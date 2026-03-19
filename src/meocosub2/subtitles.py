"""Subtitle loading helpers."""

from __future__ import annotations

from pathlib import Path

import pysubs2

from meocosub2.models import SubtitleLine, SubtitlePair


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


def align_subtitles(source: list[SubtitleLine], target: list[SubtitleLine]) -> SubtitlePair:
    return SubtitlePair(source_lines=source, target_lines=target)


def assign_target_translations(source: list[SubtitleLine], target: list[SubtitleLine], max_midpoint_delta_ms: int = 1200) -> None:
    if not source or not target:
        return

    target_index = 0
    for source_line in source:
        best_index: int | None = None
        best_overlap = -1
        best_delta = max_midpoint_delta_ms + 1
        source_midpoint = (source_line.start_ms + source_line.end_ms) // 2

        while target_index < len(target) and target[target_index].end_ms < source_line.start_ms - max_midpoint_delta_ms:
            target_index += 1

        for index in range(max(0, target_index - 1), min(len(target), target_index + 4)):
            target_line = target[index]
            overlap = min(source_line.end_ms, target_line.end_ms) - max(source_line.start_ms, target_line.start_ms)
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
