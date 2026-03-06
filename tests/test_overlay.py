import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from meocosub2.config import AppConfig
from meocosub2.overlay.server import OverlayServer


def make_server(config_path: Path | None = None) -> OverlayServer:
    return OverlayServer(
        AppConfig(
            overlay_font_size=32,
            overlay_font_family="Test Font",
            overlay_text_color="#123456",
            overlay_bg_color="rgba(1,2,3,0.5)",
            overlay_position="top",
            overlay_radius_px=30,
            overlay_padding_px=18,
            overlay_max_width_vw=72,
            overlay_blur_px=16,
            overlay_shadow_strength=0.55,
            overlay_offset_pct=8,
            overlay_animation_ms=180,
        ),
        config_path=config_path,
    )


def test_dashboard_and_overlay_pages_served(tmp_path: Path) -> None:
    server = make_server(tmp_path / "config.toml")
    with TestClient(server.app) as client:
        dashboard = client.get("/")
        overlay = client.get("/overlay")
    assert dashboard.status_code == 200
    assert "Meowcal Subtitle Studio" in dashboard.text
    assert overlay.status_code == 200
    assert "subtitle-shell" in overlay.text


def test_config_routes_return_compat_and_nested_payload(tmp_path: Path) -> None:
    server = make_server(tmp_path / "config.toml")
    with TestClient(server.app) as client:
        compat = client.get("/config")
        api_payload = client.get("/api/config")

    assert compat.json() == {
        "theme": "glass-cinematic",
        "fontSize": 32,
        "fontFamily": "Test Font",
        "textColor": "#123456",
        "bgColor": "rgba(1,2,3,0.5)",
        "position": "top",
        "radiusPx": 30,
        "paddingPx": 18,
        "maxWidthVw": 72,
        "blurPx": 16,
        "shadowStrength": 0.55,
        "offsetPct": 8,
        "animationMs": 180,
    }
    assert api_payload.json()["overlay"]["radiusPx"] == 30


def test_put_config_updates_api_payload_and_persists_style(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    server = make_server(config_path)
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws") as websocket:
            initial = json.loads(websocket.receive_text())
            response = client.put(
                "/api/config",
                json={
                    "opensubtitles": {"apiKey": "key"},
                    "languages": {"source": "en", "target": "zht"},
                    "capture": {"region": [0, 1, 2, 3], "intervalMs": 500, "ocrLanguage": "en"},
                    "matching": {"fuzzyThreshold": 70, "windowSize": 20},
                    "translation": {"endpoint": "http://127.0.0.1:5273/v1", "model": "m", "timeoutS": 30, "batchSize": 5},
                    "overlay": {
                        "port": 8765,
                        "theme": "glass-cinematic",
                        "fontSize": 44,
                        "fontFamily": "Studio Font",
                        "textColor": "#ffffff",
                        "bgColor": "rgba(0,0,0,0.65)",
                        "position": "bottom",
                        "radiusPx": 36,
                        "paddingPx": 22,
                        "maxWidthVw": 70,
                        "blurPx": 24,
                        "shadowStrength": 0.6,
                        "offsetPct": 12,
                        "animationMs": 260,
                    },
                },
            )
            style_update = json.loads(websocket.receive_text())

        api_payload = client.get("/api/config")

    assert initial["type"] == "style"
    assert response.json()["overlay"]["fontSize"] == 44
    assert style_update["type"] == "style"
    assert style_update["style"]["fontFamily"] == "Studio Font"
    assert api_payload.json()["overlay"]["radiusPx"] == 36
    assert config_path.exists()


def test_app_websocket_receives_initial_state_and_subtitle_events(tmp_path: Path) -> None:
    server = make_server(tmp_path / "config.toml")
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws/app") as websocket:
            state_event = json.loads(websocket.receive_text())
            style_event = json.loads(websocket.receive_text())
            asyncio.run(server.broadcast("hello"))
            subtitle_event = json.loads(websocket.receive_text())

    assert state_event["type"] == "state"
    assert state_event["state"]["status"] == "idle"
    assert style_event["type"] == "style"
    assert subtitle_event == {"type": "subtitle", "text": "hello"}


def test_overlay_websocket_receives_broadcast_and_prunes_dead_connections(tmp_path: Path) -> None:
    server = make_server(tmp_path / "config.toml")
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws") as websocket:
            style_event = json.loads(websocket.receive_text())
            asyncio.run(server.broadcast("overlay text"))
            subtitle_event = json.loads(websocket.receive_text())

    assert style_event["type"] == "style"
    assert subtitle_event == {"type": "subtitle", "text": "overlay text"}
