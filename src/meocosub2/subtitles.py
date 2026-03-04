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
