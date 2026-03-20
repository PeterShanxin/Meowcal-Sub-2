from pathlib import Path

import pytest

from meocosub2.config import AppConfig
from meocosub2.overlay.controller import GuiController


async def _emit(*args, **kwargs) -> None:
    return None


def make_controller(config_path: Path | None = None) -> GuiController:
    return GuiController(AppConfig(foundry_model="manual-model"), _emit, _emit, config_path=config_path)


@pytest.mark.asyncio
async def test_prepare_session_allows_ocr_fallback_without_source_subtitle(tmp_path: Path, mocker) -> None:
    controller = make_controller(tmp_path / "config.toml")
    mocker.patch(
        "meocosub2.overlay.controller.make_foundry_ready",
        return_value=type("Status", (), {"phase": "ready", "notes": "Ready."})(),
    )
    controller._state.title = "Fate/strange Fake"
    controller._state.source_language = "zht"
    controller._state.target_language = "en"
    controller._state.search_matches = [
        {
            "id": 2239923,
            "title": "Fate/strange Fake",
            "mediaType": "tvshow",
            "matchScore": 240.0,
        }
    ]
    controller._state.search_results = []

    payload = await controller.prepare_session(mode="ocr_fallback", feature_id=2239923)

    assert payload["session_mode"] == "ocr_fallback"
    assert payload["source_file_id"] is None
    assert payload["target_match_mode"] == "direct_translation"
    assert controller.state_snapshot()["selected_feature_id"] == 2239923


@pytest.mark.asyncio
async def test_install_ocr_language_reports_failure_when_language_stays_unavailable(tmp_path: Path, mocker) -> None:
    controller = make_controller(tmp_path / "config.toml")
    mocker.patch("meocosub2.overlay.controller.subprocess.run")
    mocker.patch("meocosub2.overlay.controller.available_ocr_languages", side_effect=[["en-US"], ["en-US"]])

    payload = await controller.install_ocr_language("zh-TW")

    assert payload["requested"] == "zh-TW"
    assert payload["installed"] is False
    assert payload["supported"] is False
    assert "not available" in payload["message"].lower()
