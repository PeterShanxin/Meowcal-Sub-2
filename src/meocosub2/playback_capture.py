"""One player-content capture with separate OCR/motion crops and audio metadata."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from time import monotonic

from PIL import Image

from meocosub2.audio_observation import AudioObservation, ambient_audio, player_audio
from meocosub2.playback_observation import PlaybackObserver
from meocosub2.player_window import (
    PlayerWindow,
    VisualContext,
    find_player_window,
    find_visual_context,
)
from meocosub2.timeline import PlaybackState
from meocosub2.windows_audio import read_audio_sessions

AUDIO_POLL_S = 0.5
AUDIO_TIMEOUT_S = 0.25


class PlaybackCaptureError(RuntimeError):
    """A failed frame cannot support continued subtitle projection."""


class PlaybackCapture:
    def __init__(self, observer: PlaybackObserver | None = None) -> None:
        self._observer = observer or PlaybackObserver()
        self._audio_lock = threading.Lock()
        self._sampled_at = -float("inf")
        self._owner: PlayerWindow | VisualContext | None = None
        self._audio: AudioObservation | None = None
        self._selected_region: tuple[int, ...] | None = None

    @property
    def confidence(self) -> float:
        return self._observer.confidence

    @property
    def state_since(self) -> float | None:
        return self._observer.state_since

    def observe_text(self, text: str, at: float, captured: PlaybackState) -> PlaybackState:
        if captured is PlaybackState.INVALIDATED:
            return captured
        return self._observer.observe_text(text, at)

    def reset(self) -> None:
        self._observer.reset()
        self._owner = None
        self._audio = None
        self._sampled_at = -float("inf")
        self._selected_region = None

    def _sample_audio(self, process_id: int | None) -> AudioObservation | None:
        # A device RPC that outlives the caller's deadline must not accumulate
        # more reader workers or leak COM pointers across worker apartments.
        if not self._audio_lock.acquire(blocking=False):
            return None
        try:
            sessions = read_audio_sessions()
            if sessions is None:
                return None
            return (
                ambient_audio(sessions)
                if process_id is None
                else player_audio(process_id, sessions)
            )
        finally:
            self._audio_lock.release()

    async def _read_audio(
        self, owner: PlayerWindow | VisualContext | None, now: float
    ) -> AudioObservation | None:
        if owner != self._owner:
            self._audio = None
            self._sampled_at = -float("inf")
        self._owner = owner
        if owner is None:
            return None
        if now - self._sampled_at >= AUDIO_POLL_S:
            self._sampled_at = now
            try:
                self._audio = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._sample_audio,
                        owner.process_id if isinstance(owner, PlayerWindow) else None,
                    ),
                    AUDIO_TIMEOUT_S,
                )
            except TimeoutError:
                self._audio = None
        return self._audio

    async def capture(
        self, grab: Callable, region: tuple[int, ...], at: float
    ) -> tuple[Image.Image, PlaybackState]:
        try:
            return await self._capture(grab, region, at)
        except Exception as error:
            self.reset()
            raise PlaybackCaptureError("Playback capture unavailable") from error

    async def _capture(
        self, grab: Callable, region: tuple[int, ...], at: float
    ) -> tuple[Image.Image, PlaybackState]:
        changed_selection = self._selected_region is not None and region != self._selected_region
        if changed_selection:
            self.reset()
        self._selected_region = region
        owner = await asyncio.to_thread(find_player_window, region)
        if owner is None:
            owner = await asyncio.to_thread(find_visual_context, region)
        observed_region = owner.region if owner is not None else region
        image = await asyncio.to_thread(grab, observed_region)
        audio = await self._read_audio(owner, monotonic())
        state = self._observer.observe(
            image, observed_region, at, audio, owner.process_id if owner else None
        )
        if owner is not None:
            x, y, width, height = region
            left, top, _, _ = observed_region
            image = image.crop((x - left, y - top, x - left + width, y - top + height))
        return image, PlaybackState.INVALIDATED if changed_selection else state
