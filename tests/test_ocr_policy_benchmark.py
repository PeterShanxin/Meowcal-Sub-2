import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from meocosub2 import capture, native_ocr


def benchmark():
    path = Path(__file__).resolve().parents[1] / "scripts/benchmark_ocr_policies.py"
    spec = importlib.util.spec_from_file_location("benchmark_ocr_policies", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_score_includes_missed_frames_wrong_matches_and_blank_false_positives():
    first, second = "Welcome home everybody", "Please close the door"
    truth = [
        {"frame": 0, "seconds": 0, "cue_id": "1", "truth": first, "phase": "stable"},
        {"frame": 1, "seconds": 0.1, "cue_id": "1", "truth": first, "phase": "stable"},
        {"frame": 2, "seconds": 1, "cue_id": "2", "truth": second, "phase": "stable"},
        {"frame": 3, "seconds": 2, "cue_id": "", "truth": "", "phase": "blank"},
    ]
    rows = [
        {**row, "output": output, "error": error, "ms": ms}
        for row, output, error, ms in zip(
            truth,
            [first, second, "", first],
            ["", "", "TimeoutError", ""],
            [12, 21, 1000, 18],
            strict=True,
        )
    ]
    score = benchmark().summarize(rows, truth, 1, 0.1, 0.2)
    assert score["stableExact"] == 1 / 3
    assert (score["textMatchCorrect"], score["textMatchWrong"], score["textMatchMiss"]) == (1, 1, 1)
    assert score["blankTextMatches"] == 1 and score["blankOutputRate"] == 1
    assert score["failures"] == 1 and score["maxMs"] == 1000
    assert score["over250Rate"] == 0.25


def test_zero_based_labels_align_with_one_based_png_names(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    for name in ("000001.png", "000002.png"):
        Image.new("RGB", (1, 1)).save(frames / name)
    (tmp_path / "truth.csv").write_text(
        "frame,seconds,cue_id,truth,phase\n0,0,1,Hello,stable\n1,0.1,1,Hello,stable\n", "utf-8"
    )
    assert [row["imageFile"] for row in benchmark().truth(tmp_path)] == ["000001.png", "000002.png"]


def test_unlabelled_real_cues_stop_the_benchmark(tmp_path):
    (tmp_path / "cues.csv").write_text("frame,seconds,cue_id,phase\n0,0,1,stable\n", "utf-8")
    (tmp_path / "labels.csv").write_text("cue_id,truth\n2,Other cue\n", "utf-8")
    with pytest.raises(ValueError, match="Unlabelled"):
        benchmark().truth(tmp_path)


@pytest.mark.parametrize("indices", [(1, 0), (0, 2)])
def test_out_of_order_or_missing_label_frames_stop_the_benchmark(tmp_path, indices):
    frames = tmp_path / "frames"
    frames.mkdir()
    for name in ("000001.png", "000002.png"):
        Image.new("RGB", (1, 1)).save(frames / name)
    (tmp_path / "truth.csv").write_text(
        "frame,seconds,cue_id,truth,phase\n"
        + "".join(f"{index},{index / 10},1,Hello,stable\n" for index in indices),
        "utf-8",
    )
    with pytest.raises(ValueError, match="consecutive and ordered"):
        benchmark().truth(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, TimeoutError(), RuntimeError("invalid geometry")])
async def test_ppocr_benchmark_distinguishes_blank_reads_from_suppressed_failures(
    monkeypatch, failure
):
    monkeypatch.setattr(
        capture,
        "prepare_ocr",
        AsyncMock(return_value=capture.OcrResolution("en", "en", engine="ppOcrV6")),
    )
    monkeypatch.setattr(
        native_ocr, "recognize_ppocr_lines", AsyncMock(return_value=[], side_effect=failure)
    )
    errors = []
    assert await benchmark().read(Image.new("RGB", (1, 1)), "en", "ppocr-height", 2, errors) == ""
    assert errors == ([f"ppocr:{type(failure).__name__}"] if failure else [])


@pytest.mark.asyncio
async def test_windows_benchmark_records_failed_pass_without_losing_the_best_read(monkeypatch):
    monkeypatch.setattr(
        capture, "prepare_ocr", AsyncMock(return_value=capture.OcrResolution("zh-CN", "zh-CN"))
    )
    monkeypatch.setattr(
        capture, "_run_ocr", AsyncMock(side_effect=[RuntimeError(), "A valid caption", ""])
    )
    errors = []
    output = await benchmark().read(Image.new("RGB", (1, 1)), "zh", "windows", 2, errors)
    assert output == "A valid caption"
    assert errors == ["windows-raw:RuntimeError"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, TimeoutError()])
async def test_windows_benchmark_distinguishes_a_blank_from_a_timeout(monkeypatch, failure):
    monkeypatch.setattr(
        capture, "prepare_ocr", AsyncMock(return_value=capture.OcrResolution("en", "en"))
    )
    monkeypatch.setattr(capture, "_run_ocr", AsyncMock(return_value="", side_effect=failure))
    errors = []
    assert await benchmark().read(Image.new("RGB", (1, 1)), "en", "windows", 2, errors) == ""
    assert errors == (["windows-preprocessed:TimeoutError"] if failure else [])


@pytest.mark.asyncio
async def test_ppocr_benchmark_reports_initialization_fallback(monkeypatch):
    monkeypatch.setattr(
        capture, "prepare_ocr", AsyncMock(return_value=capture.OcrResolution("en", "en"))
    )
    monkeypatch.setattr(capture, "_run_ocr", AsyncMock(return_value=""))
    errors = []
    assert await benchmark().read(Image.new("RGB", (1, 1)), "en", "ppocr-height", 2, errors) == ""
    assert errors == ["ppocr-initialization-fallback"]
