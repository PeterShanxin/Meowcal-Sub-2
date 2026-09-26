"""Target subtitle presentation on a source subtitle clock."""

from __future__ import annotations

import re
import statistics
from bisect import bisect_left
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import accumulate
from typing import Literal

from meocosub2.models import SubtitleLine
from meocosub2.textnorm import format_subtitle_cue


@dataclass(frozen=True)
class PresentationCue:
    index: int
    start_ms: int
    end_ms: int
    kind: Literal["target", "human", "model"]


@dataclass(frozen=True)
class PresentationFrame:
    text: str
    cues: tuple[PresentationCue, ...]


@dataclass(frozen=True)
class _Anchor:
    source_position: int
    target_position: int
    offset_twice_ms: int


_ANCHOR_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
# The measured shared human cues had a 190 ms P90 residual. Keep automatic
# calibration inside that agreement band rather than trusting isolated phrases.
_MAX_ANCHOR_P90_RESIDUAL_MS = 200


class PresentationTrack:
    """Answers source-clock positions from a separate target subtitle track."""

    def __init__(self, source_lines: list[SubtitleLine], target_lines: list[SubtitleLine]) -> None:
        self.source_lines = source_lines
        self.target_lines = target_lines
        anchors = _ordered_unique_anchors(source_lines, target_lines)
        self.anchor_count = len(anchors)
        self.offset_ms = _corroborated_offset_ms(anchors)

        self._target_entries = tuple(
            (line, position, line.start_ms - self.offset_ms, line.end_ms - self.offset_ms)
            for position, line in enumerate(target_lines)
        )
        self._overlapping_targets = _overlapping_entries(source_lines, self._target_entries)
        self._wholly_uncovered_ids = {
            id(source) for source in source_lines if not self._overlapping_targets[id(source)]
        }
        self._boundaries = tuple(
            sorted(
                {
                    *(
                        boundary
                        for _, _, start, end in self._target_entries
                        for boundary in (start, end)
                    ),
                    *(
                        boundary
                        for source in source_lines
                        if id(source) in self._wholly_uncovered_ids
                        for boundary in (source.start_ms, source.end_ms)
                    ),
                }
            )
        )

    def answer(self, line: SubtitleLine) -> str:
        """Return target text overlapping this source cue, else its own translation."""
        targets = self._overlapping_targets.get(id(line), ())
        return (
            _join_target_text(entry[0] for entry in _ordered_targets(targets))
            if targets
            else line.translated
        )

    def resolve_at(self, source_ms: int) -> PresentationFrame:
        targets = [entry for entry in self._target_entries if entry[2] <= source_ms < entry[3]]
        if targets:
            ordered = _ordered_targets(targets)
            lines = [entry[0] for entry in ordered]
            return PresentationFrame(
                text=_join_target_text(lines),
                cues=tuple(_cue(line, "target") for line in lines),
            )

        fallbacks = [
            (line, position)
            for position, line in enumerate(self.source_lines)
            if id(line) in self._wholly_uncovered_ids
            and line.start_ms <= source_ms < line.end_ms
            and line.translated
        ]
        ordered_fallbacks = sorted(fallbacks, key=lambda entry: (entry[0].start_ms, entry[1]))
        lines = [entry[0] for entry in ordered_fallbacks]
        return PresentationFrame(
            text="\n".join(format_subtitle_cue(line.translated) for line in lines),
            cues=tuple(_cue(line, _fallback_kind(line)) for line in lines),
        )

    def next_change_ms(self, source_ms: int) -> int | None:
        return next((boundary for boundary in self._boundaries if boundary > source_ms), None)


def _ordered_unique_anchors(
    source_lines: list[SubtitleLine], target_lines: list[SubtitleLine]
) -> list[_Anchor]:
    source_by_text: dict[str, list[tuple[int, SubtitleLine]]] = {}
    target_by_text: dict[str, list[tuple[int, SubtitleLine]]] = {}
    for position, line in enumerate(source_lines):
        normalized = _anchor_text(line.translated)
        if normalized and line.translation_source != "model":
            source_by_text.setdefault(normalized, []).append((position, line))
    for position, line in enumerate(target_lines):
        normalized = _anchor_text(line.text)
        if normalized:
            target_by_text.setdefault(normalized, []).append((position, line))

    anchors = [
        _Anchor(
            source_position=source_position,
            target_position=target_position,
            offset_twice_ms=(target.start_ms + target.end_ms) - (source.start_ms + source.end_ms),
        )
        for text, source_matches in source_by_text.items()
        if len(source_matches) == 1 and len(target_by_text.get(text, ())) == 1
        for (source_position, source), (target_position, target) in [
            (source_matches[0], target_by_text[text][0])
        ]
    ]
    return _longest_ordered_chain(sorted(anchors, key=lambda anchor: anchor.source_position))


def _corroborated_offset_ms(anchors: list[_Anchor]) -> int:
    if len(anchors) < 2:
        return 0
    offset_twice_ms = statistics.median(anchor.offset_twice_ms for anchor in anchors)
    residuals = sorted(abs(anchor.offset_twice_ms - offset_twice_ms) for anchor in anchors)
    p90_residual_twice_ms = residuals[(len(residuals) * 9 - 1) // 10]
    if p90_residual_twice_ms > _MAX_ANCHOR_P90_RESIDUAL_MS * 2:
        return 0
    return int(round(offset_twice_ms / 2))


def _longest_ordered_chain(anchors: list[_Anchor]) -> list[_Anchor]:
    """The first longest chain whose target positions rise with source order.

    Each anchor extends the longest earlier chain it can follow, preferring the
    one ending at the smallest target position. `tails[n]` holds the anchor that
    ends a chain of length n + 1 at the smallest target position seen so far,
    which is exactly that preferred predecessor, so a binary search finds it.
    """
    tails: list[int] = []
    tail_positions: list[int] = []
    previous: list[int | None] = []
    end: int | None = None
    for index, anchor in enumerate(anchors):
        length = bisect_left(tail_positions, anchor.target_position)
        previous.append(tails[length - 1] if length else None)
        if length == len(tails):
            tails.append(index)
            tail_positions.append(anchor.target_position)
            end = index
        else:
            tails[length] = index
            tail_positions[length] = anchor.target_position
    chain: list[_Anchor] = []
    while end is not None:
        chain.append(anchors[end])
        end = previous[end]
    chain.reverse()
    return chain


def _anchor_text(text: str) -> str:
    return " ".join(_ANCHOR_WORDS.findall(text.casefold()))


def _overlapping_entries(
    source_lines: list[SubtitleLine], entries: tuple[tuple[SubtitleLine, int, int, int], ...]
) -> dict[int, tuple[tuple[SubtitleLine, int, int, int], ...]]:
    """Each source cue's overlapping target entries, in target order.

    Entries are searched by start, and scanned back only while some entry at or
    before the scan position still ends after the source cue starts: a long
    target cue can outlast the ones that begin after it.
    """
    by_start = sorted(entries, key=lambda entry: entry[2])
    starts = [entry[2] for entry in by_start]
    latest_end_by = list(accumulate((entry[3] for entry in by_start), max))
    overlapping = {}
    for source in source_lines:
        found = []
        for position in range(bisect_left(starts, source.end_ms) - 1, -1, -1):
            if latest_end_by[position] <= source.start_ms:
                break
            if by_start[position][3] > source.start_ms:
                found.append(by_start[position])
        found.sort(key=lambda entry: entry[1])
        overlapping[id(source)] = tuple(found)
    return overlapping


def _join_target_text(lines: Iterable[SubtitleLine]) -> str:
    return "\n".join(format_subtitle_cue(line.text) for line in lines)


def _ordered_targets(
    entries: Iterable[tuple[SubtitleLine, int, int, int]],
) -> list[tuple[SubtitleLine, int, int, int]]:
    return sorted(entries, key=lambda entry: (entry[0].start_ms, entry[1]))


def _fallback_kind(line: SubtitleLine) -> Literal["human", "model"]:
    return "model" if line.translation_source == "model" else "human"


def _cue(line: SubtitleLine, kind: Literal["target", "human", "model"]) -> PresentationCue:
    return PresentationCue(index=line.index, start_ms=line.start_ms, end_ms=line.end_ms, kind=kind)
