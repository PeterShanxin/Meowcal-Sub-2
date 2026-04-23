import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from meocosub2.config import AppConfig
from meocosub2.overlay.server import OverlayServer


def make_server(config_path: Path | None = None) -> OverlayServer:
    return OverlayServer(
        AppConfig(
            opensubtitles_enabled=True,
            opensubtitles_api_key="test-key",
            opensubtitles_enable_org_fallback=True,
            subdl_enabled=True,
            assrt_enabled=True,
            assrt_token="assrt-token",
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


def test_dashboard_root_is_served(tmp_path: Path) -> None:
    server = make_server(tmp_path / "config.toml")
    with TestClient(server.app) as client:
        dashboard = client.get("/")
    assert dashboard.status_code == 200
    # Vite bundle mounts a root element; legacy DOM-ID assertions are gone with
    # the command-palette redesign. Keep this shallow so we don't couple to the
    # React bundle content.
    assert "<div id=\"root\"" in dashboard.text or "<div id='root'" in dashboard.text


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
    assert api_payload.json()["subtitleSources"]["subdl"]["enabled"] is True
    assert api_payload.json()["subtitleSources"]["assrt"]["token"] == "assrt-token"


def test_put_config_updates_api_payload_and_persists_style(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    server = make_server(config_path)
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws/app") as websocket:
            # Drain initial state frame, then style frame.
            _ = json.loads(websocket.receive_text())
            initial = json.loads(websocket.receive_text())
            response = client.put(
                "/api/config",
                json={
                    "subtitleSources": {
                        "opensubtitles": {"enabled": True, "apiKey": "key", "enableOrgFallback": False},
                        "subdl": {"enabled": False},
                        "assrt": {"enabled": True, "token": "fresh-assrt-token"},
                    },
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
            style_update = None
            for _ in range(4):
                event = json.loads(websocket.receive_text())
                if event.get("type") == "style":
                    style_update = event
                    break
            assert style_update is not None, "expected a style event after config PUT"

        api_payload = client.get("/api/config")

    assert initial["type"] == "style"
    assert response.json()["overlay"]["fontSize"] == 44
    assert response.json()["subtitleSources"]["subdl"]["enabled"] is False
    assert response.json()["subtitleSources"]["assrt"]["token"] == "fresh-assrt-token"
    assert style_update["type"] == "style"
    assert style_update["style"]["fontFamily"] == "Studio Font"
    assert api_payload.json()["overlay"]["radiusPx"] == 36
    assert api_payload.json()["subtitleSources"]["opensubtitles"]["apiKey"] == "key"
    assert config_path.exists()


def test_put_config_with_language_only_merge_persists_languages_without_resetting_other_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    server = make_server(config_path)
    with TestClient(server.app) as client:
        initial_payload = client.get("/api/config").json()
        response = client.put(
            "/api/config",
            json={
                **initial_payload,
                "languages": {"source": "ja", "target": "fr"},
                "capture": {
                    **initial_payload["capture"],
                    "ocrLanguage": "ja-JP",
                },
            },
        )
        api_payload = client.get("/api/config")

    saved = response.json()
    assert saved["languages"] == {"source": "ja", "target": "fr"}
    assert saved["capture"]["ocrLanguage"] == "ja-JP"
    assert saved["subtitleSources"]["opensubtitles"]["apiKey"] == "test-key"
    assert saved["overlay"]["fontFamily"] == "Test Font"
    assert api_payload.json()["languages"] == {"source": "ja", "target": "fr"}
    assert config_path.exists()
    assert 'source = "ja"' in config_path.read_text(encoding="utf-8")
    assert 'target = "fr"' in config_path.read_text(encoding="utf-8")


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


