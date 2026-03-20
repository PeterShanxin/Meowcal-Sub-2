from pathlib import Path

from fastapi.testclient import TestClient

from meocosub2.config import AppConfig
from meocosub2.errors import OpenSubtitlesError, TranslationError
from meocosub2.overlay.server import OverlayServer


def make_server(config_path: Path | None = None) -> OverlayServer:
    return OverlayServer(AppConfig(), config_path=config_path)


def test_state_route_returns_snapshot(tmp_path: Path) -> None:
    server = make_server(tmp_path / "config.toml")
    with TestClient(server.app) as client:
        response = client.get("/api/state")
    assert response.status_code == 200
    assert response.json()["status"] == "idle"
    assert response.json()["overlay_url"].endswith("/overlay")


def test_search_route_delegates_to_controller(tmp_path: Path, mocker) -> None:
    server = make_server(tmp_path / "config.toml")
    search = mocker.patch.object(
        server.controller,
        "search",
        new=mocker.AsyncMock(return_value=[{"fileId": 42, "language": "en"}]),
    )
    with TestClient(server.app) as client:
        response = client.post(
            "/api/search",
            json={"title": "Inception", "sourceLanguage": "en", "targetLanguage": "zht"},
        )

    assert response.status_code == 200
    assert response.json() == {"results": [{"fileId": 42, "language": "en"}]}
    request = search.await_args.args[0]
    assert request.title == "Inception"
    assert request.source_language == "en"
    assert request.target_language == "zht"


def test_prepare_start_and_stop_routes_delegate_to_controller(tmp_path: Path, mocker) -> None:
    server = make_server(tmp_path / "config.toml")
    prepare = mocker.patch.object(
        server.controller,
        "prepare_session",
        new=mocker.AsyncMock(return_value={"session_id": "abc123"}),
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

    with TestClient(server.app) as client:
        prepare_response = client.post("/api/session/prepare", json={"sourceFileId": 1, "targetFileId": 2})
        start_response = client.post("/api/session/start", json={"sessionId": "abc123"})
        stop_response = client.post("/api/session/stop")

    assert prepare_response.status_code == 200
    assert prepare_response.json()["session"]["session_id"] == "abc123"
    assert start_response.json()["status"] == "running"
    assert stop_response.json()["status"] == "idle"
    prepare.assert_awaited_once_with(source_file_id=1, target_file_id=2)
    start.assert_awaited_once_with("abc123")
    stop.assert_awaited_once_with()


def test_start_route_returns_conflict_on_runtime_error(tmp_path: Path, mocker) -> None:
    server = make_server(tmp_path / "config.toml")
    mocker.patch.object(
        server.controller,
        "start_session",
        new=mocker.AsyncMock(side_effect=RuntimeError("A session is already running.")),
    )
    with TestClient(server.app) as client:
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
    with TestClient(server.app) as client:
        response = client.post(
            "/api/search",
            json={"title": "Inception", "sourceLanguage": "en", "targetLanguage": "zht"},
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "OpenSubtitles search failed: 403"


def test_languages_route_returns_catalog(tmp_path: Path, mocker) -> None:
    server = make_server(tmp_path / "config.toml")
    mocker.patch("meocosub2.overlay.server.available_ocr_languages", return_value=["en-US", "zh-Hans-CN"])
    with TestClient(server.app) as client:
        response = client.get("/api/languages")

    assert response.status_code == 200
    assert any(item["code"] == "en" for item in response.json()["sourceTarget"])
    assert any(item["code"] == "zh-CN" and item["installed"] for item in response.json()["ocr"])


def test_foundry_status_route_delegates_to_controller(tmp_path: Path, mocker) -> None:
    server = make_server(tmp_path / "config.toml")
    status = {
        "cli_available": True,
        "service_running": True,
        "service_url": "http://127.0.0.1:5273",
        "models": ["phi:mini"],
        "configured_model": None,
        "selected_model": "phi:mini",
        "phase": "ready",
        "notes": "Ready.",
    }
    getter = mocker.patch.object(
        server.controller,
        "get_foundry_status_payload",
        new=mocker.AsyncMock(return_value=status),
    )
    with TestClient(server.app) as client:
        response = client.get("/api/foundry/status", params={"probe": "true"})

    assert response.status_code == 200
    assert response.json()["phase"] == "ready"
    getter.assert_awaited_once_with(probe=True, auto_start=False)


def test_prepare_route_returns_bad_gateway_on_translation_error(tmp_path: Path, mocker) -> None:
    server = make_server(tmp_path / "config.toml")
    mocker.patch.object(
        server.controller,
        "prepare_session",
        new=mocker.AsyncMock(side_effect=TranslationError("Foundry Local translation request failed")),
    )
    with TestClient(server.app) as client:
        response = client.post("/api/session/prepare", json={"sourceFileId": 1})

    assert response.status_code == 502
    assert "Foundry Local" in response.json()["detail"]
