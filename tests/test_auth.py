from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meocosub2 import auth
from meocosub2.config import AppConfig
from meocosub2.overlay.server import OverlayServer
from tests.conftest import TEST_TOKEN, studio_client


def make_server(tmp_path: Path) -> OverlayServer:
    return OverlayServer(
        AppConfig(), config_path=tmp_path / "config.toml", access_token=TEST_TOKEN
    )


PRIVILEGED_GETS = ["/", "/config", "/api/state", "/api/config", "/api/languages"]


@pytest.mark.parametrize("path", PRIVILEGED_GETS)
def test_privileged_routes_reject_callers_without_the_token(tmp_path: Path, path: str) -> None:
    with TestClient(make_server(tmp_path).app) as client:
        assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", PRIVILEGED_GETS)
def test_privileged_routes_reject_a_wrong_token(tmp_path: Path, path: str) -> None:
    with TestClient(make_server(tmp_path).app) as client:
        response = client.get(path, headers={auth.TOKEN_HEADER: "not-the-token"})
        assert response.status_code == 401


def test_privileged_writes_reject_callers_without_the_token(tmp_path: Path) -> None:
    with TestClient(make_server(tmp_path).app) as client:
        assert client.post("/api/session/stop").status_code == 401
        assert client.post("/api/search", json={"title": "x"}).status_code == 401
        assert client.put("/api/config", json={}).status_code == 401


def test_the_token_is_accepted_in_the_query_string_for_navigation(tmp_path: Path) -> None:
    with TestClient(make_server(tmp_path).app) as client:
        assert client.get(f"/?token={TEST_TOKEN}").status_code == 200


def test_an_unauthenticated_response_carries_no_token(tmp_path: Path) -> None:
    with TestClient(make_server(tmp_path).app) as client:
        response = client.get("/")
    assert TEST_TOKEN not in response.text


def test_the_studio_page_bootstraps_the_token_for_the_page_itself(tmp_path: Path) -> None:
    with studio_client(make_server(tmp_path)) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert f'window.__MEOWCAL__={{"token": "{TEST_TOKEN}"}}' in response.text


def test_a_foreign_origin_is_refused_even_with_a_valid_token(tmp_path: Path) -> None:
    with studio_client(make_server(tmp_path)) as client:
        response = client.get("/api/state", headers={"origin": "https://evil.example"})
    assert response.status_code == 403


def test_the_studio_origin_is_allowed(tmp_path: Path) -> None:
    with studio_client(make_server(tmp_path)) as client:
        response = client.get("/api/state", headers={"origin": "http://127.0.0.1:8765"})
    assert response.status_code == 200


def test_the_static_bundle_stays_reachable_without_the_token(tmp_path: Path) -> None:
    with TestClient(make_server(tmp_path).app) as client:
        assert client.get("/static/selector.js").status_code == 200


def test_the_websocket_refuses_a_caller_without_the_token(tmp_path: Path) -> None:
    from starlette.websockets import WebSocketDisconnect

    with TestClient(make_server(tmp_path).app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/app") as socket:
                socket.receive_text()


def test_the_websocket_accepts_the_token_from_the_query_string(tmp_path: Path) -> None:
    with TestClient(make_server(tmp_path).app) as client:
        with client.websocket_connect(f"/ws/app?token={TEST_TOKEN}") as socket:
            assert socket.receive_json()["type"] == "state"


def test_the_runtime_file_round_trips_the_token(tmp_path: Path) -> None:
    target = tmp_path / "runtime.json"
    auth.publish_runtime("abc", 8765, target)
    assert auth.read_runtime(target) == {"token": "abc", "port": 8765}
    auth.clear_runtime(target)
    assert auth.read_runtime(target) == {}


def test_token_comparison_rejects_empty_and_wrong_values() -> None:
    assert auth.token_matches("secret", "secret")
    assert not auth.token_matches("secret", "")
    assert not auth.token_matches("secret", None)
    assert not auth.token_matches("secret", "secre")
