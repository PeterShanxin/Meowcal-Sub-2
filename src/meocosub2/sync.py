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
from meocosub2.models import SubtitleLine, SubtitlePair
from meocosub2.textnorm import clean_cjk_text
from meocosub2.translator import open_translation_client, translate_text

logger = logging.getLogger(__name__)


async def run_sync_loop(
    pair: SubtitlePair,
    config: AppConfig,
    broadcast: Callable[[str], Awaitable[None]],
) -> None:
    for source_line, target_line in zip(pair.source_lines, pair.target_lines):
        if not source_line.translated:
            source_line.translated = target_line.text

    matcher = SubtitleMatcher(pair.source_lines, config.fuzzy_threshold, config.match_window_size)
    last_displayed_index = -1
    region = tuple(config.capture_region) if config.capture_region else (0, 800, 1920, 200)
    interval_s = config.capture_interval_ms / 1000

    while True:
        loop_start = monotonic()
        try:
            image = capture_region(region)
            ocr_text = await ocr_image(image, config.ocr_language)
            result = matcher.match(ocr_text)
            if result is not None and result.line_index != last_displayed_index:
                await broadcast(result.target_text)
                last_displayed_index = result.line_index
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Sync loop iteration failed")

        elapsed = monotonic() - loop_start
        await asyncio.sleep(max(0, interval_s - elapsed))


async def run_ocr_fallback_loop(
    target_lines: list[SubtitleLine],
    config: AppConfig,
    broadcast: Callable[[str], Awaitable[None]],
) -> None:
    matcher = SubtitleMatcher(target_lines, config.fuzzy_threshold, config.match_window_size) if target_lines else None
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
            await asyncio.sleep(max(0, interval_s - elapsed))
    finally:
        if client is not None:
            await client.close()


def _normalize_live_ocr_text(text: str) -> str:
    normalized = SubtitleMatcher.normalize_text(text)
    return clean_cjk_text(normalized)
