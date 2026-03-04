"""Main OCR sync loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from time import monotonic

from meocosub2.capture import capture_region, ocr_image
from meocosub2.config import AppConfig
from meocosub2.matcher import SubtitleMatcher
from meocosub2.models import SubtitlePair

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
