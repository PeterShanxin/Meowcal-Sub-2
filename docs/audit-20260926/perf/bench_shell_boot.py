"""How long the shell's boot wait adds after the backend is actually ready.

Replays `wait_for_backend` from src-tauri/src/main.rs against a real
`python -m meocosub2.cli serve`: read the token from runtime.json, GET
/api/state with it (2 s timeout), and sleep the poll interval between failed
attempts. The Rust shell itself needs Windows; this measures the same request
pattern. `ready` is when a fresh 200 would first have been possible, found by
a second, 5 ms probe that does not share the replayed loop's schedule.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATE = "http://127.0.0.1:8765/api/state"


def _ready(runtime: Path) -> bool:
    try:
        token = json.loads(runtime.read_text(encoding="utf-8")).get("token", "")
    except (OSError, ValueError):
        token = ""
    request = urllib.request.Request(STATE, headers={"X-Meowcal-Token": token})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


def _boot(interval_s: float) -> dict:
    with tempfile.TemporaryDirectory(prefix="meowcal-boot-") as appdata:
        runtime = Path(appdata) / "meowcal-sub-2" / "runtime.json"
        env = {**os.environ, "APPDATA": appdata, "PYTHONUTF8": "1"}
        first_possible: list[float] = []

        def probe() -> None:
            while not _ready(runtime):
                time.sleep(0.005)
            first_possible.append(time.perf_counter())

        spawned = time.perf_counter()
        process = subprocess.Popen(
            [sys.executable, "-m", "meocosub2.cli", "serve"],
            cwd=REPO,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        prober = threading.Thread(target=probe, daemon=True)
        prober.start()
        try:
            while not _ready(runtime):
                time.sleep(interval_s)
            detected = time.perf_counter()
            prober.join(timeout=5)
        finally:
            process.terminate()
            process.wait(timeout=10)
        return {
            "backend_ready_ms": round((first_possible[0] - spawned) * 1000, 1),
            "detected_ms": round((detected - spawned) * 1000, 1),
            "added_ms": round((detected - first_possible[0]) * 1000, 1),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval-ms", type=int, nargs="+", default=[400, 50])
    parser.add_argument("--repeat", type=int, default=15)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    summary = {}
    for interval in args.interval_ms:
        runs = [_boot(interval / 1000) for _ in range(args.repeat)]
        added = [run["added_ms"] for run in runs]
        summary[str(interval)] = {
            "median_backend_ready_ms": round(
                statistics.median(r["backend_ready_ms"] for r in runs), 1
            ),
            "median_detected_ms": round(statistics.median(r["detected_ms"] for r in runs), 1),
            "median_added_ms": round(statistics.median(added), 1),
            "mean_added_ms": round(statistics.fmean(added), 1),
            "max_added_ms": max(added),
            "runs": runs,
        }
        print(
            interval,
            {k: v for k, v in summary[str(interval)].items() if k != "runs"},
            file=sys.stderr,
        )
    if args.out:
        args.out.write_text(json.dumps(summary, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
