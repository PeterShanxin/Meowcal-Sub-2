"""The live capture loop: read the subtitle strip, decide what it says, show it.

Two things can answer a read, and they answer at very different speeds. Matching
it against a downloaded subtitle file takes about a millisecond and gives the
line a translator already wrote. Translating it here takes closer to a second.
So every read is matched first, and only a read that matches nothing is sent to
the model - which keeps the plate filled through the seconds before a session
has locked onto its subtitles, and through lines the file does not carry.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic

from meocosub2.capture import capture_region, ocr_image
from meocosub2.config import AppConfig
from meocosub2.matcher import SubtitleMatcher
from meocosub2.models import MatchResult, SourceSubtitleCandidate, SubtitleLine
from meocosub2.subtitle_gate import LineChange, SubtitleGate
from meocosub2.timeline import PlaybackTimeline
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

MATCHED = "matched"
TRANSLATED = "translated"

Broadcast = Callable[[str, str], Awaitable[None]]
DebugBroadcast = Callable[[dict[str, object]], Awaitable[None]]
RegionSource = Callable[[], tuple[int, ...]]
TranslatorFactory = Callable[[], Awaitable["LiveTranslator"]]


@dataclass
class Resolution:
    """What a read came to.

    Either a line ready for the plate, or the text to translate for it - the
    clean subtitle line when one matched, the raw read when none did.
    """

    text: str = ""
    translate: str = ""
    matched: bool = False
    detail: dict[str, object] = field(default_factory=dict)

    @property
    def source(self) -> str:
        return MATCHED if self.matched else TRANSLATED


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
        self._open_translator = translator
        self._timeline = PlaybackTimeline()
        self._locked: str | None = next(iter(self._matchers)) if len(self._matchers) == 1 else None
        self._pending: str = ""
        self._pending_hits = 0
        self._misses = 0

    def saw_new_cue(self) -> None:
        self._timeline.saw_new_cue()

    def saw_same_cue(self) -> None:
        self._timeline.saw_same_cue()

    def status(self) -> dict[str, object]:
        timeline = self._timeline.status()
        return {
            "predictedMs": timeline.predicted_ms,
            "driftMs": timeline.drift_ms,
            "anchored": timeline.anchored,
            "lockedCandidateId": self._locked,
        }

    def match(self, ocr_text: str) -> Resolution | None:
        winner, result = self._match(ocr_text)
        if winner is None or result is None:
            return None
        detail: dict[str, object] = {
            "matchIdx": result.line_index,
            "matchScore": round(result.score, 1),
            "matchSpan": result.span,
            "matchSrc": result.source_text[:60],
            "candidateId": winner,
            **self.status(),
        }
        if result.translated:
            return Resolution(text=result.target_text, matched=True, detail=detail)
        # The file carries this line but nothing paired with it. Translating the
        # subtitle's own words beats translating the read: same sentence, none
        # of the OCR damage.
        return Resolution(translate=result.source_text, matched=True, detail=detail)

    async def translate(self, text: str) -> str:
        translator = await self._open_translator()
        return await translator.translate(text)

    def _match(self, ocr_text: str) -> tuple[str | None, MatchResult | None]:
        window = self._timeline.window_ms()
        if self._locked is not None:
            result = self._matchers[self._locked].match(ocr_text, window)
            if result is not None and self._timeline.accepts(
                result.start_ms, result.line_index, result.score
            ):
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
            result = matcher.match(ocr_text, window)
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
        if self._locked != best_id:
            # Only a locked candidate is trusted enough to put text on screen.
            return None, None
        if not self._timeline.accepts(best.start_ms, best.line_index, best.score):
            return None, None
        return best_id, best

    def _lock(self, result_id: str) -> None:
        logger.debug("Locked subtitle candidate %s", result_id)
        self._locked = result_id
        self._pending, self._pending_hits, self._misses = "", 0, 0


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

    def saw_new_cue(self) -> None:
        return None

    def saw_same_cue(self) -> None:
        return None

    def status(self) -> dict[str, object]:
        return {}

    def match(self, ocr_text: str) -> Resolution | None:
        # Nothing to match against until the read has been translated, so every
        # read takes the slow path.
        return None

    async def translate(self, text: str) -> str:
        translator = await self._open_translator()
        translation = await translator.translate(text)
        if not translation or self._matcher is None:
            return translation
        match = self._matcher.match(translation)
        return match.target_text if match is not None else translation


Session = CandidateSession | DirectTranslationSession


@dataclass
class _Screen:
    """What the plate is showing, and which read put it there."""

    seq: int = 0
    text: str = ""
    matched: bool = False


async def open_live_translator(config: AppConfig) -> tuple[TranslationClient, LiveTranslator]:
    client = await open_translation_client(config)
    return client, LiveTranslator(client, config.source_language, config.target_language)


async def run_session_loop(
    session: Session,
    config: AppConfig,
    broadcast: Broadcast,
    debug_broadcast: DebugBroadcast | None = None,
    region_source: RegionSource | None = None,
) -> None:
    # Read the region every frame: the live dock can reselect it without stopping.
    read_region = region_source or (lambda: tuple(config.capture_region))
    interval_s = config.capture_interval_ms / 1000
    gate = SubtitleGate()
    screen = _Screen()
    pending: asyncio.Task[None] | None = None
    empty_reads = 0
    iteration = 0

    async def publish(text: str, source: str, seq: int) -> None:
        if seq != screen.seq or not text:
            return
        # A matched line is the better answer for this read; a translation that
        # arrives after it is stale by the time it lands.
        if source == TRANSLATED and screen.matched:
            return
        if text == screen.text and source == (MATCHED if screen.matched else TRANSLATED):
            return
        screen.text = text
        screen.matched = source == MATCHED
        await broadcast(text, source)

    async def translate_into(resolution: Resolution, seq: int) -> None:
        try:
            translated = await session.translate(resolution.translate)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Translating %r failed", resolution.translate[:60])
            return
        await publish(translated, resolution.source, seq)

    def start_translation(resolution: Resolution, seq: int) -> asyncio.Task[None]:
        return asyncio.create_task(translate_into(resolution, seq))

    async def handle(ocr_text: str, fresh: bool) -> dict[str, object]:
        nonlocal pending
        resolution = session.match(ocr_text)
        if resolution is None:
            if not fresh:
                # A read of a cue already on screen only gets a second chance at
                # matching; it is not worth a second trip to the model.
                return {}
            resolution = Resolution(translate=ocr_text)
        if resolution.text:
            if pending is not None:
                pending.cancel()
                pending = None
            await publish(resolution.text, resolution.source, screen.seq)
            return resolution.detail
        if not fresh and pending is not None and not pending.done():
            return resolution.detail
        if pending is not None:
            pending.cancel()
        pending = start_translation(resolution, screen.seq)
        return resolution.detail

    try:
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
                    if empty_reads >= CLEAR_AFTER_EMPTY_READS and screen.text:
                        gate.clear()
                        screen.seq += 1
                        screen.text = ""
                        screen.matched = False
                        await broadcast("", MATCHED)
                else:
                    empty_reads = 0
                    change = gate.classify(ocr_text)
                    if change is LineChange.REPEAT:
                        session.saw_same_cue()
                        # The same subtitle is read many times over the seconds it
                        # is up, and a read that was too damaged to match can come
                        # back clean. Only worth trying while nothing has matched.
                        if not screen.matched:
                            detail = await handle(ocr_text, fresh=False)
                    else:
                        gate.remember(ocr_text)
                        screen.seq += 1
                        screen.matched = False
                        session.saw_new_cue()
                        detail = await handle(ocr_text, fresh=True)
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
                        "displayed": screen.text[:60],
                        "source": MATCHED if screen.matched else TRANSLATED,
                        "elapsedMs": int((monotonic() - started) * 1000),
                        **detail,
                    }
                )
            await asyncio.sleep(max(0.0, interval_s - (monotonic() - started)))
    finally:
        if pending is not None:
            pending.cancel()
