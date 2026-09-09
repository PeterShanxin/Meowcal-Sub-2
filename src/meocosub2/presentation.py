"""Target subtitle presentation on a source subtitle clock."""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
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


class PresentationTrack:
    """Answers source-clock positions from a separate target subtitle track."""

    def __init__(self, source_lines: list[SubtitleLine], target_lines: list[SubtitleLine]) -> None:
        self.source_lines = source_lines
        self.target_lines = target_lines
        anchors = _ordered_unique_anchors(source_lines, target_lines)
        self.anchor_count = len(anchors)
        self.offset_ms = (
            int(round(statistics.median(anchor.offset_twice_ms for anchor in anchors) / 2))
            if anchors
            else 0
        )

        self._target_entries = tuple(
            (line, position, line.start_ms - self.offset_ms, line.end_ms - self.offset_ms)
            for position, line in enumerate(target_lines)
        )
        self._overlapping_targets = {
            id(source): tuple(
                entry
                for entry in self._target_entries
                if _overlaps(source.start_ms, source.end_ms, entry[2], entry[3])
            )
            for source in source_lines
        }
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


def _longest_ordered_chain(anchors: list[_Anchor]) -> list[_Anchor]:
    chains: list[list[_Anchor]] = []
    for anchor in anchors:
        choices = [chain for chain in chains if chain[-1].target_position < anchor.target_position]
        longest = max(
            choices, key=lambda chain: (len(chain), -chain[-1].target_position), default=[]
        )
        chains.append([*longest, anchor])
    return max(chains, key=lambda chain: len(chain), default=[])


def _anchor_text(text: str) -> str:
    return " ".join(_ANCHOR_WORDS.findall(text.casefold()))


def _overlaps(left_start: int, left_end: int, right_start: int, right_end: int) -> bool:
    return left_start < right_end and right_start < left_end


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
