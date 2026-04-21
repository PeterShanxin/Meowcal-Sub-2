from pathlib import Path

import pytest

from meocosub2.config import AppConfig
from meocosub2.models import SearchRequest
from meocosub2.overlay.controller import GuiController
from meocosub2.subtitle_sources.types import AggregatedSearchCatalog, AggregatedSubtitleResult, AggregatedTitleMatch


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


@pytest.mark.asyncio
async def test_prepare_session_downloads_non_opensubtitles_result(tmp_path: Path, mocker) -> None:
    controller = make_controller(tmp_path / "config.toml")
    mocker.patch(
        "meocosub2.overlay.controller.make_foundry_ready",
        return_value=type("Status", (), {"phase": "ready", "notes": "Ready."})(),
    )
    source_path = tmp_path / "source.srt"
    source_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nhello\n", encoding="utf-8")
    target_path = tmp_path / "target.srt"
    target_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nworld\n", encoding="utf-8")

    controller._search_catalog = AggregatedSearchCatalog(
        matches=[
            AggregatedTitleMatch(
                id="match-1",
                title="Fate/strange Fake",
                year=2024,
                imdb_id=None,
                tmdb_id=None,
                media_type="tvshow",
                subtitles_count=2,
                match_score=250,
                provider_count=2,
                providers=("subdl", "opensubtitles"),
                provider_labels=("SubDL", "OpenSubtitles"),
            )
        ],
        results=[
            AggregatedSubtitleResult(
                result_id="result-1",
                match_id="match-1",
                provider="subdl",
                provider_label="SubDL",
                title="The Heroic Spirit Incident",
                year=2024,
                imdb_id=None,
                tmdb_id=None,
                media_type="episode",
                season=1,
                episode=1,
                parent_title="Fate/strange Fake",
                language="zht",
                download_count=20,
                file_name="source.srt",
                provider_result=object(),
            ),
            AggregatedSubtitleResult(
                result_id="result-2",
                match_id="match-1",
                provider="opensubtitles",
                provider_label="OpenSubtitles",
                title="The Heroic Spirit Incident",
                year=2024,
                imdb_id=None,
                tmdb_id=None,
                media_type="episode",
                season=1,
                episode=1,
                parent_title="Fate/strange Fake",
                language="en",
                download_count=30,
                file_name="target.srt",
                provider_result=object(),
            ),
        ],
    )
    controller._state.title = "Fate/strange Fake"
    controller._state.source_language = "zht"
    controller._state.target_language = "en"
    controller._state.search_matches = [{"id": "match-1", "title": "Fate/strange Fake", "mediaType": "tvshow"}]
    controller._state.search_results = [
        {"id": "result-1", "resultId": "result-1", "matchId": "match-1", "provider": "subdl", "providerLabel": "SubDL", "language": "zht", "fileName": "source.srt"},
        {"id": "result-2", "resultId": "result-2", "matchId": "match-1", "provider": "opensubtitles", "providerLabel": "OpenSubtitles", "language": "en", "fileName": "target.srt"},
    ]
    download = mocker.patch.object(
        controller._aggregator,
        "download",
        side_effect=[source_path, target_path],
    )

    payload = await controller.prepare_session(mode="subtitle_pair", feature_id="match-1", source_file_id="result-1", target_file_id="result-2")

    assert payload["session_mode"] == "subtitle_pair"
    assert payload["source_provider"] == "SubDL"
    assert payload["target_provider"] == "OpenSubtitles"
    assert payload["source_file_id"] == "result-1"
    assert payload["target_file_id"] == "result-2"
    assert download.await_count == 2


@pytest.mark.asyncio
async def test_search_warning_message_highlights_thin_chinese_coverage_when_assrt_disabled(tmp_path: Path, mocker) -> None:
    controller = make_controller(tmp_path / "config.toml")
    mocker.patch.object(
        controller._aggregator,
        "search_catalog",
        return_value=AggregatedSearchCatalog(
            matches=[],
            results=[],
            warnings=["ASSRT is disabled."],
        ),
    )

    await controller.search(SearchRequest(title="Overlord", source_language="zh", target_language="en"))

    assert controller.state_snapshot()["warning_message"] == "ASSRT is disabled, so Chinese subtitle coverage may be thin."


@pytest.mark.asyncio
async def test_search_warning_message_keeps_generic_assrt_disabled_warning_for_non_chinese_search(tmp_path: Path, mocker) -> None:
    controller = make_controller(tmp_path / "config.toml")
    mocker.patch.object(
        controller._aggregator,
        "search_catalog",
        return_value=AggregatedSearchCatalog(
            matches=[],
            results=[],
            warnings=["ASSRT is disabled."],
        ),
    )

    await controller.search(SearchRequest(title="Overlord", source_language="en", target_language="fr"))

    assert controller.state_snapshot()["warning_message"] == "ASSRT is disabled."
