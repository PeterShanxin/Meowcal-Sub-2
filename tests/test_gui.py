import json
from pathlib import Path

from meocosub2.config import AppConfig
from meocosub2.errors import OpenSubtitlesError, TranslationError
from meocosub2.overlay.server import OverlayServer
from tests.conftest import TEST_TOKEN, studio_client


def make_server(config_path: Path | None = None) -> OverlayServer:
    return OverlayServer(AppConfig(), config_path=config_path, access_token=TEST_TOKEN)


def test_state_route_returns_snapshot(tmp_path: Path) -> None:
    server = make_server(tmp_path / "config.toml")
    with studio_client(server) as client:
        response = client.get("/api/state")
    assert response.status_code == 200
    assert response.json()["status"] == "idle"
    assert response.json()["search_matches"] == []
    assert response.json()["selected_feature_id"] is None


def test_search_route_delegates_to_controller(tmp_path: Path, mocker) -> None:
    server = make_server(tmp_path / "config.toml")
    search = mocker.patch.object(
        server.controller,
        "search",
        new=mocker.AsyncMock(
            return_value={
                "results": [{"fileId": 42, "language": "en"}],
                "matches": [{"id": 7, "title": "Inception"}],
            }
        ),
    )
    with studio_client(server) as client:
        response = client.post(
            "/api/search",
            json={"title": "Inception", "sourceLanguage": "en", "targetLanguage": "zht"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "results": [{"fileId": 42, "language": "en"}],
        "matches": [{"id": 7, "title": "Inception"}],
    }
    request = search.await_args.args[0]
    assert request.title == "Inception"
    assert request.source_language == "en"
    assert request.target_language == "zht"
    assert request.correlation_id is None


def test_client_log_route_writes_structured_event(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("MEOCOSUB2_EVENT_LOG_PATH", str(log_path))
    server = make_server(tmp_path / "config.toml")

    with studio_client(server) as client:
        response = client.post(
            "/api/log/client",
            json={
                "event": "ui.search.submitted",
                "correlationId": "search-123",
                "data": {"token": "secret", "title": "Fate"},
            },
        )

    assert response.status_code == 200
    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert record["layer"] == "frontend"
    assert record["event"] == "ui.search.submitted"
    assert record["correlation_id"] == "search-123"
    assert record["data"]["token"] == "[redacted]"
    assert record["data"]["title"] == "Fate"


def test_prepare_start_and_stop_routes_delegate_to_controller(tmp_path: Path, mocker) -> None:
    server = make_server(tmp_path / "config.toml")
    prepare = mocker.patch.object(
        server.controller,
        "prepare_session",
        new=mocker.AsyncMock(return_value={"session_id": "abc123", "session_mode": "subtitle_pair"}),
    )
    start = mocker.patch.object(
        server.controller,
        "start_session",
        new=mocker.AsyncMock(return_value={"status": "running"}),
    )
    stop = mocker.patch.object(
        server.controller,
        "stop_session",
        new=mocker.AsyncMock(return_value={"status": "idle"}),
    )

    with studio_client(server) as client:
        prepare_response = client.post(
            "/api/session/prepare",
            json={"mode": "subtitle_pair", "featureId": 99, "sourceFileId": 1, "targetFileId": 2},
        )
        start_response = client.post("/api/session/start", json={"sessionId": "abc123"})
        stop_response = client.post("/api/session/stop")

    assert prepare_response.status_code == 200
    assert prepare_response.json()["session"]["session_id"] == "abc123"
    assert prepare_response.json()["session"]["session_mode"] == "subtitle_pair"
    assert start_response.json()["status"] == "running"
    assert stop_response.json()["status"] == "idle"
    prepare.assert_awaited_once_with(
        mode="subtitle_pair",
        feature_id=99,
        source_file_id=1,
        target_file_id=2,
    )
    start.assert_awaited_once_with("abc123")
    stop.assert_awaited_once_with()


def test_prepare_route_supports_ocr_fallback_mode(tmp_path: Path, mocker) -> None:
    server = make_server(tmp_path / "config.toml")
    prepare = mocker.patch.object(
        server.controller,
        "prepare_session",
        new=mocker.AsyncMock(return_value={"session_id": "fallback01", "session_mode": "ocr_fallback"}),
    )

    with studio_client(server) as client:
        response = client.post(
            "/api/session/prepare",
            json={"mode": "ocr_fallback", "featureId": 2239923, "targetFileId": 200},
        )

    assert response.status_code == 200
    assert response.json()["session"]["session_mode"] == "ocr_fallback"
    prepare.assert_awaited_once_with(
        mode="ocr_fallback",
        feature_id=2239923,
        source_file_id=None,
        target_file_id=200,
    )


def test_prepare_route_supports_auto_candidate_mode(tmp_path: Path, mocker) -> None:
    server = make_server(tmp_path / "config.toml")
    prepare = mocker.patch.object(
        server.controller,
        "prepare_session",
        new=mocker.AsyncMock(return_value={"session_id": "auto01", "session_mode": "auto_candidates"}),
    )

    with studio_client(server) as client:
        response = client.post(
            "/api/session/prepare",
            json={"mode": "auto_candidates", "matchId": "match-1"},
        )

    assert response.status_code == 200
    assert response.json()["session"]["session_mode"] == "auto_candidates"
    prepare.assert_awaited_once_with(
        mode="auto_candidates",
        feature_id="match-1",
        source_file_id=None,
        target_file_id=None,
    )


def test_start_route_returns_conflict_on_runtime_error(tmp_path: Path, mocker) -> None:
    server = make_server(tmp_path / "config.toml")
    mocker.patch.object(
        server.controller,
        "start_session",
        new=mocker.AsyncMock(side_effect=RuntimeError("A session is already running.")),
    )
    with studio_client(server) as client:
        response = client.post("/api/session/start", json={"sessionId": "abc123"})

    assert response.status_code == 409
    assert response.json()["detail"] == "A session is already running."


def test_search_route_returns_bad_gateway_on_opensubtitles_error(tmp_path: Path, mocker) -> None:
    server = make_server(tmp_path / "config.toml")
    mocker.patch.object(
        server.controller,
        "search",
        new=mocker.AsyncMock(side_effect=OpenSubtitlesError("OpenSubtitles search failed: 403")),
    )
    with studio_client(server) as client:
        response = client.post(
            "/api/search",
            json={"title": "Inception", "sourceLanguage": "en", "targetLanguage": "zht"},
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "OpenSubtitles search failed: 403"


def test_languages_route_returns_catalog(tmp_path: Path, mocker) -> None:
    server = make_server(tmp_path / "config.toml")
    mocker.patch("meocosub2.overlay.server.available_ocr_languages", return_value=["en-US", "zh-Hans-CN"])
    with studio_client(server) as client:
        response = client.get("/api/languages")

    assert response.status_code == 200
    assert any(item["code"] == "en" for item in response.json()["sourceTarget"])
    assert any(item["code"] == "zh-CN" and item["installed"] for item in response.json()["ocr"])


def test_engine_status_route_delegates_to_controller(tmp_path: Path, mocker) -> None:
    server = make_server(tmp_path / "config.toml")
    status = {
        "phase": "ready",
        "message": "Local translation is ready (GPU).",
        "model": "HY-MT1.5-1.8B-Q4_K_M",
        "endpoint": "http://127.0.0.1:11436",
        "ready": True,
        "installPercent": 100,
        "accelerator": "GPU",
    }
    getter = mocker.patch.object(
        server.controller,
        "get_engine_status_payload",
        new=mocker.AsyncMock(return_value=status),
    )
    with studio_client(server) as client:
        response = client.get("/api/engine/status")

    assert response.status_code == 200
    assert response.json()["phase"] == "ready"
    getter.assert_awaited_once_with()


def test_prepare_route_returns_bad_gateway_on_translation_error(tmp_path: Path, mocker) -> None:
    server = make_server(tmp_path / "config.toml")
    mocker.patch.object(
        server.controller,
        "prepare_session",
        new=mocker.AsyncMock(side_effect=TranslationError("Foundry Local translation request failed")),
    )
    with studio_client(server) as client:
        response = client.post("/api/session/prepare", json={"mode": "subtitle_pair", "sourceFileId": 1})

    assert response.status_code == 502
    assert "Foundry Local" in response.json()["detail"]


def test_capture_screen_route_returns_the_region_it_was_asked_for(tmp_path: Path, mocker) -> None:
    server = make_server(tmp_path / "config.toml")
    grab = mocker.patch(
        "meocosub2.overlay.server.capture_region_jpeg", return_value=b"\xff\xd8jpeg"
    )
    with studio_client(server) as client:
        response = client.get(
            "/api/capture/screen", params={"x": -1920, "y": 40, "width": 2560, "height": 1440}
        )
    assert response.status_code == 200
    # A monitor left of the primary one has a negative origin, and the selector
    # draws on the whole of it: anything lost here is a still of the wrong screen.
    grab.assert_called_once_with((-1920, 40, 2560, 1440))
    assert response.json()["dataUrl"].startswith("data:image/jpeg;base64,")
