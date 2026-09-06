"""Subtitle loading helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pysubs2

from meocosub2.models import SubtitleLine, SubtitlePair


@dataclass(frozen=True)
class AlignmentReport:
    """How much of the source file a target file actually answers.

    Two subtitle files for one episode rarely carry the same lines, and the
    difference is not small: measured across four English candidates for one
    episode, the worst left 20 of 450 cues unanswered against the best one's
    single cue. Every unanswered cue is time the plate spends holding the
    previous line, or a line the local model has to write instead of a
    translator, so the difference is worth putting in front of the viewer.
    """

    total_cues: int
    unpaired_cues: int
    unpaired_ms: int


def load_subtitle_file(path: Path) -> list[SubtitleLine]:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            subtitles = pysubs2.load(str(path), encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Could not decode subtitle file: {path}")

    lines: list[SubtitleLine] = []
    for event in subtitles:
        if getattr(event, "is_comment", False):
            continue
        text = event.plaintext.strip()
        if not text:
            continue
        lines.append(
            SubtitleLine(
                index=len(lines),
                start_ms=event.start,
                end_ms=event.end,
                text=text,
            )
        )
    return lines


def alignment_report(source: list[SubtitleLine], target: list[SubtitleLine]) -> AlignmentReport:
    """What this target file would leave unanswered, without pairing anything.

    Runs against a copy, so asking about a candidate the viewer did not choose
    cannot disturb the lines the session is actually going to play.
    """
    trial = [replace(line, translated="") for line in source]
    assign_target_translations(trial, target)
    unpaired = [line for line in trial if line.text and not line.translated]
    return AlignmentReport(
        total_cues=len(trial),
        unpaired_cues=len(unpaired),
        unpaired_ms=sum(line.end_ms - line.start_ms for line in unpaired),
    )


def align_subtitles(source: list[SubtitleLine], target: list[SubtitleLine]) -> SubtitlePair:
    return SubtitlePair(source_lines=source, target_lines=target)


def assign_target_translations(
    source: list[SubtitleLine], target: list[SubtitleLine], max_midpoint_delta_ms: int = 1200
) -> None:
    if not source or not target:
        return

    target_index = 0
    for source_line in source:
        best_index: int | None = None
        best_overlap = -1
        best_delta = max_midpoint_delta_ms + 1
        source_midpoint = (source_line.start_ms + source_line.end_ms) // 2

        while (
            target_index < len(target)
            and target[target_index].end_ms < source_line.start_ms - max_midpoint_delta_ms
        ):
            target_index += 1

        for index in range(max(0, target_index - 1), min(len(target), target_index + 4)):
            target_line = target[index]
            overlap = max(
                0,
                min(source_line.end_ms, target_line.end_ms)
                - max(source_line.start_ms, target_line.start_ms),
            )
            target_midpoint = (target_line.start_ms + target_line.end_ms) // 2
            delta = abs(target_midpoint - source_midpoint)
            if overlap > best_overlap or (overlap == best_overlap and delta < best_delta):
                best_overlap = overlap
                best_delta = delta
                best_index = index

        if best_index is None:
            continue

        candidate = target[best_index]
        if best_overlap > 0 or best_delta <= max_midpoint_delta_ms:
            source_line.translated = candidate.text
