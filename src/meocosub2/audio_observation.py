"""Player-associated stream activity; never record audio or use the system mix."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioObservation:
    process_id: int
    running: bool
    peak: float | None = None


@dataclass(frozen=True)
class AudioSession:
    process_id: int
    state: int
    peak: float | None
    single_process: bool = True


def player_audio(process_id: int, sessions: list[AudioSession]) -> AudioObservation | None:
    """Silence/mute is not Stop: Windows stream state is separate from level.

    Unknown attribution, expired sessions and absence provide no evidence. In
    particular, audio in another process cannot keep this player's clock alive.
    """
    if process_id <= 0:
        return None
    selected = [session for session in sessions if session.process_id == process_id]
    if not selected or any(not session.single_process for session in selected):
        return None
    usable = [session for session in selected if session.state in (0, 1)]
    if not usable:
        return None
    peaks = [session.peak for session in usable if session.peak is not None]
    return AudioObservation(
        process_id, any(session.state == 1 for session in usable), max(peaks) if peaks else None
    )
