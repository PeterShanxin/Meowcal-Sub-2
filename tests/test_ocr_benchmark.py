"""Performance budget checks must reject both slow reads and deadline regressions."""

import importlib.util
from pathlib import Path


def module():
    path = Path(__file__).resolve().parents[1] / "scripts/benchmark_core_ocr.py"
    spec = importlib.util.spec_from_file_location("benchmark_core_ocr", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_budget_rejects_latency_and_deadline_regressions():
    compare = module().compare
    baseline = {"p50Ms": 30, "p95Ms": 50, "over250Rate": 0}
    assert compare(baseline, {"p50Ms": 38, "p95Ms": 62, "over250Rate": 0})["passed"]
    for key, value in (("p50Ms", 41), ("p95Ms", 66), ("over250Rate", 0.02)):
        assert not compare(baseline, {**baseline, key: value})["passed"]


def test_summary_retains_a_single_long_stall_in_deadline_rate_and_max():
    report = module().summarize([10.0] * 99 + [400.0])
    assert report["p50Ms"] == 10
    assert report["maxMs"] == 400
    assert report["over250Rate"] == 0.01
