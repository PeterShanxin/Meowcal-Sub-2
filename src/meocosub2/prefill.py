"""Use the local translator while a prepared session is idle."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from meocosub2.config import AppConfig
from meocosub2.gapfill import FillOutcome, fill_gaps
from meocosub2.live_translation import open_live_translator
from meocosub2.models import SubtitlePair

logger = logging.getLogger(__name__)

# Told how many cues have been answered so far, each time one lands.
Progress = Callable[[int], Awaitable[None]]


async def fill_before_the_session(
    pair: SubtitlePair,
    config: AppConfig,
    on_progress: Progress,
) -> FillOutcome:
    client, translator = await open_live_translator(config)
    filled = 0

    async def one_more() -> None:
        nonlocal filled
        filled += 1
        await on_progress(filled)

    try:
        generation = pair.source_translation
        if generation is not None:
            return await generation.fill(
                translator.translate_from_file, lambda: False, one_more, lambda: None, lambda: True
            )
        outcome = await fill_gaps(
            lambda: pair.source_lines,
            translator.translate_from_file,
            lambda: False,
            one_more,
            answer=pair.presentation.answer,
            phase="preparation",
        )
    finally:
        await client.close()
    logger.debug(
        "Answered %d unpaired cue(s) before the session started (completed=%s)",
        outcome.filled,
        outcome.completed,
    )
    return outcome
