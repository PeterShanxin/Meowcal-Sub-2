"""Filling the lines the target subtitle file has no answer for.

Two subtitle files for one episode rarely carry the same lines. Where the target
file has nothing over a source cue, `assign_target_translations` leaves it
unpaired, and the plate holds the previous line for as long as that cue runs.
Measured across four English candidates for one episode, that was between 1 and
20 cues, or 4 to 93 seconds of an episode showing the wrong line.

The local model answers those, and it answers them better than it answers the
screen: the input is the file's own clean text rather than a damaged read, the
timing is known so nothing has to arrive within a cue, and the neighbouring cues
*are* paired - so the model can be shown what this translation already calls
things and asked to match it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import NamedTuple

from meocosub2.models import SubtitleLine

logger = logging.getLogger(__name__)

# How many answered cues either side of a gap are shown to the model. Enough to
# carry names and register, short of crowding out the line being asked about.
CONTEXT_BEFORE = 2
CONTEXT_AFTER = 1
# The most cues one session will answer. A well-aligned file leaves a handful and
# a poor one leaves dozens, but a file that leaves hundreds is the wrong file -
# the prep card says so before the session starts - and working through it would
# hold the single-slot engine for the length of the episode.
MAX_FILLED_LINES = 120
# How far to look for an answered neighbour. A run of unpaired cues is filled in
# playback order, so by the time a later one is reached the earlier ones usually
# count as answered; this only bounds the walk when a whole stretch fails.
CONTEXT_SEARCH_LIMIT = 12
# How long to wait before checking again whether the model is free. The engine
# serves one request at a time, so filling ahead has to yield to the read that a
# viewer is actually waiting on.
YIELD_POLL_S = 0.25

Translate = Callable[[str, list[tuple[str, str]]], Awaitable[str]]
# Where the video has reached in the file, as a position in `lines`. None
# before anything has placed it, and before a session exists at all.
FromIndex = Callable[[], int | None]


def context_pairs(lines: list[SubtitleLine], index: int) -> list[tuple[str, str]]:
    """Answered cues around `index`, source beside target, in playback order."""
    earlier: list[tuple[str, str]] = []
    start = max(0, index - CONTEXT_SEARCH_LIMIT)
    for position in range(index - 1, start - 1, -1):
        line = lines[position]
        if line.translated:
            earlier.append((line.text, line.translated))
            if len(earlier) == CONTEXT_BEFORE:
                break
    earlier.reverse()

    later: list[tuple[str, str]] = []
    stop = min(len(lines), index + 1 + CONTEXT_SEARCH_LIMIT)
    for position in range(index + 1, stop):
        line = lines[position]
        if line.translated:
            later.append((line.text, line.translated))
            if len(later) == CONTEXT_AFTER:
                break

    return earlier + later


def unanswered(lines: list[SubtitleLine]) -> list[int]:
    """Positions of the cues that carry text with nothing paired to them."""
    return [index for index, line in enumerate(lines) if line.text and not line.translated]


class FillOutcome(NamedTuple):
    """How a pass over one file's gaps ended.

    `completed` says every gap was reached, so there is nothing to come back
    for. `engine_failed` separates the two ways a pass gives up partway: the
    session taking a different file is worth retrying when it takes this one
    again, and an engine that has stopped answering is not worth retrying at all.
    """

    filled: int
    completed: bool
    engine_failed: bool = False


async def fill_gaps(
    followed_lines: Callable[[], list[SubtitleLine]],
    translate: Translate,
    busy: Callable[[], bool],
    on_filled: Callable[[], Awaitable[None]],
    from_index: FromIndex | None = None,
) -> FillOutcome:
    """Answer the unpaired cues of the file being followed, and say how it ended.

    Written back onto the lines themselves, the way `assign_target_translations`
    already pairs them, so the clock draws a filled cue with no further wiring.
    A line the model cannot answer usefully is left unpaired rather than filled
    with something wrong: the plate then behaves exactly as it does today.

    `followed_lines` is asked again at every cue rather than read once. A session
    with several candidates can stop following one and take another, and the
    gaps of a file that is no longer drawn are not worth an engine slot.

    `from_index` says where the video has reached, so the gaps ahead of the
    viewer are answered before the ones they have already watched past. Without
    it - before a session has started, or before a match has placed one - the
    file's own order is the only order there is.
    """
    lines = followed_lines()
    gaps = unanswered(lines)
    if not gaps:
        return FillOutcome(0, True)
    reached = from_index() if from_index is not None else None
    if reached is not None:
        # Rotated before the cap, not after: the budget belongs to the cues the
        # viewer is about to reach, and the ones behind them get what is left.
        gaps = [index for index in gaps if index >= reached] + [
            index for index in gaps if index < reached
        ]
    if len(gaps) > MAX_FILLED_LINES:
        logger.debug(
            "Target file leaves %d cues unpaired; answering %d of them from position %s",
            len(gaps),
            MAX_FILLED_LINES,
            "the start" if reached is None else reached,
        )
        gaps = gaps[:MAX_FILLED_LINES]

    logger.debug("Filling %d cue(s) the target file left unpaired", len(gaps))
    filled = 0
    completed = True
    engine_failed = False
    for index in gaps:
        # The viewer is waiting on live reads; filling ahead is not urgent and
        # the engine answers one at a time.
        while busy():
            await asyncio.sleep(YIELD_POLL_S)
        if followed_lines() is not lines:
            logger.debug("Stopped filling: the session is following a different subtitle file")
            completed = False
            break
        line = lines[index]
        try:
            answer = await translate(line.text, context_pairs(lines, index))
        except asyncio.CancelledError:
            raise
        except Exception:
            # An engine that has stopped answering will not answer the next one
            # either, and retrying every remaining gap only fills the log.
            logger.exception("Filling the unpaired cue at index %d failed; stopping", index)
            completed = False
            engine_failed = True
            break
        if not answer:
            continue
        line.translated = answer
        filled += 1
        await on_filled()
    logger.debug("Filled %d of %d unpaired cue(s)", filled, len(gaps))
    return FillOutcome(filled, completed, engine_failed)
