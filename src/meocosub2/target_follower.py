"""Locate a target-only subtitle track using translations of confirmed screen cues."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from meocosub2.config import AppConfig
from meocosub2.matcher import SubtitleMatcher
from meocosub2.models import SubtitleLine
from meocosub2.presentation import PresentationTrack
from meocosub2.resolution import display_position_ms
from meocosub2.textnorm import format_subtitle_cue
from meocosub2.timeline import SEEK_SCORE, PlaybackTimeline

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScreenRead:
    text: str
    onset: float
    generation: int
    continuity: int


class TargetTrackFollower:
    def __init__(self, lines: list[SubtitleLine], config: AppConfig, bias_ms: Callable[[], int]):
        self.generation = 0
        self._continuity = 0
        self._waiting: ScreenRead | None = None
        self.worker: asyncio.Task[None] | None = None
        self._misses = 0
        self.timeline = PlaybackTimeline(require_confirmation=True)
        self.track = PresentationTrack([], lines)
        self.matcher = SubtitleMatcher(
            lines,
            config.fuzzy_threshold,
            config.match_window_size,
            config.match_window_backward,
            target_language=config.target_language,
        )
        self._occurrences = Counter(
            self.matcher.normalize_for_match(format_subtitle_cue(line.text)) for line in lines
        )
        self._bias_ms = bias_ms
        self._visible_end: int | None = None
        self._end_by_index = {line.index: line.end_ms for line in lines}
        self.live_text = ""
        self.onset = 0.0

    def reset(self) -> None:
        self.clear_cue()
        self.timeline.reset()
        self.matcher.reset()
        self._misses = 0

    def new_cue(self, at: float) -> None:
        self._visible_end = None
        self.generation += 1
        self.onset = at
        self.timeline.saw_new_cue(at)

    def same_cue(self, at: float) -> None:
        self.timeline.saw_same_cue(at)
        if self._visible_end is not None:
            self.timeline.confirm_visible_cue(self._visible_end, at)

    def clear_cue(self) -> None:
        self._visible_end = None
        self.generation += 1
        self.live_text = ""
        self._waiting = None
        self._continuity += 1
        self.timeline.clear_cue()

    def submit(
        self, text: str, translate: Callable[[str], Awaitable[str]], wake: asyncio.Event
    ) -> None:
        self._waiting = ScreenRead(text, self.onset, self.generation, self._continuity)
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self._read_until_idle(translate, wake))

    async def _read_until_idle(
        self, translate: Callable[[str], Awaitable[str]], wake: asyncio.Event
    ) -> None:
        # Finish one answer even if several subtitles pass during inference.
        # The next request takes the latest confirmed caption, keeping lag bounded.
        while self._waiting is not None:
            read, self._waiting = self._waiting, None
            try:
                translated = await translate(read.text)
            except Exception:
                logger.exception("Target-track translation failed (input_chars=%d)", len(read.text))
                translated = ""
            if read.continuity != self._continuity:
                continue
            current = read.generation == self.generation
            if current:
                translated = self.answer(translated, read.onset, current=True)
            self.live_text = "" if self.timeline.anchored else translated
            wake.set()

    def answer(self, answer: str, at: float, current: bool) -> str:
        """A queued answer may supply wording; only a still-visible cue supplies time."""
        if not answer:
            return ""
        self.matcher.clear_cue()
        result = self.matcher.match(
            answer, self.timeline.window_ms(), self.timeline.cue_position_ms
        )
        if result is None:
            if current:
                self._misses += 1
                if self._misses >= 2:
                    self.timeline.invalidate()
            return answer
        wording = result.target_text
        # A common line can be word-perfect in the wrong scene. Its words remain
        # useful while two distinct, well-placed observations establish time.
        if (
            not current
            or result.span != 1
            or self._occurrences[self.matcher.normalize_for_match(result.source_text)] != 1
        ):
            return wording
        if self.timeline.accepts(result.start_ms, result.line_index, result.score, seen_at=at):
            self._misses = 0
            self.live_text = ""
            if result.score >= SEEK_SCORE:
                self._visible_end = self._end_by_index[result.line_index]

        return wording

    def position_ms(self, lead_ms: int, now: float | None = None) -> int | None:
        return display_position_ms(self.timeline, lead_ms, self._bias_ms(), now)
