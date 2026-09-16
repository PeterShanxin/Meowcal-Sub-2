"""Saving corrected tracks must leave a ready, durable playback session."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from meocosub2.config import load_config, save_config
from meocosub2.engine import EngineInstallError
from meocosub2.overlay.subtitle_editor import SaveEdits
from tests.conftest import studio_client
from tests.test_subtitle_editor import SOURCE, TARGET, editor_server, edits


@pytest.fixture(autouse=True)
def ready_engine(monkeypatch):
    warm = AsyncMock()
    monkeypatch.setattr("meocosub2.overlay.controller.engine.ensure_ready", warm)
    return warm


@pytest.mark.parametrize("changed_key", ["source:source-1", "target"])
@pytest.mark.parametrize("fault", ["modified", "deleted", "missing-revision"])
def test_save_rejects_stale_unchanged_tracks(tmp_path, changed_key, fault):
    server = editor_server(tmp_path)
    with studio_client(server) as client:
        request = edits(client)
        request["files"] = [f for f in request["files"] if f["key"] == changed_key]
        unchanged_key = "target" if changed_key != "target" else "source:source-1"
        unchanged = tmp_path / ("target.vtt" if unchanged_key == "target" else "source.srt")
        if fault == "modified":
            unchanged.write_text("different track", encoding="utf-8")
        elif fault == "deleted":
            unchanged.unlink()
        else:
            del request["revisions"][unchanged_key]
        response = client.post("/api/subtitle-editor/save", json=request)
        assert response.status_code == 400, response.text
        assert not list(tmp_path.glob("subtitles/corrected/*"))
        assert server.controller._state.prepared_session.session_id == "initial"


def test_config_write_failure_keeps_previous_session_and_bias(tmp_path, monkeypatch):
    server = editor_server(tmp_path)
    save_config(server.controller.config, tmp_path / "config.toml")
    original = server.controller._prepared_runtime

    def fail(*args):
        raise OSError("Config is read-only")

    monkeypatch.setattr("meocosub2.overlay.controller.save_config", fail)
    with studio_client(server) as client:
        response = client.post("/api/subtitle-editor/save", json=edits(client))
        assert response.status_code == 400, response.text
        assert "read-only" in response.json()["detail"]
    assert server.controller._prepared_runtime is original
    assert server.controller._state.prepared_session.session_id == "initial"
    assert server.controller.config.sync_bias_ms == 800
    assert load_config(tmp_path / "config.toml").sync_bias_ms == 800
    assert not list(tmp_path.glob("subtitles/corrected/*"))


@pytest.mark.parametrize("available", [False, True])
def test_monolingual_replacement_requires_ready_engine(tmp_path, ready_engine, available):
    server = editor_server(tmp_path)
    controller = server.controller
    controller._state.prepared_session = replace(
        controller._state.prepared_session, target_path=None, used_translation=False
    )
    (tmp_path / "source.srt").write_text(
        SOURCE.replace("Hello world", "Hello world\n你好世界"), encoding="utf-8"
    )
    if not available:
        ready_engine.side_effect = EngineInstallError("Install local translation first")
    with studio_client(server) as client:
        request = edits(client, **{"source:source-1": SOURCE})
        response = client.post("/api/subtitle-editor/save", json=request)
    ready_engine.assert_awaited_once()
    assert response.status_code == (200 if available else 502), response.text
    if available:
        assert response.json()["session"]["used_translation"] is True
        assert load_config(tmp_path / "config.toml").sync_bias_ms == 0
    else:
        assert controller._state.prepared_session.session_id == "initial"
        assert controller.config.sync_bias_ms == 800
        assert not list(tmp_path.glob("subtitles/corrected/*"))


def test_human_target_remains_usable_without_engine(tmp_path, ready_engine):
    server = editor_server(tmp_path)
    ready_engine.side_effect = EngineInstallError("Not installed")
    with studio_client(server) as client:
        response = client.post("/api/subtitle-editor/save", json=edits(client))
        assert response.status_code == 200, response.text
        assert response.json()["state"]["warning_message"]
        assert server.controller._prefill_task is None


def request_for(controller, **contents):
    payload = controller.read_subtitle_editor("initial")
    return SaveEdits(
        sessionId="initial",
        revisions={f["key"]: f["revision"] for f in payload["files"]},
        files=[
            {"key": key, "format": "vtt" if key == "target" else "srt", "content": text}
            for key, text in contents.items()
        ],
    )


@pytest.mark.asyncio
async def test_save_restarts_prefill_on_rebuilt_track(tmp_path, monkeypatch):
    controller = editor_server(tmp_path).controller
    filled = []

    async def fill(lines, config, on_progress, answer):
        filled.extend(line.text for line in lines if not answer(line))
        await on_progress(len(filled))

    monkeypatch.setattr("meocosub2.overlay.controller.fill_before_the_session", fill)
    await controller.save_subtitle_edits(
        request_for(controller, target=TARGET.split("\n\n00:00:03")[0] + "\n")
    )
    assert controller._prefill_task is not None
    await asyncio.wait_for(controller._prefill_task, 2)
    assert filled == ["Another line"]
    assert controller.state_snapshot()["gap_fill"] == {"filled": 1, "total": 1, "active": False}
    await controller.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["disk", "session", "running", "cancel"])
async def test_save_rechecks_after_engine_wait(tmp_path, monkeypatch, fault):
    controller = editor_server(tmp_path).controller
    entered, release = asyncio.Event(), asyncio.Event()

    async def warm():
        entered.set()
        await asyncio.wait_for(release.wait(), 2)

    monkeypatch.setattr("meocosub2.overlay.controller.engine.ensure_ready", warm)
    task = asyncio.create_task(
        controller.save_subtitle_edits(request_for(controller, target=TARGET))
    )
    await asyncio.wait_for(entered.wait(), 2)
    expected = ValueError
    if fault == "disk":
        (tmp_path / "source.srt").write_text("external change", encoding="utf-8")
    elif fault == "session":
        controller._state.prepared_session = replace(
            controller._state.prepared_session, session_id="newer"
        )
    elif fault == "running":
        controller._state.status = "running"
        expected = RuntimeError
    else:
        task.cancel()
        expected = asyncio.CancelledError
    release.set()
    with pytest.raises(expected):
        await task
    assert not list(tmp_path.glob("subtitles/corrected/*"))
    assert controller.config.sync_bias_ms == 800
    await controller.shutdown()


@pytest.mark.asyncio
async def test_save_does_not_prefill_after_playback_takes_over(tmp_path, monkeypatch):
    controller = editor_server(tmp_path).controller
    fill = AsyncMock()
    monkeypatch.setattr("meocosub2.overlay.controller.fill_before_the_session", fill)

    async def broadcast():
        # A client can press Start as soon as the corrected session is published.
        controller._state.status = "running"

    monkeypatch.setattr(controller, "_emit_app_state", broadcast)
    await controller.save_subtitle_edits(
        request_for(controller, target=TARGET.split("\n\n00:00:03")[0] + "\n")
    )
    assert controller._prefill_task is None
    fill.assert_not_awaited()
    await controller.shutdown()
