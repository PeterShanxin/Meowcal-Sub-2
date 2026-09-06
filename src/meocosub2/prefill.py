"""Answering the target file's gaps in the window before a session starts.

Between choosing a target file and pressing Start there is a stretch - reading
the prep card, dragging the capture region over the player, finding the moment
to start from - where the translation engine has nothing else to do. Every cue
answered there is one the viewer never waits on later: during playback the
engine serves one request at a time, so a fill and a live read compete for the
same slot, and the read is the one somebody is watching for.

Nothing is handed over when the session starts. The answers are written onto the
same `SubtitleLine` objects the session's matchers wrap, and the session's own
filler recomputes what is still unpaired - so an interrupted pass simply carries
on from wherever it reached.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from meocosub2.config import AppConfig
from meocosub2.gapfill import FillOutcome, fill_gaps
from meocosub2.models import SubtitleLine
from meocosub2.sync import open_live_translator

logger = logging.getLogger(__name__)

# Told how many cues have been answered so far, each time one lands.
Progress = Callable[[int], Awaitable[None]]


async def fill_before_the_session(
    lines: list[SubtitleLine],
    config: AppConfig,
    on_progress: Progress,
) -> FillOutcome:
    """Answer what the target file left unpaired, reporting each cue as it lands.

    Nothing is competing for the engine yet, so this never yields, and there is
    no clock to order by - the file's own order is the order the viewer will
    reach the cues in.
    """
    client, translator = await open_live_translator(config)
    filled = 0

    async def one_more() -> None:
        nonlocal filled
        filled += 1
        await on_progress(filled)

    try:
        outcome = await fill_gaps(
            lambda: lines,
            translator.translate_from_file,
            lambda: False,
            one_more,
        )
    finally:
        await client.close()
    logger.debug(
        "Answered %d unpaired cue(s) before the session started (completed=%s)",
        outcome.filled,
        outcome.completed,
    )
    return outcome
