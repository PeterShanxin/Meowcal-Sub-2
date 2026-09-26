"""Presentation construction with sparse dialogue and one full-track sign cue."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import time
from pathlib import Path

import meocosub2.presentation as presentation
from meocosub2.models import SubtitleLine


def measure(count: int, repeat: int) -> dict:
    source = [SubtitleLine(i, i * 10, i * 10 + 5, "source") for i in range(count)]
    target = [SubtitleLine(0, 0, count * 10, "sign")]
    target += [SubtitleLine(i + 1, i * 10, i * 10 + 5, "dialogue") for i in range(count)]
    samples = []
    for _ in range(repeat):
        started = time.perf_counter()
        track = presentation.PresentationTrack(source, target)
        samples.append(round((time.perf_counter() - started) * 1000, 3))
        assert all(track.answer(cue) == "sign\ndialogue" for cue in source)
    return {
        "source_cues": count,
        "overlap_pairs": 2 * count,
        "median_ms": statistics.median(samples),
        "runs_ms": samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cues", type=int, nargs="+", default=[1000, 2000, 4000, 8000])
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.repeat < 1 or any(count < 1 for count in args.cues):
        parser.error("repeat and cue counts must be positive")
    result = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "presentation_sha256": hashlib.sha256(Path(presentation.__file__).read_bytes()).hexdigest(),
        "runs": [measure(count, args.repeat) for count in args.cues],
    }
    body = json.dumps(result, indent=2)
    print(body)
    if args.out:
        args.out.write_text(body + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
