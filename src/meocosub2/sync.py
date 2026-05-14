"""Main OCR sync loop."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from time import monotonic

from meocosub2.capture import capture_region, ocr_image
from meocosub2.config import AppConfig
from meocosub2.matcher import SubtitleMatcher
from meocosub2.models import MatchResult, SourceSubtitleCandidate, SubtitleLine, SubtitlePair
from meocosub2.textnorm import clean_cjk_text
from meocosub2.translator import open_translation_client, translate_text

logger = logging.getLogger(__name__)

AUTO_LOCK_SCORE = 92.0
AUTO_CONFIRM_HITS = 2
AUTO_UNLOCK_MISSES = 3


async def run_sync_loop(
    pair: SubtitlePair,
    config: AppConfig,
    broadcast: Callable[[str], Awaitable[None]],
    debug_broadcast: Callable[[dict[str, object]], Awaitable[None]] | None = None,
) -> None:
    for source_line, target_line in zip(pair.source_lines, pair.target_lines):
        if not source_line.translated:
            source_line.translated = target_line.text

    matcher = SubtitleMatcher(
        pair.source_lines,
        config.fuzzy_threshold,
        config.match_window_size,
        target_language=config.target_language,
    )
    last_displayed_index = -1
    if not config.capture_region:
        logger.warning("No capture region configured — using default (0, 800, 1920, 200). Set capture.region in config for your screen.")
    region = tuple(config.capture_region) if config.capture_region else (0, 800, 1920, 200)
    interval_s = config.capture_interval_ms / 1000
    iteration = 0

    while True:
        iteration += 1
        loop_start = monotonic()
        ocr_text = ""
        result = None
        try:
            image = capture_region(region)
            ocr_text = await ocr_image(image, config.ocr_language)
            result = matcher.match(ocr_text)
            if result is not None and result.line_index != last_displayed_index:
                logger.debug("SYNC #%d broadcast idx=%d score=%.1f text=%r", iteration, result.line_index, result.score, result.target_text[:60])
                await broadcast(result.target_text)
                last_displayed_index = result.line_index
            else:
                logger.debug(
                    "SYNC #%d ocr=%r match=%s",
                    iteration,
                    ocr_text[:60],
                    f"idx={result.line_index} (same)" if result else "miss",
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Sync loop #%d failed (ocr=%r)", iteration, ocr_text[:60])

        elapsed = monotonic() - loop_start
        if debug_broadcast is not None:
            await debug_broadcast({
                "iteration": iteration,
                "ocrText": ocr_text[:120],
                "matchIdx": result.line_index if result else None,
                "matchScore": round(result.score, 1) if result else None,
                "matchSrc": result.source_text[:60] if result else None,
                "elapsedMs": int(elapsed * 1000),
            })
            elapsed = monotonic() - loop_start
        await asyncio.sleep(max(0, interval_s - elapsed))


async def run_ocr_fallback_loop(
    target_lines: list[SubtitleLine],
    config: AppConfig,
    broadcast: Callable[[str], Awaitable[None]],
    debug_broadcast: Callable[[dict[str, object]], Awaitable[None]] | None = None,
) -> None:
    matcher = SubtitleMatcher(target_lines, config.fuzzy_threshold, config.match_window_size, target_language=config.target_language) if target_lines else None
    translation_context: deque[str] = deque(maxlen=3)
    translation_cache: OrderedDict[str, str] = OrderedDict()
    last_ocr_key = ""
    last_displayed = ""
    region = tuple(config.capture_region) if config.capture_region else (0, 800, 1920, 200)
    interval_s = config.capture_interval_ms / 1000
    client = None
    model = None

    try:
        client, model = await open_translation_client(config)

        while True:
            loop_start = monotonic()
            ocr_key = ""
            display_text = ""
            try:
                image = capture_region(region)
                ocr_text = await ocr_image(image, config.ocr_language)
                ocr_key = _normalize_live_ocr_text(ocr_text)
                if len(ocr_key) < 3 or ocr_key == last_ocr_key:
                    elapsed = monotonic() - loop_start
                    await asyncio.sleep(max(0, interval_s - elapsed))
                    continue

                last_ocr_key = ocr_key
                translation = translation_cache.get(ocr_key)
                if translation is None:
                    translation = await translate_text(
                        ocr_text,
                        config,
                        context_lines=list(translation_context),
                        client=client,
                        model=model,
                    )
                    translation_cache[ocr_key] = translation
                    translation_cache.move_to_end(ocr_key)
                    while len(translation_cache) > 32:
                        translation_cache.popitem(last=False)

                if translation:
                    translation_context.append(translation)

                display_text = translation
                if matcher is not None and translation:
                    match = matcher.match(translation)
                    if match is not None:
                        display_text = match.target_text

                if display_text and display_text != last_displayed:
                    await broadcast(display_text)
                    last_displayed = display_text
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("OCR fallback loop iteration failed")

            elapsed = monotonic() - loop_start
            if debug_broadcast is not None:
                await debug_broadcast({
                    "ocrText": ocr_key[:120],
                    "matchIdx": None,
                    "matchScore": None,
                    "matchSrc": None,
                    "translation": (display_text or "")[:60],
                    "elapsedMs": int(elapsed * 1000),
                })
                elapsed = monotonic() - loop_start
            await asyncio.sleep(max(0, interval_s - elapsed))
    finally:
        if client is not None:
            await client.close()


async def run_auto_candidate_sync_loop(
    candidates: list[SourceSubtitleCandidate],
    config: AppConfig,
    broadcast: Callable[[str], Awaitable[None]],
    debug_broadcast: Callable[[dict[str, object]], Awaitable[None]] | None = None,
) -> None:
    if not candidates:
        raise RuntimeError("Auto subtitle matching needs at least one source candidate.")

    matchers = [
        _CandidateMatcher(
            candidate=candidate,
            matcher=SubtitleMatcher(
                candidate.pair.source_lines,
                config.fuzzy_threshold,
                config.match_window_size,
                target_language=config.target_language,
            ),
        )
        for candidate in candidates
    ]
    locked: _CandidateMatcher | None = None
    pending_id = ""
    pending_hits = 0
    locked_misses = 0
    last_displayed_key = ""
    region = tuple(config.capture_region) if config.capture_region else (0, 800, 1920, 200)
    interval_s = config.capture_interval_ms / 1000
    client = None
    model = None
    translation_cache: OrderedDict[str, str] = OrderedDict()
    needs_live_translation = not any(
        line.translated
        for candidate in candidates
        for line in candidate.pair.source_lines
    )
    iteration = 0

    try:
        if needs_live_translation:
            client, model = await open_translation_client(config)

        while True:
            iteration += 1
            loop_start = monotonic()
            ocr_text = ""
            result: MatchResult | None = None
            winner: _CandidateMatcher | None = None
            locked_this_frame = False
            try:
                image = capture_region(region)
                ocr_text = await ocr_image(image, config.ocr_language)

                if locked is not None:
                    result = locked.matcher.match(ocr_text)
                    winner = locked if result is not None else None
                    if result is None:
                        locked_misses += 1
                        if locked_misses >= AUTO_UNLOCK_MISSES:
                            logger.debug("AUTO match unlock: candidate=%s misses=%d", locked.candidate.result_id, locked_misses)
                            locked = None
                            pending_id = ""
                            pending_hits = 0
                    else:
                        locked_misses = 0

                if locked is None:
                    winner, result = _best_candidate_match(matchers, ocr_text)
                    if winner is not None and result is not None:
                        if result.score >= AUTO_LOCK_SCORE:
                            locked = winner
                            locked_this_frame = True
                            pending_id = ""
                            pending_hits = 0
                        elif winner.candidate.result_id == pending_id:
                            pending_hits += 1
                            if pending_hits >= AUTO_CONFIRM_HITS:
                                locked = winner
                                locked_this_frame = True
                                pending_id = ""
                                pending_hits = 0
                        else:
                            pending_id = winner.candidate.result_id
                            pending_hits = 1

                can_display = result is not None and locked is not None and winner is locked
                if can_display:
                    display_text = result.target_text
                    if needs_live_translation and client is not None:
                        display_text = await _translate_cached(result.source_text, config, client, model, translation_cache)
                    display_key = f"{winner.candidate.result_id if winner else ''}:{result.line_index}:{display_text}"
                    if display_text and display_key != last_displayed_key:
                        logger.debug(
                            "AUTO match broadcast candidate=%s idx=%d score=%.1f locked=%s text=%r",
                            winner.candidate.result_id if winner else "",
                            result.line_index,
                            result.score,
                            locked is not None,
                            display_text[:60],
                        )
                        await broadcast(display_text)
                        last_displayed_key = display_key
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Auto sync loop #%d failed (ocr=%r)", iteration, ocr_text[:60])

            elapsed = monotonic() - loop_start
            if debug_broadcast is not None:
                await debug_broadcast({
                    "iteration": iteration,
                    "ocrText": ocr_text[:120],
                    "matchIdx": result.line_index if result else None,
                    "matchScore": round(result.score, 1) if result else None,
                    "matchSrc": result.source_text[:60] if result else None,
                    "candidateId": winner.candidate.result_id if winner else None,
                    "lockedCandidateId": locked.candidate.result_id if locked else None,
                    "lockedThisFrame": locked_this_frame,
                    "elapsedMs": int(elapsed * 1000),
                })
                elapsed = monotonic() - loop_start
            await asyncio.sleep(max(0, interval_s - elapsed))
    finally:
        if client is not None:
            await client.close()


def _normalize_live_ocr_text(text: str) -> str:
    normalized = SubtitleMatcher.normalize_text(text)
    return clean_cjk_text(normalized)


class _CandidateMatcher:
    def __init__(self, candidate: SourceSubtitleCandidate, matcher: SubtitleMatcher) -> None:
        self.candidate = candidate
        self.matcher = matcher


def _best_candidate_match(
    matchers: list[_CandidateMatcher],
    ocr_text: str,
) -> tuple[_CandidateMatcher | None, MatchResult | None]:
    best_candidate: _CandidateMatcher | None = None
    best_result: MatchResult | None = None
    for candidate in matchers:
        result = candidate.matcher.match(ocr_text)
        if result is None:
            continue
        if best_result is None or result.score > best_result.score:
            best_candidate = candidate
            best_result = result
    return best_candidate, best_result


async def _translate_cached(
    text: str,
    config: AppConfig,
    client,
    model: str | None,
    cache: OrderedDict[str, str],
) -> str:
    key = _normalize_live_ocr_text(text)
    cached = cache.get(key)
    if cached is not None:
        cache.move_to_end(key)
        return cached
    translated = await translate_text(text, config, client=client, model=model)
    cache[key] = translated
    while len(cache) > 64:
        cache.popitem(last=False)
    return translated
