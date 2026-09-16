import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from meocosub2.config import AppConfig, load_config
from meocosub2.models import PreparedRuntime, PreparedSession, SourceSubtitleCandidate
from meocosub2.overlay.server import OverlayServer
from meocosub2.overlay.subtitle_editor import MAX_BYTES, validate_content
from meocosub2.subtitles import align_subtitles, load_subtitle_file
from tests.conftest import TEST_TOKEN, studio_client

SOURCE = "1\n00:00:01,000 --> 00:00:02,000\nHello world\n\n2\n00:00:03,000 --> 00:00:04,000\nAnother line\n"
TARGET = "WEBVTT - demo\n\nNOTE retained\n猫\n\nfirst\n00:00:01.000 --> 00:00:02.000 align:start\n你好世界\n\n00:00:03.000 --> 00:00:04.000\n下一行\n"


@pytest.fixture(autouse=True)
def ready_engine(monkeypatch):
    monkeypatch.setattr("meocosub2.overlay.controller.engine.ensure_ready", AsyncMock())


def editor_server(tmp_path: Path) -> OverlayServer:
    source, target = tmp_path / "source.srt", tmp_path / "target.vtt"
    source.write_text(SOURCE, encoding="utf-8")
    target.write_text(TARGET, encoding="utf-8")
    server = OverlayServer(
        AppConfig(sync_bias_ms=800, capture_region=[0, 0, 500, 100]),
        tmp_path / "config.toml",
        access_token=TEST_TOKEN,
    )
    target_lines = load_subtitle_file(target)
    server.controller._prepared_runtime = PreparedRuntime(
        "subtitle_pair",
        target_lines=target_lines,
        source_candidates=[
            SourceSubtitleCandidate(
                "source-1",
                source.name,
                "Local",
                "en",
                str(source),
                align_subtitles(load_subtitle_file(source), target_lines),
            )
        ],
    )
    server.controller._state.prepared_session = PreparedSession(
        session_id="initial",
        title="Subtitle editor demo",
        source_language="en",
        target_language="zh",
        resolved_source_language="en",
        source_language_mode="exact",
        source_file_id="source-1",
        source_path=str(source),
        source_file_name=source.name,
        source_line_count=2,
        target_file_id="target-1",
        target_path=str(target),
        target_file_name=target.name,
        target_line_count=2,
    )
    return server


def edits(client, **contents):
    payload = client.get("/api/subtitle-editor/initial").json()
    return {
        "sessionId": payload["sessionId"],
        "revisions": {item["key"]: item["revision"] for item in payload["files"]},
        "files": [
            dict(
                key=item["key"],
                format="vtt" if item["key"] == "target" else "srt",
                content=contents.get(item["key"], item["content"].replace("\r\n", "\n")),
            )
            for item in payload["files"]
        ],
    }


def test_save_copies_preserves_notes_rebuilds_tracks_and_resets_bias(tmp_path):
    server = editor_server(tmp_path)
    with studio_client(server) as client:
        request = edits(
            client,
            **{
                "source:source-1": SOURCE.replace("Hello world", "Corrected source"),
                "target": TARGET.replace("01.000", "01.500").replace("02.000", "02.500"),
            },
        )
        response = client.post("/api/subtitle-editor/save", json=request)
        assert response.status_code == 200, response.text
        session = response.json()["session"]
        assert session["session_id"] != "initial"
        assert (
            Path(session["source_path"]).read_text(encoding="utf-8")
            == request["files"][0]["content"]
        )
        assert (
            Path(session["target_path"]).read_text(encoding="utf-8")
            == request["files"][1]["content"]
        )
        assert (tmp_path / "source.srt").read_text(encoding="utf-8") == SOURCE
        assert (tmp_path / "target.vtt").read_text(encoding="utf-8") == TARGET
        runtime = server.controller._prepared_runtime
        assert runtime.source_candidates[0].pair.source_lines[0].text == "Corrected source"
        assert runtime.target_lines[0].start_ms == 1500
        assert runtime.target_lines[0].end_ms == 2500
        assert runtime.source_candidates[0].pair.presentation.target_lines[0].start_ms == 1500
        assert client.get("/api/state").json()["config"]["sync"]["biasMs"] == 0
        assert load_config(tmp_path / "config.toml").sync_bias_ms == 0
        assert client.post("/api/subtitle-editor/save", json=request).status_code == 400
        reopened = client.get(f"/api/subtitle-editor/{session['session_id']}").json()
        assert reopened["files"][1]["content"] == request["files"][1]["content"]


@pytest.mark.parametrize("status", ["running", "preparing", "searching", "stopping"])
def test_live_or_busy_session_cannot_be_read_or_changed(tmp_path, status):
    server = editor_server(tmp_path)
    with studio_client(server) as client:
        request = edits(client)
        server.controller._state.status = status
        assert client.get("/api/subtitle-editor/initial").status_code == 409
        assert client.post("/api/subtitle-editor/save", json=request).status_code == 409
        assert not (tmp_path / "subtitles").exists()


@pytest.mark.parametrize("fault", ["stale", "external", "duplicate", "foreign", "invalid"])
def test_invalid_batch_leaves_all_original_tracks_and_session_unchanged(tmp_path, fault):
    server = editor_server(tmp_path)
    with studio_client(server) as client:
        request = edits(client)
        if fault == "stale":
            request["sessionId"] = "old-session"
        elif fault == "external":
            (tmp_path / "target.vtt").write_text(TARGET + "\n", encoding="utf-8")
        elif fault == "duplicate":
            request["files"][1] = request["files"][0]
        elif fault == "foreign":
            request["files"][1]["key"] = "../../private.srt"
        else:
            request["files"][1]["content"] = "WEBVTT\n\nbroken"
        response = client.post("/api/subtitle-editor/save", json=request)
        assert response.status_code == 400
        assert not (tmp_path / "subtitles").exists()
        assert server.controller._state.prepared_session.session_id == "initial"
        assert server.controller.config.sync_bias_ms == 800


def test_editor_routes_require_token_and_same_origin(tmp_path):
    with studio_client(editor_server(tmp_path)) as client:
        assert (
            client.get(
                "/api/subtitle-editor/initial", headers={"X-Meowcal-Token": "bad"}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/subtitle-editor/save", json={}, headers={"Origin": "https://foreign.example"}
            ).status_code
            == 403
        )


@pytest.mark.parametrize(
    "content,format",
    [
        ("WEBVTT\n\n", "vtt"),
        (SOURCE.replace("02,000", "00,500"), "srt"),
        (SOURCE.replace("Hello world", "\0"), "srt"),
        (SOURCE.replace("Hello world", "\ud800"), "srt"),
        (SOURCE.replace("Hello world", ""), "srt"),
        (SOURCE.replace("01,000", "01,00"), "srt"),
        (SOURCE.replace("1\n", "bad\n", 1), "srt"),
        (TARGET.replace("NOTE retained", "NOTE -->"), "vtt"),
        pytest.param("x" * (MAX_BYTES + 1), "srt", id="oversized"),
    ],
)
def test_storage_rejects_unusable_exports(content, format):
    with pytest.raises(ValueError):
        validate_content(content, format)


def test_rebuild_failure_removes_only_new_copies(tmp_path, monkeypatch):
    server = editor_server(tmp_path)

    def fail(_, **kwargs):
        raise ValueError("Cannot read playback track")

    with studio_client(server) as client:
        request = edits(client)
        monkeypatch.setattr("meocosub2.overlay.subtitle_editor.load_subtitle_file", fail)
        assert client.post("/api/subtitle-editor/save", json=request).status_code == 400
        assert not list((tmp_path / "subtitles/corrected").iterdir())
        assert (tmp_path / "source.srt").exists()


def test_unsupported_and_invalid_encoding_tracks_report_per_file(tmp_path):
    server = editor_server(tmp_path)
    (tmp_path / "target.vtt").write_bytes(b"\xff")
    with studio_client(server) as client:
        response = client.get("/api/subtitle-editor/initial")
        assert response.status_code == 200
        assert "content" in response.json()["files"][0]
        assert "UTF-8" in response.json()["files"][1]["error"]


@pytest.mark.asyncio
async def test_sync_receives_corrected_runtime(tmp_path, monkeypatch):
    from meocosub2.overlay.subtitle_editor import EditFile, SaveEdits, revision

    server = editor_server(tmp_path)
    controller = server.controller
    captured = []

    async def sync(runtime, config):
        captured.append((runtime.target_lines[0].start_ms, config.sync_bias_ms))

    monkeypatch.setattr(controller, "_run_sync_loop", sync)
    monkeypatch.setattr(
        "meocosub2.overlay.controller.resolve_ocr_language",
        lambda _: SimpleNamespace(
            warning_message="", resolved_language="en-US", requested_language="en-US"
        ),
    )
    updated = await controller.save_subtitle_edits(
        SaveEdits(
            sessionId="initial",
            revisions={
                "target": revision((tmp_path / "target.vtt").read_bytes()),
                "source:source-1": revision((tmp_path / "source.srt").read_bytes()),
            },
            files=[
                EditFile(
                    key="target",
                    format="vtt",
                    content=TARGET.replace("01.000", "01.500"),
                )
            ],
        )
    )
    await controller.start_session(updated.session_id)
    await asyncio.wait_for(controller._sync_task, 1)
    assert captured == [(1500, 0)]
    await controller.shutdown()


def test_auto_candidate_and_bilingual_tracks_rebuild_independently(tmp_path):
    server = editor_server(tmp_path)
    controller = server.controller
    extra = tmp_path / "extra.srt"
    extra.write_text(SOURCE.replace("Hello world", "Hello world\n你好世界"), encoding="utf-8")
    first = controller._prepared_runtime.source_candidates[0]
    controller._prepared_runtime.source_candidates.append(
        replace(first, result_id="source-2", path=str(extra))
    )
    with studio_client(server) as client:
        response = client.post("/api/subtitle-editor/save", json=edits(client))
        assert response.status_code == 200, response.text
        runtime = controller._prepared_runtime
        assert len(runtime.source_candidates) == 2
        assert runtime.source_candidates[1].pair.source_lines[0].translated == "你好世界"


@pytest.mark.asyncio
@pytest.mark.parametrize("clear", [False, True])
async def test_start_rechecks_session_after_waiting_for_prefill(tmp_path, monkeypatch, clear):
    controller = editor_server(tmp_path).controller
    entered, release = asyncio.Event(), asyncio.Event()
    stop_prefill = controller._stop_prefill

    async def wait_prefill():
        entered.set()
        await asyncio.wait_for(release.wait(), 2)

    monkeypatch.setattr(controller, "_stop_prefill", wait_prefill)
    monkeypatch.setattr(
        "meocosub2.overlay.controller.resolve_ocr_language",
        lambda _: SimpleNamespace(
            warning_message="", resolved_language="en-US", requested_language="en-US"
        ),
    )
    task = asyncio.create_task(controller.start_session("initial"))
    await asyncio.wait_for(entered.wait(), 2)
    controller._state.prepared_session = (
        None if clear else replace(controller._state.prepared_session, session_id="corrected")
    )
    release.set()
    with pytest.raises(ValueError, match="Subtitles changed"):
        await task
    assert controller._sync_task is None
    monkeypatch.setattr(controller, "_stop_prefill", stop_prefill)
    await controller.shutdown()
