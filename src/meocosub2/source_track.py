"""Build a timed target from one untranslated source while live viewing continues."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from meocosub2.gapfill import YIELD_POLL_S, FillOutcome, PendingGaps, Translate, context_pairs
from meocosub2.models import SubtitleLine
from meocosub2.presentation import PresentationTrack

logger = logging.getLogger(__name__)


class SourceTrackTranslation:
    """Answers belong to this prepared source, including across stop and restart."""

    def __init__(self, lines: list[SubtitleLine]) -> None:
        self.lines = lines
        self.presentation: PresentationTrack | None = None
        self._missing = sum(not line.translated for line in lines)
        self._in_flight: dict[int, asyncio.Future[str]] = {}
        if self._missing == 0:
            self._finish()

    def _finish(self) -> None:
        target = [
            SubtitleLine(
                line.index, line.start_ms, line.end_ms, line.translated, translation_source="model"
            )
            for line in self.lines
        ]
        # The generated cues already use source time. They need no offset calibration.
        self.presentation = PresentationTrack([], target)

    async def translate_cue(self, index: int, translate: Translate) -> str:
        line = self.lines[index]
        if line.translated:
            return line.translated
        if index in self._in_flight:
            # A seek can cancel a live waiter. The owner still needs its answer.
            return await asyncio.shield(self._in_flight[index])
        finished = asyncio.get_running_loop().create_future()
        self._in_flight[index] = finished
        try:
            text = await translate(line.text, context_pairs(self.lines, index))
            if text:
                line.translated = text
                line.translation_source = "model"
                self._missing -= 1
                if self._missing == 0:
                    self._finish()
            return text
        finally:
            self._in_flight.pop(index)
            finished.set_result(line.translated)

    async def fill(
        self,
        translate: Translate,
        busy: Callable[[], bool],
        updated: Callable[[], Awaitable[None]],
        position: Callable[[], int | None],
        active: Callable[[], bool],
    ) -> FillOutcome:
        pending = PendingGaps(self.lines)
        filled = 0
        while active() and self.presentation is None:
            if busy():
                await asyncio.sleep(YIELD_POLL_S)
                continue
            index = pending.pop(position())
            if index is None:
                break

            try:
                text = await self.translate_cue(index, translate)
            except Exception as error:
                logger.warning("Source track generation stopped (%s)", type(error).__name__)
                return FillOutcome(filled, False, engine_failed=True)
            if text:
                filled += 1
                await updated()
        # A declined line remains available to live translation. Let a new session retry it.
        return FillOutcome(filled, self.presentation is not None)
