"""Fill source cues unanswered by a human target track or carried translation.

Target answers can supply neighboring examples without being copied onto source
cues. Model answers remain source-aligned fallbacks.
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
Answer = Callable[[SubtitleLine], str]


def own_translation(line: SubtitleLine) -> str:
    return line.translated


def context_pairs(
    lines: list[SubtitleLine], index: int, answer: Answer = own_translation
) -> list[tuple[str, str]]:
    """Answered cues around `index`, source beside target, in playback order."""
    earlier: list[tuple[str, str]] = []
    start = max(0, index - CONTEXT_SEARCH_LIMIT)
    for position in range(index - 1, start - 1, -1):
        line = lines[position]
        translation = answer(line)
        if translation:
            earlier.append((line.text, translation))
            if len(earlier) == CONTEXT_BEFORE:
                break
    earlier.reverse()

    later: list[tuple[str, str]] = []
    stop = min(len(lines), index + 1 + CONTEXT_SEARCH_LIMIT)
    for position in range(index + 1, stop):
        line = lines[position]
        translation = answer(line)
        if translation:
            later.append((line.text, translation))
            if len(later) == CONTEXT_AFTER:
                break

    return earlier + later


def unanswered(lines: list[SubtitleLine], answer: Answer = own_translation) -> list[int]:
    """Positions of the cues that carry text with nothing paired to them."""
    return [index for index, line in enumerate(lines) if line.text and not answer(line)]


def next_gap(
    lines: list[SubtitleLine],
    attempted: set[int],
    reached: int | None,
    answer: Answer = own_translation,
) -> int | None:
    """The cue to answer next: the first one still unpaired at or after `reached`.

    Wraps to the start once nothing is left ahead, so the cues the viewer has
    already watched past are answered last rather than not at all. Asked afresh
    for every cue, which is what lets a seek move the fill: an order chosen once
    would keep working through the file from wherever the video was when the
    pass began.

    A cue the model declined counts as attempted. Asking again inside one pass
    would spend the engine on the answer it has already refused to give.
    """
    gaps = [index for index in unanswered(lines, answer) if index not in attempted]
    if not gaps:
        return None
    if reached is None:
        return gaps[0]
    return next((index for index in gaps if index >= reached), gaps[0])


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
    answer: Answer = own_translation,
) -> FillOutcome:
    """Answer the unpaired cues of the file being followed, and say how it ended.

    Answers are written onto the source lines as model fallbacks. The presentation
    track reads those same objects when their interval arrives. Human target cues
    remain in their own track; `answer` supplies their coverage and context.

    `followed_lines` is asked again at every cue rather than read once. A session
    with several candidates can stop following one and take another, and the
    gaps of a file that is no longer drawn are not worth an engine slot.

    `from_index` says where the video has reached, and is asked again for every
    cue rather than read once. The order a pass would freeze at its start is
    wrong twice over: the session's filler runs before the first read, so it
    begins with the video unplaced, and a viewer can seek at any point after
    that. Choosing the next cue against the position as it is now covers both,
    and covers a session that never places the video at all - there the file's
    own order is the only order there is.
    """
    lines = followed_lines()
    if not unanswered(lines, answer):
        return FillOutcome(0, True)

    logger.debug(
        "Filling the %d cue(s) the target file left unpaired", len(unanswered(lines, answer))
    )
    attempted: set[int] = set()
    filled = 0
    completed = False
    engine_failed = False
    for _ in range(MAX_FILLED_LINES):
        # The viewer is waiting on live reads; filling ahead is not urgent and
        # the engine answers one at a time.
        while busy():
            await asyncio.sleep(YIELD_POLL_S)
        if followed_lines() is not lines:
            logger.debug("Stopped filling: the session is following a different subtitle file")
            break
        index = next_gap(lines, attempted, from_index() if from_index is not None else None, answer)
        if index is None:
            completed = True
            break
        attempted.add(index)
        line = lines[index]
        try:
            translation = await translate(line.text, context_pairs(lines, index, answer))
        except asyncio.CancelledError:
            raise
        except Exception:
            # An engine that has stopped answering will not answer the next one
            # either, and retrying every remaining gap only fills the log.
            logger.exception("Filling the unpaired cue at index %d failed; stopping", index)
            engine_failed = True
            break
        if not translation:
            continue
        line.translated = translation
        line.translation_source = "model"
        filled += 1
        await on_filled()
    logger.debug("Filled %d cue(s); %d attempted", filled, len(attempted))
    return FillOutcome(filled, completed, engine_failed)
