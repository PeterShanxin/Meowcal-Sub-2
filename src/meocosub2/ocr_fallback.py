"""Play confirmed OCR cues in order when there is no source subtitle clock."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from time import perf_counter

from meocosub2.playback_capture import PlaybackCaptureError
from meocosub2.subtitle_gate import LineChange
from meocosub2.textnorm import collapse_whitespace, is_cjk_char
from meocosub2.translator import is_untranslatable

logger = logging.getLogger(__name__)

CONFIRM_WITHIN_S = 2.0
CLEAR_AFTER_EMPTY_READS = 3
MAX_QUEUE_AGE_S = 15.0
MAX_QUEUE_DEPTH = 32
MAX_SUCCESSOR_WAIT_S = 4.0
DISPLAY_TICK_S = 0.025
_IDENTITY_EQUIVALENTS = str.maketrans({"’": "'", "‘": "'", "凈": "净", "淨": "净"})


@dataclass(eq=False)
class _Cue:
    key: str
    text: str
    started: float
    sample_s: float
    queued_at: float
    ended: float | None = None
    answer: str | None = None

    def reading_time(self, shown_at: float) -> float:
        assert self.answer and self.ended is not None
        cjk = sum(is_cjk_char(char) for char in self.answer)
        other = len(self.answer) - cjk
        source_s = max(0.0, self.ended - self.started - self.sample_s)
        budget = max(0.35, min(4.0, source_s))
        estimate = max(0.6, min(3.5, 0.4 + 0.035 * other + 0.07 * cjk))
        minimum = max(0.35, min(1.2, 0.25 + 0.025 * other + 0.05 * cjk))
        delay = shown_at - self.started
        return min(budget, max(minimum, max(source_s, estimate) - delay))


class _CueQueue:
    def __init__(self, interval_s: float) -> None:
        self._interval_s = interval_s
        self._wake = asyncio.Event()
        self._waiting: deque[_Cue] = deque()
        self._active: _Cue | None = None
        self._candidate: tuple[str, float, float] | None = None
        self._last_read_at: float | None = None
        self._empty_since: float | None = None
        self._empty_reads = 0
        self._visible: _Cue | None = None
        self._shown_at = 0.0
        self._reset_matcher = False
        self.displayed = ""

    def reset(self) -> None:
        self._waiting.clear()
        self._active = self._candidate = self._visible = None
        self._last_read_at = self._empty_since = None
        self._empty_reads = 0
        self._reset_matcher = True
        self._wake.set()

    def interrupt_read(self) -> None:
        self._candidate = None
        self._empty_since = None
        self._empty_reads = 0

    def observe(self, text: str, at: float) -> LineChange | None:
        previous, self._last_read_at = self._last_read_at, at
        sample_s = self._interval_s if previous is None else at - previous
        if is_untranslatable(text):
            self._candidate = None
            if self._empty_since is None:
                self._empty_since = at
            self._empty_reads += 1
            if self._empty_reads == CLEAR_AFTER_EMPTY_READS:
                self._end_active(self._empty_since)
            return None

        key = collapse_whitespace(text).rstrip(".,!?;:。，！？… ").translate(_IDENTITY_EQUIVALENTS)
        key = key.lower()
        self._empty_since = None
        self._empty_reads = 0
        if self._active is not None and self._active.key == key:
            self._candidate = None
            return LineChange.REPEAT
        candidate = self._candidate
        if (
            candidate is None
            or candidate[0] != key
            or not 0 < at - candidate[1] <= CONFIRM_WITHIN_S
        ):
            self._candidate = (key, at, sample_s)
            return LineChange.UNSTABLE

        _, started, interval = candidate
        self._candidate = None
        self._end_active(started)
        queued_at = perf_counter()
        self._active = _Cue(key, text, started, interval, queued_at)
        self._waiting.append(self._active)
        self._recover_if_stalled(queued_at)
        self._wake.set()
        return LineChange.NEW

    def _end_active(self, at: float) -> None:
        if self._active is not None:
            self._active.ended = at
            self._active = None
            self._wake.set()

    def _recover_if_stalled(self, now: float) -> None:
        if not self._waiting or self._waiting[0] is self._active:
            return
        if (
            len(self._waiting) < MAX_QUEUE_DEPTH
            and now - self._waiting[0].queued_at < MAX_QUEUE_AGE_S
        ):
            return
        remaining = deque(cue for cue in self._waiting if cue is self._active)
        logger.warning(
            "OCR fallback skipped %d backlogged cues", len(self._waiting) - len(remaining)
        )
        self._waiting = remaining
        self._visible = None

    def _next_display(self, now: float) -> str | None:
        head = self._waiting[0] if self._waiting else None
        if self._visible is not None:
            ended = self._visible.ended
            if ended is None or now - self._shown_at < self._visible.reading_time(self._shown_at):
                return None
            if head is not None and head.answer is None and now - ended < MAX_SUCCESSOR_WAIT_S:
                return None

        if head is not None and head.answer is not None:
            self._waiting.popleft()
            self._visible = head if head.answer else None
            return head.answer
        self._visible = None
        return "" if self.displayed else None

    async def run(
        self,
        translate: Callable[[str], Awaitable[str]],
        publish: Callable[[str], Awaitable[None]],
        reset_matcher: Callable[[], None],
        timeout_s: float,
    ) -> None:
        async def translate_cue(cue: _Cue) -> str:
            try:
                async with asyncio.timeout(timeout_s):
                    return await translate(cue.text)
            except Exception as error:
                logger.warning("OCR fallback translation failed (%s)", type(error).__name__)
                return ""

        task: asyncio.Task[str] | None = None
        request: _Cue | None = None
        try:
            while True:
                self._wake.clear()
                now = perf_counter()
                self._recover_if_stalled(now)
                if task is not None and task.done():
                    if request is not None and request in self._waiting:
                        request.answer = "" if task.cancelled() else task.result()
                    task = request = None
                if task is not None and request not in self._waiting and not task.cancelling():
                    # Core owns one slot. Let cancellation settle before starting the next cue.
                    task.cancel()
                if task is None:
                    if self._reset_matcher:
                        # Late work may have touched the matcher while unwinding.
                        reset_matcher()
                        self._reset_matcher = False
                    request = next((cue for cue in self._waiting if cue.answer is None), None)
                    if request is not None:
                        task = asyncio.create_task(translate_cue(request))
                        task.add_done_callback(lambda _: self._wake.set())

                text = self._next_display(now)
                if text is not None:
                    if text != self.displayed:
                        await publish(text)
                        self.displayed = text
                    self._shown_at = perf_counter()
                timed = bool(self._waiting) or (
                    self._visible is not None and self._visible.ended is not None
                )
                with suppress(TimeoutError):
                    async with asyncio.timeout(DISPLAY_TICK_S if timed else 1.0):
                        await self._wake.wait()
        finally:
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def run_ocr_fallback(
    read_region: Callable[[], tuple[int, ...]],
    read_text: Callable[[tuple[int, ...]], Awaitable[str]],
    translate: Callable[[str], Awaitable[str]],
    publish: Callable[[str], Awaitable[None]],
    reset_matcher: Callable[[], None],
    interval_s: float,
    translation_timeout_s: float,
    debug: Callable[[dict[str, object]], Awaitable[None]] | None,
) -> None:
    queue = _CueQueue(interval_s)
    presenter = asyncio.create_task(
        queue.run(translate, publish, reset_matcher, min(translation_timeout_s, MAX_QUEUE_AGE_S))
    )
    previous_region: tuple[int, ...] | None = None
    iteration = 0
    try:
        while True:
            iteration += 1
            started = perf_counter()
            region = read_region()
            if region != previous_region:
                queue.reset()
                previous_region = region
            text = ""
            change = None
            try:
                text = await read_text(region)
            except PlaybackCaptureError as error:
                queue.reset()
                logger.warning(
                    "OCR fallback capture #%d failed (%s)", iteration, type(error).__name__
                )
            except Exception as error:
                queue.interrupt_read()
                logger.warning(
                    "OCR fallback recognition #%d failed (%s)", iteration, type(error).__name__
                )
            else:
                change = queue.observe(text, started)

            if debug is not None:
                await debug(
                    {
                        "iteration": iteration,
                        "ocrText": text[:120],
                        "change": change.value if change else "empty",
                        "displayed": queue.displayed[:60],
                        "source": "translated" if queue.displayed else "matched",
                        "elapsedMs": int((perf_counter() - started) * 1000),
                        "playingConfidence": 0.0,
                    }
                )
            if presenter.done():
                await presenter
            await asyncio.sleep(max(0.0, interval_s - (perf_counter() - started)))
    finally:
        presenter.cancel()
        await asyncio.gather(presenter, return_exceptions=True)
