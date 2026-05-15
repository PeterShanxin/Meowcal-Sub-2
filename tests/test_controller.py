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
async def test_prepare_auto_candidate_session_downloads_top_sources_and_best_target(tmp_path: Path, mocker) -> None:
    controller = make_controller(tmp_path / "config.toml")
    source_a = tmp_path / "source-a.srt"
    source_a.write_text("1\n00:00:01,000 --> 00:00:02,000\nhello there\n", encoding="utf-8")
    source_b = tmp_path / "source-b.srt"
    source_b.write_text("1\n00:00:01,000 --> 00:00:02,000\nhello again\n", encoding="utf-8")
    target = tmp_path / "target.srt"
    target.write_text("1\n00:00:01,000 --> 00:00:02,000\n你好\n", encoding="utf-8")

    controller._search_catalog = AggregatedSearchCatalog(
        matches=[
            AggregatedTitleMatch(
                id="match-1",
                title="Fate/strange Fake",
                year=2024,
                imdb_id=None,
                tmdb_id=None,
                media_type="episode",
                season=1,
                episode=1,
                parent_title="Fate/strange Fake",
                subtitles_count=3,
                match_score=250,
                provider_count=2,
                providers=("subdl", "opensubtitles"),
                provider_labels=("SubDL", "OpenSubtitles"),
            )
        ],
        results=[
            AggregatedSubtitleResult(
                result_id="source-a",
                match_id="match-1",
                provider="subdl",
                provider_label="SubDL",
                title="Episode 1",
                year=2024,
                imdb_id=None,
                tmdb_id=None,
                media_type="episode",
                season=1,
                episode=1,
                parent_title="Fate/strange Fake",
                language="zht",
                download_count=50,
                file_name="source-a.srt",
                provider_rank=0,
                provider_result=object(),
            ),
            AggregatedSubtitleResult(
                result_id="source-b",
                match_id="match-1",
                provider="opensubtitles",
                provider_label="OpenSubtitles",
                title="Episode 1",
                year=2024,
                imdb_id=None,
                tmdb_id=None,
                media_type="episode",
                season=1,
                episode=1,
                parent_title="Fate/strange Fake",
                language="zh",
                download_count=40,
                file_name="source-b.srt",
                provider_rank=2,
                provider_result=object(),
            ),
            AggregatedSubtitleResult(
                result_id="target",
                match_id="match-1",
                provider="subdl",
                provider_label="SubDL",
                title="Episode 1",
                year=2024,
                imdb_id=None,
                tmdb_id=None,
                media_type="episode",
                season=1,
                episode=1,
                parent_title="Fate/strange Fake",
                language="en",
                download_count=70,
                file_name="target.srt",
                provider_rank=0,
                provider_result=object(),
            ),
        ],
    )
    controller._state.title = "Fate/strange Fake"
    controller._state.source_language = "zht"
    controller._state.target_language = "en"
    controller._state.search_matches = [{"id": "match-1", "title": "Fate/strange Fake", "mediaType": "episode"}]
    download = mocker.patch.object(controller._aggregator, "download", side_effect=[source_a, source_b, target])

    payload = await controller.prepare_session(mode="auto_candidates", feature_id="match-1")

    assert payload["session_mode"] == "auto_candidates"
    assert payload["target_match_mode"] == "auto_subtitle_file"
    assert payload["source_candidate_count"] == 2
    assert payload["target_candidate_count"] == 1
    assert payload["source_file_id"] is None
    assert payload["source_file_name"] is None
    assert payload["source_summary"] == "2 source candidates"
    assert payload["target_file_id"] == "target"
    assert controller._prepared_runtime is not None
    assert len(controller._prepared_runtime.source_candidates) == 2
    assert download.await_count == 3


@pytest.mark.asyncio
async def test_prepare_auto_candidate_session_combines_source_and_target_warnings(tmp_path: Path, mocker) -> None:
    controller = make_controller(tmp_path / "config.toml")
    mocker.patch(
        "meocosub2.overlay.controller.make_foundry_ready",
        return_value=type("Status", (), {"phase": "ready", "notes": "Ready."})(),
    )
    source_path = tmp_path / "source.srt"
    source_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nhello there\n", encoding="utf-8")
    controller._search_catalog = AggregatedSearchCatalog(
        matches=[
            AggregatedTitleMatch(
                id="match-1",
                title="Fate/strange Fake",
                year=2024,
                imdb_id=None,
                tmdb_id=None,
                media_type="episode",
                subtitles_count=1,
                match_score=250,
                provider_count=1,
                providers=("subdl",),
                provider_labels=("SubDL",),
            )
        ],
        results=[
            AggregatedSubtitleResult(
                result_id="source-zh",
                match_id="match-1",
                provider="subdl",
                provider_label="SubDL",
                title="Episode 1",
                year=2024,
                imdb_id=None,
                tmdb_id=None,
                media_type="episode",
                language="zh",
                download_count=50,
                file_name="source.srt",
                provider_rank=0,
                provider_result=object(),
            ),
        ],
    )
    controller._state.title = "Fate/strange Fake"
    controller._state.source_language = "zht"
    controller._state.target_language = "en"
    controller._state.search_matches = [{"id": "match-1", "title": "Fate/strange Fake", "mediaType": "episode"}]
    mocker.patch.object(controller._aggregator, "download", return_value=source_path)

    await controller.prepare_session(mode="auto_candidates", feature_id="match-1")

    warning = controller.state_snapshot()["warning_message"]
    assert "Chinese-family source subtitle candidates" in warning
    assert "No target subtitle matched" in warning


@pytest.mark.asyncio
async def test_prepare_auto_candidate_session_ignores_stale_completion(tmp_path: Path, mocker) -> None:
    controller = make_controller(tmp_path / "config.toml")
    mocker.patch(
        "meocosub2.overlay.controller.make_foundry_ready",
        return_value=type("Status", (), {"phase": "ready", "notes": "Ready."})(),
    )
    source_path = tmp_path / "source.srt"
    source_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nhello there\n", encoding="utf-8")
    controller._search_catalog = AggregatedSearchCatalog(
        matches=[
            AggregatedTitleMatch(
                id="match-old",
                title="Old",
                year=2024,
                imdb_id=None,
                tmdb_id=None,
                media_type="episode",
                subtitles_count=1,
                match_score=250,
                provider_count=1,
                providers=("subdl",),
                provider_labels=("SubDL",),
            ),
            AggregatedTitleMatch(
                id="match-new",
                title="New",
                year=2024,
                imdb_id=None,
                tmdb_id=None,
                media_type="episode",
                subtitles_count=1,
                match_score=250,
                provider_count=1,
                providers=("subdl",),
                provider_labels=("SubDL",),
            ),
        ],
        results=[
            AggregatedSubtitleResult(
                result_id="source-old",
                match_id="match-old",
                provider="subdl",
                provider_label="SubDL",
                title="Old",
                year=2024,
                imdb_id=None,
                tmdb_id=None,
                media_type="episode",
                language="en",
                download_count=50,
                file_name="source.srt",
                provider_rank=0,
                provider_result=object(),
            ),
        ],
    )
    controller._state.title = "Fate/strange Fake"
    controller._state.source_language = "en"
    controller._state.target_language = "zh"
    controller._state.search_matches = [
        {"id": "match-old", "title": "Old", "mediaType": "episode"},
        {"id": "match-new", "title": "New", "mediaType": "episode"},
    ]
    mocker.patch.object(controller._aggregator, "download", return_value=source_path)
    original_set_progress = controller._set_progress

    async def switch_selection_once(stage: str, message: str, current: int, total: int) -> None:
        await original_set_progress(stage, message, current, total)
        controller._state.selected_feature_id = "match-new"

    mocker.patch.object(controller, "_set_progress", side_effect=switch_selection_once)

    payload = await controller.prepare_session(mode="auto_candidates", feature_id="match-old")

    assert payload["feature_id"] == "match-old"
    assert controller.state_snapshot()["selected_feature_id"] == "match-new"
    assert controller.state_snapshot()["prepared_session"] is None
    assert controller._prepared_runtime is None


def test_auto_candidate_ranking_prefers_exact_language_before_family_fallback(tmp_path: Path) -> None:
    controller = make_controller(tmp_path / "config.toml")
    controller._search_catalog = AggregatedSearchCatalog(
        matches=[],
        results=[
            AggregatedSubtitleResult(
                result_id="fallback-zh",
                match_id="match-1",
                provider="subdl",
                provider_label="SubDL",
                title="Episode 1",
                year=2024,
                imdb_id=None,
                tmdb_id=None,
                media_type="episode",
                language="zh",
                download_count=100,
                file_name="fallback.srt",
                provider_rank=0,
                provider_result=object(),
            ),
            AggregatedSubtitleResult(
                result_id="exact-zht",
                match_id="match-1",
                provider="opensubtitles",
                provider_label="OpenSubtitles",
                title="Episode 1",
                year=2024,
                imdb_id=None,
                tmdb_id=None,
                media_type="episode",
                language="zht",
                download_count=1,
                file_name="exact.srt",
                provider_rank=2,
                provider_result=object(),
            ),
        ],
    )

    candidates = controller._candidate_results_for_feature("match-1", "zht", 1)

    assert [item.result_id for item in candidates] == ["exact-zht"]


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


@pytest.mark.asyncio
async def test_save_config_payload_updates_state_languages_and_persists_file(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    controller = make_controller(config_path)

    payload = await controller.save_config_payload(
        {
            "subtitleSources": {
                "opensubtitles": {"enabled": True, "apiKey": "", "username": "", "password": "", "enableOrgFallback": False},
                "subdl": {"enabled": True},
                "assrt": {"enabled": False, "token": ""},
            },
            "languages": {"source": "ja", "target": "fr"},
            "capture": {"region": [], "intervalMs": 1500, "ocrLanguage": "ja-JP"},
            "matching": {"fuzzyThreshold": 65, "windowSize": 30},
            "translation": {"endpoint": "http://127.0.0.1:5273/v1", "model": "manual-model", "timeoutS": 30, "batchSize": 5},
            "overlay": {
                "port": 8765,
                "theme": "glass-cinematic",
                "fontSize": 28,
                "fontFamily": "Aptos",
                "textColor": "#FFFFFF",
                "bgColor": "rgba(0,0,0,0.75)",
                "position": "bottom",
                "radiusPx": 28,
                "paddingPx": 20,
                "maxWidthVw": 78,
                "blurPx": 20,
                "shadowStrength": 0.45,
                "offsetPct": 10,
                "animationMs": 220,
            },
            "debug": {"mode": False},
        }
    )

    assert payload["languages"] == {"source": "ja", "target": "fr"}
    assert controller.state_snapshot()["source_language"] == "ja"
    assert controller.state_snapshot()["target_language"] == "fr"
    assert config_path.exists()
    saved_text = config_path.read_text(encoding="utf-8")
    assert 'source = "ja"' in saved_text
    assert 'target = "fr"' in saved_text
