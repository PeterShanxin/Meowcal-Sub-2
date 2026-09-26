"""Session preparation through the real controller, downloads served from disk.

Runs `GuiController.prepare_session("subtitle_pair", ...)` with a source file,
a chosen target and three rival targets (TARGET_ALIGNMENT_SAMPLE), which is the
path the studio takes when the viewer picks a source and a target. Provider
downloads return local files at once and the translation engine reports ready,
so what remains is the backend's own work. A 5 ms heartbeat task measures how
long the event loop - which also serves the studio's API and websocket - is
held without yielding.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from fixtures import write_episode

from meocosub2.config import AppConfig
from meocosub2.overlay.controller import GuiController
from meocosub2.subtitle_sources.types import (
    AggregatedSearchCatalog,
    AggregatedSubtitleResult,
    AggregatedTitleMatch,
)

RIVALS = 3


async def _emit(*_args, **_kwargs) -> None:
    return None


def _result(result_id: str, language: str, file_name: str) -> AggregatedSubtitleResult:
    return AggregatedSubtitleResult(
        result_id=result_id,
        match_id="match-1",
        provider="subdl",
        provider_label="SubDL",
        title="Synthetic",
        year=2026,
        imdb_id=None,
        media_type="episode",
        language=language,
        download_count=10,
        file_name=file_name,
        season=1,
        episode=1,
        provider_result=object(),
    )


def _controller(tmp: Path, files: dict[str, Path], bilingual: bool) -> GuiController:
    controller = GuiController(AppConfig(), _emit, config_path=tmp / "config.toml")
    results = [_result("source", "en", "source.srt"), _result("target", "zh", "target.srt")]
    results += [_result(f"rival{n}", "zh", f"rival{n}.srt") for n in range(1, RIVALS + 1)]
    controller._search_catalog = AggregatedSearchCatalog(
        matches=[
            AggregatedTitleMatch(
                id="match-1",
                title="Synthetic",
                year=2026,
                imdb_id=None,
                tmdb_id=None,
                media_type="tvshow",
                subtitles_count=len(results),
                match_score=100,
                provider_count=1,
                providers=("subdl",),
                provider_labels=("SubDL",),
            )
        ],
        results=results,
    )
    controller._state.title = "Synthetic"
    controller._state.source_language = "en"
    controller._state.target_language = "zh"
    controller._state.search_matches = [
        {"id": "match-1", "title": "Synthetic", "mediaType": "tvshow"}
    ]
    controller._state.search_results = [
        {
            "id": r.result_id,
            "resultId": r.result_id,
            "matchId": "match-1",
            "provider": "subdl",
            "providerLabel": "SubDL",
            "language": r.language,
            "fileName": r.file_name,
        }
        for r in results
    ]
    paths = {"source": files["bilingual" if bilingual else "source"], "target": files["target"]}
    paths |= {f"rival{n}": files[f"rival{n}"] for n in range(1, RIVALS + 1)}

    async def download(entry: AggregatedSubtitleResult) -> Path:
        return paths[entry.result_id]

    controller._aggregator.download = download  # type: ignore[method-assign]
    controller._aggregator.downloads_remaining = lambda _provider: None  # type: ignore[method-assign]
    return controller


async def _heartbeat(stalls: list[float], stop: asyncio.Event) -> None:
    last = time.perf_counter()
    while not stop.is_set():
        await asyncio.sleep(0.005)
        now = time.perf_counter()
        stalls.append(now - last - 0.005)
        last = now


async def _prepare_once(tmp: Path, files: dict[str, Path], bilingual: bool) -> dict:
    controller = _controller(tmp, files, bilingual)
    stalls: list[float] = []
    stop = asyncio.Event()
    beat = asyncio.create_task(_heartbeat(stalls, stop))
    await asyncio.sleep(0.02)
    started = time.perf_counter()
    payload = await controller.prepare_session(
        mode="subtitle_pair", feature_id="match-1", source_file_id="source", target_file_id="target"
    )
    elapsed = time.perf_counter() - started
    stop.set()
    await beat
    await controller._stop_prefill()
    return {
        "prepare_ms": round(elapsed * 1000, 1),
        "max_loop_stall_ms": round(max(stalls, default=0) * 1000, 1),
        "translated_line_count": payload["translated_line_count"],
        "alignment": [
            (a["result_id"], a["unpaired_cues"], a["unpaired_ms"])
            for a in payload["target_alignment"]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cues", type=int, nargs="+", default=[800, 1600, 3000])
    parser.add_argument("--repeat", type=int, default=7)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--fixtures", type=Path, default=Path(tempfile.gettempdir()) / "meowcal-perf-fixtures"
    )
    args = parser.parse_args()
    rows = []

    async def no_fill(*_args, **_kwargs) -> int:
        return 0

    async def engine_ready() -> str:
        return "http://127.0.0.1:0"

    with (
        patch("meocosub2.overlay.controller.fill_before_the_session", no_fill),
        patch("meocosub2.overlay.controller.engine.ensure_ready", engine_ready),
    ):
        for cues in args.cues:
            files = write_episode(args.fixtures, cues, rivals=RIVALS)
            for bilingual in (False, True):
                runs = [
                    asyncio.run(_prepare_once(args.fixtures, files, bilingual))
                    for _ in range(args.repeat)
                ]
                times = [r["prepare_ms"] for r in runs]
                row = {
                    "cues": cues,
                    "bilingual": bilingual,
                    # The first run pays module warm-up and cold file caches.
                    "first_ms": times[0],
                    "median_ms": round(statistics.median(times), 1),
                    "min_ms": min(times),
                    "max_ms": max(times),
                    "median_max_loop_stall_ms": round(
                        statistics.median(r["max_loop_stall_ms"] for r in runs), 1
                    ),
                    "translated_line_count": runs[0]["translated_line_count"],
                    "alignment": runs[0]["alignment"],
                    "runs_ms": times,
                }
                rows.append(row)
                print(json.dumps(row), file=sys.stderr)
    if args.out:
        args.out.write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
