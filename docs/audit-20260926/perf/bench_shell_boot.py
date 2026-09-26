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


def _boot(interval_s: float, timeout_s: float = 60) -> dict:
    if interval_s <= 0 or timeout_s <= 0:
        raise ValueError("interval and timeout must be positive")
    with tempfile.TemporaryDirectory(prefix="meowcal-boot-") as appdata:
        runtime = Path(appdata) / "meowcal-sub-2" / "runtime.json"
        env = {**os.environ, "APPDATA": appdata, "PYTHONUTF8": "1"}
        first_possible: list[float] = []
        stop = threading.Event()
        deadline = time.perf_counter() + timeout_s

        def probe() -> None:
            while not stop.is_set() and time.perf_counter() < deadline:
                if _ready(runtime):
                    first_possible.append(time.perf_counter())
                    return
                stop.wait(0.005)

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
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f"backend exited before readiness: {process.returncode}")
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    raise TimeoutError("backend did not become ready before the deadline")
                if _ready(runtime):
                    break
                stop.wait(min(interval_s, remaining))
            detected = time.perf_counter()
            prober.join(timeout=3)
            if not first_possible:
                raise RuntimeError("readiness probe did not confirm backend readiness")
        finally:
            stop.set()
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            finally:
                prober.join(timeout=3)
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
