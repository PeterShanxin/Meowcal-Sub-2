"""Shared playback observations and reported timing status."""

from dataclasses import dataclass
from enum import Enum


class PlaybackState(Enum):
    ADVANCING = "advancing"
    STOPPED = "stopped"
    UNCERTAIN = "uncertain"
    INVALIDATED = "invalidated"


@dataclass
class TimelineStatus:
    """What the clock believes, for the debug events and the event log."""

    predicted_ms: int | None
    drift_ms: int | None
    anchored: bool
    misses: int
