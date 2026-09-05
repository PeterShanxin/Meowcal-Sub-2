"""Where the video is, judged from the subtitle lines that have matched.

Nothing on screen is drawn from this clock. The overlay only ever shows a line
the OCR just read, which is what keeps it in step with the viewer. The clock
exists to answer a different question: a subtitle file repeats short lines -
"yes", "what?", a name - dozens of times across an episode, and text alone
cannot say which of them is on screen. Position can.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import monotonic

logger = logging.getLogger(__name__)

# How far either side of the predicted position a line is still believable.
# Forward is the generous side: playback moves that way, and a run of missed
# reads leaves the next hit ahead of where the clock last heard from.
WINDOW_BACK_MS = 8_000
WINDOW_FORWARD_MS = 25_000
# A line found outside the window has to be this convincing before it is even
# considered, and then has to agree with a second read before the clock moves.
SEEK_SCORE = 88.0
SEEK_CLUSTER_LINES = 20
# Consecutive rejected matches before the anchor is treated as wrong rather than
# the reads as unlucky. Without this a bad anchor can never be escaped.
ANCHOR_ABANDON_MISSES = 8
# An anchor nothing has agreed with for this long is not describing this video.
ANCHOR_MAX_AGE_S = 90.0
# The longest a single subtitle is assumed to genuinely stay on screen. Past
# this the viewer has paused, and the clock should not run on without them.
CUE_HOLD_S = 6.0


@dataclass
class TimelineStatus:
    """What the clock believes, for the debug panel and the event log."""

    predicted_ms: int | None
    drift_ms: int | None
    anchored: bool
    misses: int


class PlaybackTimeline:
    """The playback position implied by the subtitle lines that have matched.

    Anchored by every accepted match, advanced by the wall clock, and held still
    while one subtitle stays on screen longer than a subtitle plausibly lasts.
    """

    def __init__(self) -> None:
        self._anchor_ms: int | None = None
        self._anchor_at = 0.0
        self._paused_s = 0.0
        self._cue_since: float | None = None
        self._cue_credited_s = 0.0
        self._misses = 0
        self._drift_ms: int | None = None
        self._pending_seek_index: int | None = None

    @property
    def anchored(self) -> bool:
        return self._anchor_ms is not None

    def status(self, now: float | None = None) -> TimelineStatus:
        return TimelineStatus(
            predicted_ms=self.predicted_ms(now),
            drift_ms=self._drift_ms,
            anchored=self.anchored,
            misses=self._misses,
        )

    def predicted_ms(self, now: float | None = None) -> int | None:
        if self._anchor_ms is None:
            return None
        now = monotonic() if now is None else now
        return int(self._anchor_ms + (now - self._anchor_at - self._paused_s) * 1000)

    def window_ms(self, now: float | None = None) -> tuple[int, int] | None:
        predicted = self.predicted_ms(now)
        if predicted is None:
            return None
        return predicted - WINDOW_BACK_MS, predicted + WINDOW_FORWARD_MS

    def saw_new_cue(self, now: float | None = None) -> None:
        """A different subtitle is on screen, so the clock is running normally."""
        self._cue_since = monotonic() if now is None else now
        self._cue_credited_s = 0.0

    def saw_same_cue(self, now: float | None = None) -> None:
        """The same subtitle is still on screen.

        Past the length a subtitle plausibly runs, the extra seconds are the
        viewer sitting on a paused frame rather than dialogue holding, so they
        are taken back out of the clock.
        """
        if self._cue_since is None:
            return
        now = monotonic() if now is None else now
        overrun = (now - self._cue_since) - CUE_HOLD_S
        if overrun > self._cue_credited_s:
            self._paused_s += overrun - self._cue_credited_s
            self._cue_credited_s = overrun

    def accepts(self, line_start_ms: int, line_index: int, score: float, now: float | None = None) -> bool:
        """Whether a matched line is where the video actually is.

        An unanchored clock believes the first thing it is told. An anchored one
        believes anything near its prediction, and moves to somewhere else only
        for a high score that a second read agrees with - which is what a viewer
        dragging the progress bar looks like, and what one unlucky match does not.
        """
        now = monotonic() if now is None else now
        self._expire_stale_anchor(now)

        predicted = self.predicted_ms(now)
        if predicted is None:
            self._anchor(line_start_ms, now, drift=None)
            return True

        if predicted - WINDOW_BACK_MS <= line_start_ms <= predicted + WINDOW_FORWARD_MS:
            self._anchor(line_start_ms, now, drift=line_start_ms - predicted)
            return True

        self._misses += 1
        if score < SEEK_SCORE:
            self._forget_anchor_if_hopeless()
            return False

        pending = self._pending_seek_index
        if pending is not None and abs(line_index - pending) <= SEEK_CLUSTER_LINES:
            logger.debug("Timeline re-anchored to line %d after a seek", line_index)
            self._anchor(line_start_ms, now, drift=None)
            return True

        self._pending_seek_index = line_index
        self._forget_anchor_if_hopeless()
        return False

    def _anchor(self, line_start_ms: int, now: float, drift: int | None) -> None:
        self._anchor_ms = line_start_ms
        self._anchor_at = now
        self._paused_s = 0.0
        self._drift_ms = drift
        self._misses = 0
        self._pending_seek_index = None
        self.saw_new_cue(now)

    def _forget_anchor_if_hopeless(self) -> None:
        if self._misses >= ANCHOR_ABANDON_MISSES:
            logger.debug("Timeline dropped its anchor after %d rejected matches", self._misses)
            self.reset()

    def _expire_stale_anchor(self, now: float) -> None:
        if self._anchor_ms is not None and now - self._anchor_at > ANCHOR_MAX_AGE_S:
            logger.debug("Timeline dropped an anchor nothing agreed with for %.0fs", ANCHOR_MAX_AGE_S)
            self.reset()

    def reset(self) -> None:
        self._anchor_ms = None
        self._anchor_at = 0.0
        self._paused_s = 0.0
        self._cue_since = None
        self._cue_credited_s = 0.0
        self._misses = 0
        self._drift_ms = None
        self._pending_seek_index = None
