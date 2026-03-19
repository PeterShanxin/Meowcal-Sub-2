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
    assert "What do you want to watch?" in dashboard.text
    assert 'id="loading-overlay"' in dashboard.text
    assert 'id="loading-retry"' in dashboard.text
    assert 'id="settings-open-button"' in dashboard.text
    assert 'id="settings-drawer"' in dashboard.text
    assert 'id="settings-close-button"' in dashboard.text
    assert 'id="settings-inline-button"' in dashboard.text
    assert 'id="source-language-picker"' in dashboard.text
    assert 'id="target-language-picker"' in dashboard.text
    assert 'id="source-language-options"' in dashboard.text
    assert 'id="target-language-options"' in dashboard.text
    assert 'id="source-language-trigger" class="language-trigger hidden"' not in dashboard.text
    assert 'id="target-language-trigger" class="language-trigger hidden"' not in dashboard.text
    assert 'id="source-language-input" class="native-language-select" name="sourceLanguage" tabindex="-1" aria-hidden="true"' in dashboard.text
    assert 'id="target-language-input" class="native-language-select" name="targetLanguage" tabindex="-1" aria-hidden="true"' in dashboard.text
    assert 'id="language-menu-portal"' not in dashboard.text
    assert 'id="language-menu-panel"' not in dashboard.text
    assert "custom-select" not in dashboard.text
    assert overlay.status_code == 200
    assert "subtitle-shell" in overlay.text


def test_dashboard_script_uses_blocking_bootstrap_without_custom_selects(tmp_path: Path) -> None:
    server = make_server(tmp_path / "config.toml")
    with TestClient(server.app) as client:
        script = client.get("/static/app.js")

    assert script.status_code == 200
    assert "Language options failed to load. Retry startup." in script.text
    assert "Studio startup incomplete" in script.text
    assert script.text.count('setBootstrapLoading("Loading studio...", "Preparing languages and saved settings.");') == 1
    assert "openLanguagePicker" in script.text
    assert "closeLanguagePicker" in script.text
    assert "setSettingsDrawerOpen" in script.text
    assert "languageMenuPortal" not in script.text
    assert "languageMenuPanel" not in script.text
    assert "positionLanguageMenuPanel" not in script.text
    assert "showModal()" not in script.text
    assert "languageMenuDialog" not in script.text
    assert "wrapSelect(" not in script.text
    assert "custom-select" not in script.text


def test_dashboard_styles_use_inline_language_picker_layout(tmp_path: Path) -> None:
    server = make_server(tmp_path / "config.toml")
    with TestClient(server.app) as client:
        styles = client.get("/static/app.css")

    assert styles.status_code == 200
    assert ".language-picker {" in styles.text
    assert ".language-picker-options {" in styles.text
    assert ".language-picker-option" in styles.text
    assert ".language-field.is-open .language-trigger" in styles.text
    assert "clip-path: inset(50%)" in styles.text
    assert ".hero-shell {" in styles.text
    assert ".settings-drawer {" in styles.text
    assert ".result-card.selected {" in styles.text
    assert ".language-trigger,\n.language-picker {" not in styles.text
    assert ".language-menu-portal" not in styles.text
    assert ".language-menu-panel" not in styles.text


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
