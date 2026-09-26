"""Per-frame cost of the live sync loop after OCR, on a simulated clock.

Drives `CandidateSession` the way `run_session_loop` does: a read every
capture interval (250 ms), `saw_new_cue`/`saw_same_cue` from the subtitle gate,
`match` on each new or unconfirmed read, and a renderer wake
(`seconds_to_next_line` + `line_now`) every 200 ms. Wall time is simulated so
the timeline advances deterministically; only the CPU work is timed.

OCR itself (Windows OCR through Meowcal Core) cannot run in this container, so
the benchmark starts from recognised text. 15% of reads are the source line
itself; the rest are a different translation of the scene, which is what the
agent guide measured on a real episode (12% matched).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

from fixtures import OTHER_WORDS, write_episode

import meocosub2.subtitle_gate as gate_module
import meocosub2.timeline as timeline_module
from meocosub2.bilingual import split_bilingual
from meocosub2.config import AppConfig
from meocosub2.models import SourceSubtitleCandidate
from meocosub2.subtitle_gate import LineChange, SubtitleGate
from meocosub2.subtitles import align_subtitles, load_subtitle_file
from meocosub2.sync import CandidateSession

CAPTURE_S = 0.25
RENDER_S = 0.2
MATCHING_READ_SHARE = 0.15


class Clock:
    now = 1000.0

    def __call__(self) -> float:
        return self.now


async def _no_translator():
    raise RuntimeError("not used")


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "n": len(values),
        "mean_us": round(statistics.fmean(values) * 1e6, 1),
        "p50_us": round(_pct(values, 0.5) * 1e6, 1),
        "p95_us": round(_pct(values, 0.95) * 1e6, 1),
        "p99_us": round(_pct(values, 0.99) * 1e6, 1),
        "max_us": round(max(values) * 1e6, 1),
        "total_ms": round(sum(values) * 1e3, 1),
    }


async def run(cues: int, minutes: float, bilingual: bool, directory: Path, seed: int) -> dict:
    files = write_episode(directory, cues)
    source = load_subtitle_file(files["bilingual" if bilingual else "source"])
    target = load_subtitle_file(files["target"])
    if bilingual:
        split_bilingual(source, "en", "zh")
    candidate = SourceSubtitleCandidate(
        "a", "a.srt", "p", "en", "a.srt", align_subtitles(source, target)
    )
    clock = Clock()
    timeline_module.monotonic = clock
    gate_module.monotonic = clock
    session = CandidateSession([candidate], AppConfig(sync_bias_ms=0), _no_translator)
    gate = SubtitleGate()
    rng = random.Random(seed)
    # The video starts 30 s into the file; the clock the session reads is wall time.
    video_zero = clock.now - 30.0
    by_cue: dict[int, str] = {}
    match_times: list[float] = []
    render_times: list[float] = []
    next_render = clock.now
    confirmed = False
    end = clock.now + minutes * 60
    while clock.now < end:
        video_ms = int((clock.now - video_zero) * 1000)
        on_screen = next((line for line in source if line.start_ms <= video_ms < line.end_ms), None)
        if on_screen is None:
            text = ""
        else:
            if on_screen.index not in by_cue:
                by_cue[on_screen.index] = (
                    on_screen.text
                    if rng.random() < MATCHING_READ_SHARE
                    else " ".join(rng.choice(OTHER_WORDS) for _ in range(rng.randint(3, 10)))
                )
            text = by_cue[on_screen.index]
        if text:
            change = gate.classify(text)
            if change is LineChange.REPEAT:
                session.saw_same_cue(clock.now)
                if not confirmed:
                    started = time.perf_counter()
                    resolution = await session.match(text, follow=False)
                    match_times.append(time.perf_counter() - started)
                    confirmed = bool(resolution and resolution.detail.get("confirmed"))
            elif change is not LineChange.UNSTABLE:
                gate.remember(text)
                confirmed = False
                session.saw_new_cue(clock.now)
                started = time.perf_counter()
                resolution = await session.match(text, follow=True)
                match_times.append(time.perf_counter() - started)
                confirmed = bool(resolution and resolution.detail.get("confirmed"))
        step_end = clock.now + CAPTURE_S
        while next_render < step_end:
            clock.now = max(clock.now, next_render)
            started = time.perf_counter()
            session.seconds_to_next_line()
            session.line_now()
            render_times.append(time.perf_counter() - started)
            next_render += RENDER_S
        clock.now = step_end
    return {
        "cues": cues,
        "target_cues": len(target),
        "bilingual": bilingual,
        "simulated_minutes": minutes,
        "anchored_at_end": session.anchored,
        "match": _summary(match_times),
        "render_tick": _summary(render_times),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cues", type=int, nargs="+", default=[800, 1600])
    parser.add_argument("--minutes", type=float, default=10)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--fixtures", type=Path, default=Path(tempfile.gettempdir()) / "meowcal-perf-fixtures"
    )
    args = parser.parse_args()
    results = []
    for cues in args.cues:
        for bilingual in (False, True):
            for attempt in range(args.repeat):
                result = asyncio.run(
                    run(cues, args.minutes, bilingual, args.fixtures, seed=attempt)
                )
                result["attempt"] = attempt
                results.append(result)
                print(json.dumps(result), file=sys.stderr)
    if args.out:
        args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
