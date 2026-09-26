"""Failure handling and metric labels in the reproducible performance harness."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

PERF = Path(__file__).resolve().parents[1] / "docs/audit-20260926/perf"


def load_benchmark(name):
    spec = importlib.util.spec_from_file_location(name, PERF / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("exits", [True, False])
def test_shell_benchmark_bounds_failed_start_and_stops_owned_workers(monkeypatch, exits):
    bench = load_benchmark("bench_shell_boot")
    popen = subprocess.Popen
    thread = bench.threading.Thread
    processes, threads = [], []

    def spawn(*args, **kwargs):
        code = "raise SystemExit(7)" if exits else "import time; time.sleep(60)"
        process = popen([sys.executable, "-c", code], **kwargs)
        processes.append(process)
        return process

    def start_thread(*args, **kwargs):
        worker = thread(*args, **kwargs)
        threads.append(worker)
        return worker

    monkeypatch.setattr(bench.subprocess, "Popen", spawn)
    monkeypatch.setattr(bench.threading, "Thread", start_thread)
    monkeypatch.setattr(bench, "_ready", lambda _: False)
    expected = RuntimeError if exits else TimeoutError
    with pytest.raises(expected, match="backend"):
        bench._boot(0.01, timeout_s=2 if exits else 0.05)
    assert all(process.poll() is not None for process in processes)
    assert all(not worker.is_alive() for worker in threads)


def test_routed_second_navigation_is_not_reported_as_cached_warm_start():
    bench = load_benchmark("bench_startup")
    visit = {"palette_ready_ms": 10, "spawn_to_palette_ms": 20}
    summary = bench.summarize([{"backend_ready_ms": 5, "cold": visit, "repeat_navigation": visit}])
    assert "warm" not in summary
    assert summary["repeat_navigation"]["palette_ready_ms"] == 10
