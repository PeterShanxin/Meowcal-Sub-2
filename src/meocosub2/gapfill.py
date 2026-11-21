"""Fill source cues unanswered by a human target track or carried translation.

Target answers can supply neighboring examples without being copied onto source
cues. Model answers remain source-aligned fallbacks.
"""

from __future__ import annotations

import asyncio
import logging
from bisect import bisect_left
from collections.abc import Awaitable, Callable
from typing import Literal, NamedTuple

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


class PendingGaps:
    """Unattempted cues in this pass; a seek changes which one is next."""

    def __init__(self, lines: list[SubtitleLine], answer: Answer = own_translation) -> None:
        self._lines = lines
        self._answer = answer
        self._indices = unanswered(lines, answer)

    def __len__(self) -> int:
        return len(self._indices)

    def pop(self, reached: int | None) -> int | None:
        while self._indices:
            position = bisect_left(self._indices, reached or 0)
            index = self._indices.pop(position if position < len(self._indices) else 0)
            if not self._answer(self._lines[index]):
                return index
        return None


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
    *,
    phase: Literal["preparation", "session"] = "session",
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

    `phase` identifies preparation and playback passes in numeric DEBUG traces.
    """
    lines = followed_lines()
    pending = PendingGaps(lines, answer)
    if not pending:
        return FillOutcome(0, True)

    logger.debug("Gap fill %s starting: %d unpaired cue(s)", phase, len(pending))
    attempted = 0
    filled = 0
    completed = False
    engine_failed = False
    last_reached: int | None = None
    for _ in range(MAX_FILLED_LINES):
        # The viewer is waiting on live reads; filling ahead is not urgent and
        # the engine answers one at a time.
        while busy():
            await asyncio.sleep(YIELD_POLL_S)
        if followed_lines() is not lines:
            logger.debug("Gap fill %s stopped: following a different subtitle file", phase)
            break
        reached = from_index() if from_index is not None else None
        if reached != last_reached:
            logger.debug(
                "Gap fill %s followed position changed %s -> %s", phase, last_reached, reached
            )
            last_reached = reached
        index = pending.pop(reached)
        if index is None:
            completed = True
            break
        logger.debug("Gap fill %s selected cue=%d reached=%s", phase, index, reached)
        attempted += 1
        line = lines[index]
        try:
            translation = await translate(line.text, context_pairs(lines, index, answer))
        except asyncio.CancelledError:
            raise
        except Exception:
            # An engine that has stopped answering will not answer the next one
            # either, and retrying every remaining gap only fills the log.
            logger.exception("Gap fill %s cue=%d failed; stopping", phase, index)
            engine_failed = True
            break
        if not translation or answer(line):
            continue
        line.translated = translation
        line.translation_source = "model"
        filled += 1
        await on_filled()
    logger.debug(
        "Gap fill %s finished: filled=%d attempted=%d completed=%s engine_failed=%s",
        phase,
        filled,
        attempted,
        completed,
        engine_failed,
    )
    return FillOutcome(filled, completed, engine_failed)
