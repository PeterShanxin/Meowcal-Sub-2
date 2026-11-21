"""Translate a playback position into the subtitle strip's current contents."""

from dataclasses import asdict, dataclass, field

from meocosub2.presentation import PresentationTrack
from meocosub2.timeline import PlaybackTimeline

MATCHED = "matched"
TRANSLATED = "translated"


@dataclass
class Resolution:
    """What a read came to.

    Either a line ready for the plate, or the text to translate for it - the
    clean subtitle line when one matched, the raw read when none did.
    """

    text: str = ""
    translate: str = ""
    matched: bool = False
    # The last file line this answer covers. A read can match a cue the file
    # splits across two lines; the clock only ever answers with one.
    covers_through: int | None = None
    covers_until_ms: int | None = None
    detail: dict[str, object] = field(default_factory=dict)

    @property
    def source(self) -> str:
        return MATCHED if self.matched else TRANSLATED


def target_frame(track: PresentationTrack, position: int, detail: dict[str, object]) -> Resolution:
    frame = track.resolve_at(position)
    return Resolution(
        text=frame.text,
        matched=True,
        detail={
            "presentationCues": [asdict(cue) for cue in frame.cues],
            "presentationClockMs": position + track.offset_ms,
            "mappingOffsetMs": track.offset_ms,
            "confirmed": False,
            **detail,
        },
    )


def display_position_ms(
    timeline: PlaybackTimeline,
    lead_ms: int,
    bias_ms: int,
    now: float | None = None,
) -> int | None:
    """Bound the measured display lag by the matched cue, then apply the viewer's adjustment."""
    position = timeline.position_ms(now)
    if position is None:
        return None
    lagged = position + lead_ms
    anchor = timeline.anchor_ms
    return (max(lagged, anchor) if anchor is not None else lagged) + bias_ms
