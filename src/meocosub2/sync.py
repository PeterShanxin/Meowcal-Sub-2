"""The live capture loop: read the subtitle strip, decide what it says, show it."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from time import monotonic

from meocosub2.capture import capture_region, ocr_image
from meocosub2.config import AppConfig
from meocosub2.matcher import SubtitleMatcher
from meocosub2.models import MatchResult, SourceSubtitleCandidate, SubtitleLine
from meocosub2.subtitle_gate import LineChange, SubtitleGate
from meocosub2.translator import TranslationClient, is_untranslatable, open_translation_client

logger = logging.getLogger(__name__)

# A candidate has to win by this much before the session commits to it, or by
# agreeing with itself across this many reads.
AUTO_LOCK_SCORE = 92.0
AUTO_CONFIRM_HITS = 2
AUTO_UNLOCK_MISSES = 3
# Consecutive empty reads before the overlay clears. One blank frame is a cue
# transition; several in a row mean nothing is on screen.
CLEAR_AFTER_EMPTY_READS = 3
TRANSLATION_CACHE_SIZE = 64
CONTEXT_LINES = 3

Broadcast = Callable[[str], Awaitable[None]]
DebugBroadcast = Callable[[dict[str, object]], Awaitable[None]]
RegionSource = Callable[[], tuple[int, ...]]
TranslatorFactory = Callable[[], Awaitable["LiveTranslator"]]


class LiveTranslator:
    """Caches translations and carries recent lines as context, like v1's session cache."""

    def __init__(self, client: TranslationClient, source_language: str, target_language: str) -> None:
        self._client = client
        self._source_language = source_language
        self._target_language = target_language
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._context: deque[str] = deque(maxlen=CONTEXT_LINES)

    async def translate(self, text: str) -> str:
        key = SubtitleMatcher.normalize_text(text)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        translated = await self._client.translate(
            text, self._source_language, self._target_language, list(self._context)
        )
        if translated:
            self._cache[key] = translated
            while len(self._cache) > TRANSLATION_CACHE_SIZE:
                self._cache.popitem(last=False)
            self._context.append(translated)
        return translated


class CandidateSession:
    """Matches OCR against downloaded subtitle candidates and shows the paired line.

    With one candidate this is a straight match. With several it locks onto the
    one that agrees with the screen and unlocks when it stops agreeing, so a
    wrong release or a mismatched cut does not pin the session to bad timings.
    """

    mode = "candidates"

    def __init__(
        self,
        candidates: list[SourceSubtitleCandidate],
        config: AppConfig,
        translator: TranslatorFactory,
    ) -> None:
        self._matchers = {
            candidate.result_id: SubtitleMatcher(
                candidate.pair.source_lines,
                config.fuzzy_threshold,
                config.match_window_size,
                config.match_window_backward,
                target_language=config.target_language,
            )
            for candidate in candidates
        }
        self._candidates = {candidate.result_id: candidate for candidate in candidates}
        self._open_translator = translator
        self._locked: str | None = next(iter(self._matchers)) if len(self._matchers) == 1 else None
        self._pending: str = ""
        self._pending_hits = 0
        self._misses = 0

    async def resolve(self, ocr_text: str) -> tuple[str, dict[str, object]]:
        winner, result = self._match(ocr_text)
        if winner is None or result is None:
            return "", {"matchIdx": None, "matchScore": None, "lockedCandidateId": self._locked}

        text = result.target_text
        if not self._line_is_translated(winner, result.line_index):
            translator = await self._open_translator()
            text = await translator.translate(result.source_text) or ""
        return text, {
            "matchIdx": result.line_index,
            "matchScore": round(result.score, 1),
            "matchSrc": result.source_text[:60],
            "candidateId": winner,
            "lockedCandidateId": self._locked,
        }

    def _match(self, ocr_text: str) -> tuple[str | None, MatchResult | None]:
        if self._locked is not None:
            result = self._matchers[self._locked].match(ocr_text)
            if result is not None:
                self._misses = 0
                return self._locked, result
            self._misses += 1
            if len(self._matchers) == 1 or self._misses < AUTO_UNLOCK_MISSES:
                return None, None
            logger.debug("Unlocking subtitle candidate %s after %d misses", self._locked, self._misses)
            self._locked = None
            self._misses = 0

        best_id, best = "", None
        for result_id, matcher in self._matchers.items():
            result = matcher.match(ocr_text)
            if result is not None and (best is None or result.score > best.score):
                best_id, best = result_id, result
        if best is None:
            return None, None

        if best.score >= AUTO_LOCK_SCORE:
            self._lock(best_id)
        elif best_id == self._pending:
            self._pending_hits += 1
            if self._pending_hits >= AUTO_CONFIRM_HITS:
                self._lock(best_id)
        else:
            self._pending, self._pending_hits = best_id, 1
        # Only a locked candidate is trusted enough to put text on screen.
        return (best_id, best) if self._locked == best_id else (None, None)

    def _lock(self, result_id: str) -> None:
        logger.debug("Locked subtitle candidate %s", result_id)
        self._locked = result_id
        self._pending, self._pending_hits, self._misses = "", 0, 0

    def _line_is_translated(self, result_id: str, line_index: int) -> bool:
        candidate = self._candidates[result_id]
        return any(
            line.index == line_index and bool(line.translated)
            for line in candidate.pair.source_lines
        )


class DirectTranslationSession:
    """Translates what OCR reads, with no source subtitle file to match against."""

    mode = "translation"

    def __init__(
        self,
        target_lines: list[SubtitleLine],
        config: AppConfig,
        translator: TranslatorFactory,
    ) -> None:
        self._open_translator = translator
        self._matcher = (
            SubtitleMatcher(
                target_lines,
                config.fuzzy_threshold,
                config.match_window_size,
                config.match_window_backward,
                target_language=config.target_language,
            )
            if target_lines
            else None
        )

    async def resolve(self, ocr_text: str) -> tuple[str, dict[str, object]]:
        translator = await self._open_translator()
        translation = await translator.translate(ocr_text)
        if not translation:
            return "", {"translation": ""}
        if self._matcher is not None:
            match = self._matcher.match(translation)
            if match is not None:
                return match.target_text, {
                    "translation": translation[:60],
                    "matchIdx": match.line_index,
                    "matchScore": round(match.score, 1),
                }
        return translation, {"translation": translation[:60]}


async def open_live_translator(config: AppConfig) -> tuple[TranslationClient, LiveTranslator]:
    client = await open_translation_client(config)
    return client, LiveTranslator(client, config.source_language, config.target_language)


async def run_session_loop(
    session: CandidateSession | DirectTranslationSession,
    config: AppConfig,
    broadcast: Broadcast,
    debug_broadcast: DebugBroadcast | None = None,
    region_source: RegionSource | None = None,
) -> None:
    # Read the region every frame: the live dock can reselect it without stopping.
    read_region = region_source or (lambda: tuple(config.capture_region))
    interval_s = config.capture_interval_ms / 1000
    gate = SubtitleGate()
    displayed = ""
    empty_reads = 0
    iteration = 0

    while True:
        iteration += 1
        started = monotonic()
        ocr_text = ""
        change: LineChange | None = None
        detail: dict[str, object] = {}
        try:
            image = await asyncio.to_thread(capture_region, read_region())
            ocr_text = await ocr_image(image, config.ocr_language)

            if is_untranslatable(ocr_text):
                empty_reads += 1
                if empty_reads >= CLEAR_AFTER_EMPTY_READS and displayed:
                    gate.clear()
                    displayed = ""
                    await broadcast("")
            else:
                empty_reads = 0
                change = gate.classify(ocr_text)
                if change is not LineChange.REPEAT:
                    gate.remember(ocr_text)
                    text, detail = await session.resolve(ocr_text)
                    if text and text != displayed:
                        displayed = text
                        await broadcast(text)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Capture loop #%d failed (ocr=%r)", iteration, ocr_text[:60])

        if debug_broadcast is not None:
            await debug_broadcast(
                {
                    "iteration": iteration,
                    "ocrText": ocr_text[:120],
                    "change": change.value if change else "empty",
                    "displayed": displayed[:60],
                    "elapsedMs": int((monotonic() - started) * 1000),
                    **detail,
                }
            )
        await asyncio.sleep(max(0.0, interval_s - (monotonic() - started)))
