"""Where the video is, judged from the subtitle lines that have matched.

Most reads never match: the burned-in subtitles are usually a different
translation from the downloaded file, so the words differ where the dialogue
does not. What every read does carry is a position, and one match fixes it for
the rest of the episode - so this clock is what the overlay plays from, and
matching is what keeps it honest.

It also settles a question text alone cannot. A subtitle file repeats short
lines - "yes", "what?", a name - dozens of times across an episode, and only
position says which of them is the one on screen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import monotonic

logger = logging.getLogger(__name__)

# Search eligibility is deliberately wider than evidence for moving the clock.
WINDOW_BACK_MS = 8_000
WINDOW_FORWARD_MS = 25_000
# A line the clock did not expect has to be this convincing before it is even
# considered, and then has to agree with a second read before the clock moves.
# Both signals arrive on this scale: a near-exact text score, or a cosine put on
# it by the matcher, where 0.88 sits at the top of the 0.62-0.93 band genuine
# semantic matches occupied and far above the 0.55 junk ceiling.
SEEK_SCORE = 88.0
# How far apart two matches may put the video and still be describing the same
# playback. A viewer watches forward, so the distance between the subtitle file
# and the wall clock barely moves: measured over a real session it held to
# 28.9s +/- 0.8s across six minutes and 150 lines, with no rate drift.
AGREEING_OFFSET_MS = 2_000
# Corroboration must come from nearby dialogue, not an unrelated later scene.
CONFIRMATION_MAX_AGE_S = 15.0
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
        self._cue_started_ms: int | None = None
        self._cue_credited_s = 0.0
        self._misses = 0
        self._drift_ms: int | None = None
        self._pending_offset_ms: int | None = None
        self._pending_index: int | None = None
        self._pending_at = 0.0

    @property
    def anchored(self) -> bool:
        return self._anchor_ms is not None

    @property
    def anchor_ms(self) -> int | None:
        """The file position the last accepted match fixed the clock to."""
        return self._anchor_ms

    def status(self, now: float | None = None) -> TimelineStatus:
        return TimelineStatus(
            predicted_ms=self.predicted_ms(now),
            drift_ms=self._drift_ms,
            anchored=self.anchored,
            misses=self._misses,
        )

    def _running_ms(self, now: float) -> int | None:
        """Where the wall clock alone says the video is."""
        if self._anchor_ms is None:
            return None
        return int(self._anchor_ms + (now - self._anchor_at - self._paused_s) * 1000)

    def _held_ms(self, now: float) -> int | None:
        """Where the clock stood when the cue now frozen on screen appeared.

        A cue that has outlasted any subtitle is a paused frame, and the line
        the viewer is looking at is the one that was on screen when it went up -
        not the two or three the clock ran on through before it stopped.
        `saw_same_cue` freezes the clock; this walks it back to the pause.

        Provisional on purpose: the moment a different cue is read the video is
        moving again, and the clock carries on from where it actually was.
        """
        if self._cue_since is None or self._cue_started_ms is None:
            return None
        if now - self._cue_since <= CUE_HOLD_S:
            return None
        return self._cue_started_ms

    def predicted_ms(self, now: float | None = None) -> int | None:
        now = monotonic() if now is None else now
        running = self._running_ms(now)
        held = self._held_ms(now)
        if running is None or held is None:
            return running
        return min(running, held)

    def position_ms(self, now: float | None = None) -> int | None:
        """Where the video is, for a caller about to draw a line from the clock.

        Unlike `predicted_ms` this first drops an anchor nothing has agreed with
        for too long. A caller that only reads the clock would otherwise keep a
        wrong anchor alive forever, because nothing else would be checking it.
        """
        now = monotonic() if now is None else now
        self._expire_stale_anchor(now)
        return self.predicted_ms(now)

    def window_ms(self, now: float | None = None) -> tuple[int, int] | None:
        predicted = self.predicted_ms(now)
        if predicted is None:
            return None
        return predicted - WINDOW_BACK_MS, predicted + WINDOW_FORWARD_MS

    def saw_new_cue(self, now: float | None = None) -> None:
        """A different subtitle is on screen, so the clock is running normally."""
        now = monotonic() if now is None else now
        self._cue_since = now
        # Taken from the running clock rather than the reported one, so that
        # walking back to a pause does not leave the clock walked back forever.
        self._cue_started_ms = self._running_ms(now)
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

    def accepts(
        self,
        line_start_ms: int,
        line_index: int,
        score: float,
        now: float | None = None,
        seen_at: float | None = None,
        confident: bool = False,
    ) -> bool:
        """Whether a matched line is where the video actually is.

        Small corrections and strong in-window evidence follow the clock.
        Larger weak moves require different cues whose observation times imply
        the same playback offset.
        A whole-file seek additionally needs strong text or agreement between
        text and meaning. Repeated OCR of one cue cannot confirm itself.
        """
        now = monotonic() if now is None else now
        # The line was on screen before the frame that read it: a capture every
        # `interval` plus the OCR itself puts every read a beat behind the
        # picture. Anchoring at the moment this cue was first seen, rather than
        # at the moment it was recognised, keeps that beat out of the clock -
        # otherwise every line the clock places is late by the same amount.
        at = self._cue_since if seen_at is None else seen_at
        at = now if at is None else min(at, now)
        self._expire_stale_anchor(now)

        # Where this match puts the video, relative to the wall clock. Two
        # matches of the same playback imply nearly the same distance however
        # far apart they are, which is what makes them comparable at all.
        offset_ms = line_start_ms - int(at * 1000)

        predicted = self.predicted_ms(at)
        if predicted is None:
            if (
                confident
                or score >= SEEK_SCORE
                or self._agrees_with_pending(offset_ms, line_index, at)
            ):
                self._anchor(line_start_ms, at, drift=None)
                return True
            self._remember_pending(offset_ms, line_index, at)
            return False

        in_window = predicted - WINDOW_BACK_MS <= line_start_ms <= predicted + WINDOW_FORWARD_MS
        if abs(line_start_ms - predicted) <= AGREEING_OFFSET_MS or (
            in_window and (confident or score >= SEEK_SCORE)
        ):
            self._anchor(line_start_ms, at, drift=line_start_ms - predicted)
            return True

        self._misses += 1
        if not in_window and score < SEEK_SCORE and not confident:
            self._pending_offset_ms = None
            self._forget_anchor_if_hopeless()
            return False

        if self._agrees_with_pending(offset_ms, line_index, at):
            logger.debug("Timeline re-anchored to line %d after a seek", line_index)
            self._anchor(line_start_ms, at, drift=None)
            return True

        # Recorded after the anchor is given up rather than before, so that
        # abandoning a hopeless anchor does not also discard the evidence that
        # would let the next match replace it.
        self._forget_anchor_if_hopeless()
        self._remember_pending(offset_ms, line_index, at)
        return False

    def _remember_pending(self, offset_ms: int, line_index: int, at: float) -> None:
        self._pending_offset_ms = offset_ms
        self._pending_index = line_index
        self._pending_at = at

    def _agrees_with_pending(self, offset_ms: int, line_index: int, at: float) -> bool:
        pending = self._pending_offset_ms
        return (
            pending is not None
            and line_index != self._pending_index
            and 0 < at - self._pending_at <= CONFIRMATION_MAX_AGE_S
            and abs(offset_ms - pending) <= AGREEING_OFFSET_MS
        )

    def _anchor(self, line_start_ms: int, at: float, drift: int | None) -> None:
        self._anchor_ms = line_start_ms
        self._anchor_at = at
        self._paused_s = 0.0
        # The cue this line was matched from went up at the same moment the
        # clock is being anchored to, so the hold that catches a paused video
        # measures from there too.
        self._cue_since = at
        self._cue_started_ms = line_start_ms
        self._cue_credited_s = 0.0
        self._drift_ms = drift
        self._misses = 0
        self._pending_offset_ms = None

    def _forget_anchor_if_hopeless(self) -> None:
        if self._misses >= ANCHOR_ABANDON_MISSES:
            logger.debug("Timeline dropped its anchor after %d rejected matches", self._misses)
            self.reset()

    def _expire_stale_anchor(self, now: float) -> None:
        if self._anchor_ms is not None and now - self._anchor_at > ANCHOR_MAX_AGE_S:
            logger.debug(
                "Timeline dropped an anchor nothing agreed with for %.0fs", ANCHOR_MAX_AGE_S
            )
            self.reset()

    def reset(self) -> None:
        self._anchor_ms = None
        self._anchor_at = 0.0
        self._paused_s = 0.0
        self._cue_since = None
        self._cue_started_ms = None
        self._cue_credited_s = 0.0
        self._misses = 0
        self._drift_ms = None
        self._pending_offset_ms = None
