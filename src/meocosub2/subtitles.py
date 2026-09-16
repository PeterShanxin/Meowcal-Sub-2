"""Subtitle loading helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pysubs2

from meocosub2.models import SubtitleCheck, SubtitleLine, SubtitlePair
from meocosub2.presentation import PresentationTrack


@dataclass(frozen=True)
class AlignmentReport:
    """Source cues lacking target coverage and their own human translation."""

    total_cues: int
    unpaired_cues: int
    unpaired_ms: int


def load_subtitle_file(
    path: Path, *, checks: list[SubtitleCheck] | None = None
) -> list[SubtitleLine]:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            subtitles = pysubs2.load(str(path), encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Could not decode subtitle file: {path}")

    report = SubtitleCheck(file_name=path.name)
    lines: list[SubtitleLine] = []
    seen: set[tuple[int, int, str]] = set()
    for position, event in enumerate(subtitles, start=1):
        if getattr(event, "is_comment", False):
            continue
        text = event.plaintext.strip()
        if not text:
            report.empty_removed += 1
            continue
        if not 0 <= event.start < event.end <= 9007199254740991:
            raise ValueError(
                f"{path.name}: cue {position} has invalid timing. Choose a corrected subtitle file."
            )
        if "\0" in text:
            raise ValueError(
                f"{path.name}: cue {position} contains a NUL character. Choose a corrected subtitle file."
            )
        # Playback renders plain text. Only identical text on the exact same
        # interval is redundant; overlaps and later repetitions are dialogue.
        key = (event.start, event.end, text)
        if key in seen:
            report.duplicates_removed += 1
            continue
        seen.add(key)
        lines.append(
            SubtitleLine(
                index=len(lines),
                start_ms=event.start,
                end_ms=event.end,
                text=text,
            )
        )
    ordered = sorted(lines, key=lambda line: line.start_ms)
    if not ordered:
        raise ValueError(f"{path.name}: no playable subtitle cues. Choose another subtitle file.")
    report.reordered = lines != ordered
    for index, line in enumerate(ordered):
        line.index = index
    if checks is not None:
        checks.append(report)
    return ordered


def alignment_report(
    source: list[SubtitleLine],
    target: list[SubtitleLine],
    carried: list[str] | None = None,
) -> AlignmentReport:
    """What this target file would leave for the model, without pairing anything.

    Runs against a copy, so asking about a candidate the viewer did not choose
    cannot disturb the lines the session is actually going to play.

    `carried` is what the source file answers on its own, which every candidate
    falls back to alike. Counted as answered, because it is: leaving it out
    reported cues as needing the model when the session would never ask.
    """
    trial = [
        replace(line, translated=carried[index] if carried else "")
        for index, line in enumerate(source)
    ]
    presentation = PresentationTrack(trial, target)
    unpaired = [line for line in trial if line.text and not presentation.answer(line)]
    return AlignmentReport(
        total_cues=len(trial),
        unpaired_cues=len(unpaired),
        unpaired_ms=sum(line.end_ms - line.start_ms for line in unpaired),
    )


def align_subtitles(source: list[SubtitleLine], target: list[SubtitleLine]) -> SubtitlePair:
    return SubtitlePair(source_lines=source, target_lines=target)
