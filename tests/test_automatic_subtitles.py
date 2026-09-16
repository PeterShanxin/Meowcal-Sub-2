import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_controller import _pair_controller

UNORDERED = (
    "1\n00:00:03,000 --> 00:00:04,000\nLater\n\n"
    "2\n00:00:01,000 --> 00:00:02,000\nFirst\n\n"
    "3\n00:00:01,000 --> 00:00:02,000\nFirst\n"
)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["subtitle_pair", "auto_candidates", "ocr_fallback"])
async def test_preparation_uses_checked_tracks_without_opening_editor(tmp_path, mocker, mode):
    controller, _, download = _pair_controller(tmp_path, mocker, UNORDERED, UNORDERED)
    controller._state.selected_feature_id = "match-1"
    if mode == "ocr_fallback":
        download.side_effect = [tmp_path / "target.srt"]
    originals = {path: path.read_bytes() for path in tmp_path.glob("*.srt")}

    session = await controller.prepare_session(
        mode=mode, feature_id="match-1", source_file_id="result-1", target_file_id="result-2"
    )

    assert session["target_line_count"] == 2
    checks = session["subtitle_checks"]
    assert len(checks) == (1 if mode == "ocr_fallback" else 2)
    assert all(check["duplicates_removed"] == 1 and check["reordered"] for check in checks)
    assert controller.state_snapshot()["prepared_session"]["subtitle_checks"] == checks
    runtime = controller._prepared_runtime
    assert runtime is not None
    assert [(line.index, line.start_ms) for line in runtime.target_lines] == [(0, 1000), (1, 3000)]
    for candidate in runtime.source_candidates:
        assert len(candidate.pair.source_lines) == 2
        assert candidate.pair.presentation.resolve_at(1500).text == "First"
        assert candidate.pair.presentation.resolve_at(2500).text == ""
    for path, raw in originals.items():
        assert path.read_bytes() == raw
    assert not (tmp_path / "subtitles" / "corrected").exists()
    controller.config = replace(controller.config, capture_region=[0, 0, 500, 100])
    mocker.patch(
        "meocosub2.overlay.controller.resolve_ocr_language",
        return_value=SimpleNamespace(
            warning_message="", resolved_language="en-US", requested_language="en-US"
        ),
    )
    sync = mocker.patch.object(controller, "_run_sync_loop", new_callable=mocker.AsyncMock)
    await controller.start_session(session["session_id"])
    await asyncio.wait_for(controller._sync_task, 1)
    assert sync.call_args.args[0] is runtime
    await controller.shutdown()


@pytest.mark.asyncio
async def test_broken_interval_stops_preparation_before_engine_start(tmp_path: Path, mocker):
    controller, warm, _ = _pair_controller(
        tmp_path, mocker, UNORDERED.replace("00:00:04,000", "00:00:02,000"), UNORDERED
    )
    with pytest.raises(ValueError, match="source.srt.*cue 1.*timing"):
        await controller.prepare_session(
            mode="subtitle_pair",
            feature_id="match-1",
            source_file_id="result-1",
            target_file_id="result-2",
        )
    assert warm.await_count == 0
    assert controller.state_snapshot()["status"] == "error"
