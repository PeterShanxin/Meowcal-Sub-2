from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from meocosub2.config import AppConfig
from meocosub2.engine import EngineInstallError
from meocosub2.errors import TranslationError
from meocosub2.models import PreparedRuntime, SearchRequest
from meocosub2.overlay.controller import GuiController
from meocosub2.subtitle_sources.types import (
    AggregatedEpisode,
    AggregatedSearchCatalog,
    AggregatedSeason,
    AggregatedSubtitleResult,
    AggregatedTitleMatch,
    AggregatedWork,
    ProviderSubtitleResult,
)


async def _emit(*args, **kwargs) -> None:
    return None


def make_controller(config_path: Path | None = None) -> GuiController:
    return GuiController(AppConfig(), _emit, config_path=config_path)


@pytest.mark.asyncio
async def test_prepare_session_allows_ocr_fallback_without_source_subtitle(
    tmp_path: Path, mocker
) -> None:
    controller = make_controller(tmp_path / "config.toml")
    mocker.patch(
        "meocosub2.overlay.controller.engine.ensure_ready",
        new=AsyncMock(return_value="http://127.0.0.1:11436"),
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
async def test_install_ocr_language_reports_failure_when_language_stays_unavailable(
    tmp_path: Path, mocker
) -> None:
    controller = make_controller(tmp_path / "config.toml")
    mocker.patch("meocosub2.overlay.controller.subprocess.run")
    mocker.patch(
        "meocosub2.overlay.controller.available_ocr_languages", side_effect=[["en-US"], ["en-US"]]
    )

    payload = await controller.install_ocr_language("zh-TW")

    assert payload["requested"] == "zh-TW"
    assert payload["installed"] is False
    assert payload["supported"] is False
    assert "not available" in payload["message"].lower()


def _pair_controller(tmp_path: Path, mocker) -> tuple[GuiController, AsyncMock, AsyncMock]:
    """A controller ready to prepare a source/target subtitle pair.

    Returns it with the patched engine start and the patched download, so a
    test can assert on either without rebuilding the catalog.
    """
    controller = make_controller(tmp_path / "config.toml")
    warm = mocker.patch(
        "meocosub2.overlay.controller.engine.ensure_ready",
        new=AsyncMock(return_value="http://127.0.0.1:11436"),
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
    controller._state.search_matches = [
        {"id": "match-1", "title": "Fate/strange Fake", "mediaType": "tvshow"}
    ]
    controller._state.search_results = [
        {
            "id": "result-1",
            "resultId": "result-1",
            "matchId": "match-1",
            "provider": "subdl",
            "providerLabel": "SubDL",
            "language": "zht",
            "fileName": "source.srt",
        },
        {
            "id": "result-2",
            "resultId": "result-2",
            "matchId": "match-1",
            "provider": "opensubtitles",
            "providerLabel": "OpenSubtitles",
            "language": "en",
            "fileName": "target.srt",
        },
    ]
    download = mocker.patch.object(
        controller._aggregator,
        "download",
        side_effect=[source_path, target_path],
    )
    return controller, warm, download


@pytest.mark.asyncio
async def test_prepare_session_downloads_non_opensubtitles_result(tmp_path: Path, mocker) -> None:
    controller, _, download = _pair_controller(tmp_path, mocker)

    payload = await controller.prepare_session(
        mode="subtitle_pair",
        feature_id="match-1",
        source_file_id="result-1",
        target_file_id="result-2",
    )

    assert payload["session_mode"] == "subtitle_pair"
    assert payload["source_provider"] == "SubDL"
    assert payload["target_provider"] == "OpenSubtitles"
    assert payload["source_file_id"] == "result-1"
    assert payload["target_file_id"] == "result-2"
    assert download.await_count == 2


@pytest.mark.asyncio
async def test_preparing_a_pair_starts_the_engine_the_opening_lines_need(
    tmp_path: Path, mocker
) -> None:
    """The model answers until a match anchors the clock, target file or not."""
    controller, warm, _ = _pair_controller(tmp_path, mocker)

    await controller.prepare_session(
        mode="subtitle_pair",
        feature_id="match-1",
        source_file_id="result-1",
        target_file_id="result-2",
    )

    assert warm.await_count == 1


@pytest.mark.asyncio
async def test_a_pair_with_a_target_file_prepares_without_the_translation_engine(
    tmp_path: Path, mocker
) -> None:
    """The file carries the session, so a missing engine costs lines, not the session.

    Only the opening lines and the cues the target file has no answer for want
    the model. Refusing to prepare over those would take a session that plays
    away from every viewer who has not downloaded the engine.
    """
    controller, warm, _ = _pair_controller(tmp_path, mocker)
    warm.side_effect = EngineInstallError("Local translation is not installed yet.")

    payload = await controller.prepare_session(
        mode="subtitle_pair",
        feature_id="match-1",
        source_file_id="result-1",
        target_file_id="result-2",
    )

    assert payload["session_mode"] == "subtitle_pair"
    assert "not installed" in controller.state_snapshot()["warning_message"]


@pytest.mark.asyncio
async def test_a_pair_without_a_target_file_will_not_prepare_without_the_engine(
    tmp_path: Path, mocker
) -> None:
    """With no target file the model is the only answer, so the failure stands."""
    controller, warm, _ = _pair_controller(tmp_path, mocker)
    warm.side_effect = EngineInstallError("Local translation is not installed yet.")

    with pytest.raises(TranslationError):
        await controller.prepare_session(
            mode="subtitle_pair",
            feature_id="match-1",
            source_file_id="result-1",
            target_file_id=None,
        )


@pytest.mark.asyncio
async def test_prepare_auto_candidate_session_downloads_top_sources_and_best_target(
    tmp_path: Path, mocker
) -> None:
    controller = make_controller(tmp_path / "config.toml")
    mocker.patch(
        "meocosub2.overlay.controller.engine.ensure_ready",
        new=AsyncMock(return_value="http://127.0.0.1:11436"),
    )
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
    controller._state.search_matches = [
        {"id": "match-1", "title": "Fate/strange Fake", "mediaType": "episode"}
    ]
    download = mocker.patch.object(
        controller._aggregator, "download", side_effect=[source_a, source_b, target]
    )

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
async def test_prepare_auto_candidate_session_combines_source_and_target_warnings(
    tmp_path: Path, mocker
) -> None:
    controller = make_controller(tmp_path / "config.toml")
    mocker.patch(
        "meocosub2.overlay.controller.engine.ensure_ready",
        new=AsyncMock(return_value="http://127.0.0.1:11436"),
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
    controller._state.search_matches = [
        {"id": "match-1", "title": "Fate/strange Fake", "mediaType": "episode"}
    ]
    mocker.patch.object(controller._aggregator, "download", return_value=source_path)

    await controller.prepare_session(mode="auto_candidates", feature_id="match-1")

    warning = controller.state_snapshot()["warning_message"]
    assert "Chinese-family source subtitle candidates" in warning
    assert "No target subtitle matched" in warning


@pytest.mark.asyncio
async def test_prepare_auto_candidate_session_ignores_stale_completion(
    tmp_path: Path, mocker
) -> None:
    controller = make_controller(tmp_path / "config.toml")
    mocker.patch(
        "meocosub2.overlay.controller.engine.ensure_ready",
        new=AsyncMock(return_value="http://127.0.0.1:11436"),
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

    with pytest.raises(RuntimeError, match="Stale auto-prepare result"):
        await controller.prepare_session(mode="auto_candidates", feature_id="match-old")

    assert controller.state_snapshot()["selected_feature_id"] == "match-new"
    assert controller.state_snapshot()["prepared_session"] is None
    assert controller._prepared_runtime is None


def test_auto_candidate_ranking_prefers_exact_language_before_family_fallback(
    tmp_path: Path,
) -> None:
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
async def test_search_warning_message_highlights_thin_chinese_coverage_when_assrt_disabled(
    tmp_path: Path, mocker
) -> None:
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

    await controller.search(
        SearchRequest(title="Overlord", source_language="zh", target_language="en")
    )

    assert (
        controller.state_snapshot()["warning_message"]
        == "ASSRT is disabled, so Chinese subtitle coverage may be thin."
    )


@pytest.mark.asyncio
async def test_search_warning_message_keeps_generic_assrt_disabled_warning_for_non_chinese_search(
    tmp_path: Path, mocker
) -> None:
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

    await controller.search(
        SearchRequest(title="Overlord", source_language="en", target_language="fr")
    )

    assert controller.state_snapshot()["warning_message"] == "ASSRT is disabled."


@pytest.mark.asyncio
async def test_hydrate_episode_replaces_skeleton_with_clickable_results(
    tmp_path: Path, mocker
) -> None:
    controller = make_controller(tmp_path / "config.toml")
    controller._state.title = "From"
    controller._state.source_language = "en"
    controller._state.target_language = "zht"
    controller._search_catalog = AggregatedSearchCatalog(
        matches=[
            AggregatedTitleMatch(
                id="match-other-from",
                title="From.S04E06",
                year=2025,
                imdb_id=None,
                tmdb_id=None,
                media_type="episode",
                season=4,
                episode=6,
                parent_title="From",
                subtitles_count=1,
                match_score=80,
                provider_count=1,
                providers=("opensubtitles",),
                provider_labels=("OpenSubtitles",),
            )
        ],
        results=[],
        works=[
            AggregatedWork(
                id="work-1",
                title="From",
                media_type="series",
                year=2022,
                year_end=2025,
                imdb_id=None,
                tmdb_id=None,
                providers=("opensubtitles",),
                provider_labels=("OpenSubtitles",),
                seasons=[
                    AggregatedSeason(
                        season_number=4,
                        subtitles_count=0,
                        episodes=[
                            AggregatedEpisode(
                                season=4,
                                episode=6,
                                title="Scar Tissue",
                                match_id="skeleton:4:6",
                                subtitles_count=0,
                            ),
                            AggregatedEpisode(
                                season=4,
                                episode=7,
                                title="Promised You a Miracle",
                                match_id="skeleton:4:7",
                                subtitles_count=0,
                            ),
                        ],
                    )
                ],
            )
        ],
    )
    controller._state.search_works = [controller._search_catalog.works[0]]
    exact_catalog = AggregatedSearchCatalog(
        matches=[
            AggregatedTitleMatch(
                id="match-1",
                title="From.S04E06",
                year=2025,
                imdb_id=None,
                tmdb_id=None,
                media_type="episode",
                season=4,
                episode=6,
                parent_title="From",
                subtitles_count=2,
                match_score=120,
                provider_count=1,
                providers=("opensubtitles",),
                provider_labels=("OpenSubtitles",),
            )
        ],
        results=[
            AggregatedSubtitleResult(
                result_id="result-1",
                match_id="match-1",
                provider="opensubtitles",
                provider_label="OpenSubtitles",
                title="From.S04E06",
                year=2025,
                imdb_id=None,
                media_type="episode",
                season=4,
                episode=6,
                parent_title="From",
                language="en",
                download_count=10,
                file_name="From.S04E06.en.srt",
                match_score=120,
                provider_rank=2,
                provider_result=ProviderSubtitleResult(
                    id="os-result-1",
                    match_id="os-match-1",
                    provider="opensubtitles",
                    provider_label="OpenSubtitles",
                    title="From.S04E06",
                    year=2025,
                    imdb_id=None,
                    media_type="episode",
                    season=4,
                    episode=6,
                    parent_title="From",
                    language="en",
                    download_count=10,
                    file_name="From.S04E06.en.srt",
                ),
            ),
            AggregatedSubtitleResult(
                result_id="result-2",
                match_id="match-2",
                provider="opensubtitles",
                provider_label="OpenSubtitles",
                title="Other Show.S04E06",
                year=2025,
                imdb_id=None,
                media_type="episode",
                season=4,
                episode=6,
                parent_title="Other Show",
                language="en",
                download_count=50,
                file_name="Other.Show.S04E06.en.srt",
                match_score=125,
                provider_rank=1,
                provider_result=ProviderSubtitleResult(
                    id="os-result-2",
                    match_id="os-match-2",
                    provider="opensubtitles",
                    provider_label="OpenSubtitles",
                    title="Other Show.S04E06",
                    year=2025,
                    imdb_id=None,
                    media_type="episode",
                    season=4,
                    episode=6,
                    parent_title="Other Show",
                    language="en",
                    download_count=50,
                    file_name="Other.Show.S04E06.en.srt",
                ),
            ),
        ],
    )
    season_catalog = AggregatedSearchCatalog(
        matches=[
            AggregatedTitleMatch(
                id="match-3",
                title="From.S04E07",
                year=2025,
                imdb_id=None,
                tmdb_id=None,
                media_type="episode",
                season=4,
                episode=7,
                parent_title="From",
                subtitles_count=1,
                match_score=115,
                provider_count=1,
                providers=("opensubtitles",),
                provider_labels=("OpenSubtitles",),
            )
        ],
        results=[
            AggregatedSubtitleResult(
                result_id="result-3",
                match_id="match-3",
                provider="opensubtitles",
                provider_label="OpenSubtitles",
                title="From.S04E07",
                year=2025,
                imdb_id=None,
                media_type="episode",
                season=4,
                episode=7,
                parent_title="From",
                language="en",
                download_count=8,
                file_name="From.S04E07.en.srt",
                match_score=115,
                provider_rank=2,
                provider_result=ProviderSubtitleResult(
                    id="os-result-3",
                    match_id="os-match-3",
                    provider="opensubtitles",
                    provider_label="OpenSubtitles",
                    title="From.S04E07",
                    year=2025,
                    imdb_id=None,
                    media_type="episode",
                    season=4,
                    episode=7,
                    parent_title="From",
                    language="en",
                    download_count=8,
                    file_name="From.S04E07.en.srt",
                ),
            )
        ],
    )
    search_mock = mocker.AsyncMock(side_effect=[exact_catalog, season_catalog, exact_catalog])
    mocker.patch.object(controller._aggregator, "search_catalog", new=search_mock)

    payload = await controller.hydrate_episode(work_id="work-1", title="From", season=4, episode=6)

    assert payload["hydrated"] is True
    assert payload["matchId"] == "hydrated:work-1:4:6"
    assert [call.args[0] for call in search_mock.await_args_list[:2]] == ["From S04E06", "From S04"]
    episodes = controller.state_snapshot()["search_works"][0]["seasons"][0]["episodes"]
    episode_6 = next(ep for ep in episodes if ep["episode"] == 6)
    episode_7 = next(ep for ep in episodes if ep["episode"] == 7)
    assert episode_6["matchId"] == "hydrated:work-1:4:6"
    assert episode_6["subtitlesCount"] == 1
    assert episode_7["matchId"] == "hydrated:work-1:4:7"
    assert episode_7["subtitlesCount"] == 1
    assert controller.state_snapshot()["search_results"][0]["matchId"] == "hydrated:work-1:4:6"

    payload = await controller.hydrate_episode(work_id="work-1", title="From", season=4, episode=6)

    assert payload["hydrated"] is True
    assert payload["matchId"] == "hydrated:work-1:4:6"
    assert len(controller.state_snapshot()["search_results"]) == 2


@pytest.mark.asyncio
async def test_hydrate_season_replaces_skeletons_without_selecting_episode(
    tmp_path: Path, mocker
) -> None:
    controller = make_controller(tmp_path / "config.toml")
    controller._state.title = "From"
    controller._state.source_language = "en"
    controller._state.target_language = "zht"
    controller._state.selected_feature_id = "previous-match"
    controller._search_catalog = AggregatedSearchCatalog(
        matches=[],
        results=[],
        works=[
            AggregatedWork(
                id="work-1",
                title="From",
                media_type="series",
                year=2022,
                year_end=2025,
                imdb_id=None,
                tmdb_id=None,
                providers=("subdl",),
                provider_labels=("SubDL",),
                seasons=[
                    AggregatedSeason(
                        season_number=2,
                        subtitles_count=0,
                        episodes=[
                            AggregatedEpisode(
                                season=2, episode=1, title="One", match_id="skeleton:2:1"
                            ),
                            AggregatedEpisode(
                                season=2, episode=2, title="Two", match_id="skeleton:2:2"
                            ),
                        ],
                    )
                ],
            )
        ],
    )
    controller._state.search_works = [controller._search_catalog.works[0]]
    season_catalog = AggregatedSearchCatalog(
        matches=[],
        results=[
            AggregatedSubtitleResult(
                result_id="result-1",
                match_id="match-1",
                provider="subdl",
                provider_label="SubDL",
                title="From.S02E01",
                year=2023,
                imdb_id=None,
                media_type="episode",
                season=2,
                episode=1,
                parent_title="From",
                language="en",
                download_count=10,
                file_name="From.S02E01.en.srt",
                provider_rank=0,
                provider_result=ProviderSubtitleResult(
                    id="subdl-result-1",
                    match_id="subdl-match-1",
                    provider="subdl",
                    provider_label="SubDL",
                    title="From.S02E01",
                    year=2023,
                    imdb_id=None,
                    media_type="episode",
                    season=2,
                    episode=1,
                    parent_title="From",
                    language="en",
                    download_count=10,
                    file_name="From.S02E01.en.srt",
                ),
            ),
            AggregatedSubtitleResult(
                result_id="result-2",
                match_id="match-2",
                provider="subdl",
                provider_label="SubDL",
                title="From.S02E02",
                year=2023,
                imdb_id=None,
                media_type="episode",
                season=2,
                episode=2,
                parent_title="From",
                language="en",
                download_count=8,
                file_name="From.S02E02.en.srt",
                provider_rank=0,
                provider_result=ProviderSubtitleResult(
                    id="subdl-result-2",
                    match_id="subdl-match-2",
                    provider="subdl",
                    provider_label="SubDL",
                    title="From.S02E02",
                    year=2023,
                    imdb_id=None,
                    media_type="episode",
                    season=2,
                    episode=2,
                    parent_title="From",
                    language="en",
                    download_count=8,
                    file_name="From.S02E02.en.srt",
                ),
            ),
        ],
    )
    search_mock = mocker.AsyncMock(return_value=season_catalog)
    mocker.patch.object(controller._aggregator, "search_catalog", new=search_mock)

    payload = await controller.hydrate_season(work_id="work-1", title="From", season=2)

    assert payload["hydrated"] is True
    assert payload["hydratedEpisodes"] == 2
    assert search_mock.await_args.args[:2] == ("From S02", "en,zh,zht")
    assert controller.state_snapshot()["selected_feature_id"] == "previous-match"
    episodes = controller.state_snapshot()["search_works"][0]["seasons"][0]["episodes"]
    assert [ep["matchId"] for ep in episodes] == ["hydrated:work-1:2:1", "hydrated:work-1:2:2"]
    assert [ep["subtitlesCount"] for ep in episodes] == [1, 1]


@pytest.mark.asyncio
async def test_hydrate_season_accepts_matching_tmdb_when_imdb_formats_differ(
    tmp_path: Path, mocker
) -> None:
    controller = make_controller(tmp_path / "config.toml")
    controller._state.title = "From"
    controller._state.source_language = "zh"
    controller._state.target_language = "en"
    controller._search_catalog = AggregatedSearchCatalog(
        matches=[],
        results=[],
        works=[
            AggregatedWork(
                id="work-1",
                title="FROM",
                media_type="series",
                year=2022,
                year_end=2026,
                imdb_id="tt9813792",
                tmdb_id="124364",
                providers=("subdl",),
                provider_labels=("SubDL",),
                seasons=[
                    AggregatedSeason(
                        season_number=1,
                        subtitles_count=0,
                        episodes=[
                            AggregatedEpisode(
                                season=1, episode=1, title="One", match_id="skeleton:1:1"
                            )
                        ],
                    )
                ],
            )
        ],
    )
    controller._state.search_works = [controller._search_catalog.works[0]]
    season_catalog = AggregatedSearchCatalog(
        matches=[],
        results=[
            AggregatedSubtitleResult(
                result_id="result-1",
                match_id="match-1",
                provider="opensubtitles",
                provider_label="OpenSubtitles",
                title="Long Day's Journey Into Night",
                year=2022,
                imdb_id="9813792",
                tmdb_id="124364",
                media_type="episode",
                season=1,
                episode=1,
                parent_title="FROM",
                language="en",
                download_count=10,
                file_name="From.S01E01.en.srt",
                provider_rank=2,
                provider_result=ProviderSubtitleResult(
                    id="os-result-1",
                    match_id="os-match-1",
                    provider="opensubtitles",
                    provider_label="OpenSubtitles",
                    title="Long Day's Journey Into Night",
                    year=2022,
                    imdb_id="9813792",
                    tmdb_id="124364",
                    media_type="episode",
                    season=1,
                    episode=1,
                    parent_title="FROM",
                    language="en",
                    download_count=10,
                    file_name="From.S01E01.en.srt",
                ),
            )
        ],
    )
    mocker.patch.object(
        controller._aggregator, "search_catalog", new=mocker.AsyncMock(return_value=season_catalog)
    )

    payload = await controller.hydrate_season(work_id="work-1", title="FROM", season=1)

    assert payload["hydrated"] is True
    episodes = controller.state_snapshot()["search_works"][0]["seasons"][0]["episodes"]
    assert episodes[0]["matchId"] == "hydrated:work-1:1:1"


@pytest.mark.asyncio
async def test_save_config_payload_updates_state_languages_and_persists_file(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    controller = make_controller(config_path)

    payload = await controller.save_config_payload(
        {
            "subtitleSources": {
                "opensubtitles": {
                    "enabled": True,
                    "apiKey": "",
                    "username": "",
                    "password": "",
                    "enableOrgFallback": False,
                },
                "subdl": {"enabled": True},
                "assrt": {"enabled": False, "token": ""},
            },
            "languages": {"source": "ja", "target": "fr"},
            "capture": {"region": [], "intervalMs": 1500, "ocrLanguage": "ja-JP"},
            "matching": {"fuzzyThreshold": 65, "windowSize": 30},
            "translation": {
                "endpoint": "http://127.0.0.1:5273/v1",
                "model": "manual-model",
                "timeoutS": 30,
                "batchSize": 5,
            },
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


async def test_saving_a_language_change_clears_the_titles_it_invalidates(tmp_path: Path) -> None:
    controller = make_controller(tmp_path / "config.toml")
    controller._search_catalog = AggregatedSearchCatalog(matches=[], results=[])
    controller._state.search_results = [{"resultId": "result-1", "matchId": "match-1"}]
    controller._state.search_matches = [{"matchId": "match-1"}]
    controller._state.search_works = [{"workId": "work-1"}]
    controller._state.selected_feature_id = "match-1"

    await controller.save_config_payload({"languages": {"source": "ja", "target": "en"}})

    assert controller._search_catalog is None
    assert controller._state.search_results == []
    assert controller._state.search_matches == []
    assert controller._state.search_works == []
    assert controller._state.selected_feature_id is None


async def test_saving_an_overlay_change_keeps_the_current_search(tmp_path: Path) -> None:
    controller = make_controller(tmp_path / "config.toml")
    catalog = AggregatedSearchCatalog(matches=[], results=[])
    controller._search_catalog = catalog
    controller._state.search_results = [{"resultId": "result-1", "matchId": "match-1"}]
    controller._state.selected_feature_id = "match-1"

    await controller.save_config_payload({"overlay": {"fontSize": 44}})

    assert controller._search_catalog is catalog
    assert controller._state.search_results
    assert controller._state.selected_feature_id == "match-1"


async def test_preparing_after_the_catalog_is_dropped_reports_a_stale_search(
    tmp_path: Path,
) -> None:
    controller = make_controller(tmp_path / "config.toml")
    controller._state.search_matches = [{"matchId": "match-1", "title": "Inception"}]
    controller._search_catalog = None

    with pytest.raises(ValueError):
        await controller.prepare_session(mode="auto_candidates", feature_id="match-1")


class _StubProvider:
    def __init__(self, code: str, label: str) -> None:
        self.provider_code = code
        self.provider_label = label


class _ProgressiveStubAggregator:
    """Reports SubDL landing, then ASSRT, mirroring the real aggregator's callback contract."""

    providers = (_StubProvider("subdl", "SubDL"), _StubProvider("assrt", "ASSRT"))

    async def search_catalog(self, title, languages, correlation_id=None, on_provider_update=None):
        interim = AggregatedSearchCatalog(
            matches=[
                AggregatedTitleMatch(
                    id="match-1",
                    title="Interim Result",
                    year=None,
                    imdb_id=None,
                    tmdb_id=None,
                    media_type="movie",
                )
            ],
            results=[],
        )
        if on_provider_update is not None:
            await on_provider_update(["subdl"], ["subdl"], interim)
        return AggregatedSearchCatalog(
            matches=[
                AggregatedTitleMatch(
                    id="match-1",
                    title="Final Result",
                    year=None,
                    imdb_id=None,
                    tmdb_id=None,
                    media_type="movie",
                )
            ],
            results=[],
        )


async def test_search_pushes_an_interim_state_before_the_final_provider_answers(
    tmp_path: Path,
) -> None:
    emitted_states: list[dict] = []

    async def capture(event_type, payload) -> None:
        if event_type == "state":
            emitted_states.append(payload["state"])

    controller = GuiController(AppConfig(), capture, config_path=tmp_path / "config.toml")
    controller._aggregator = _ProgressiveStubAggregator()

    await controller.search(
        SearchRequest(title="Rick and Morty", source_language="en", target_language="en")
    )

    titles = [s["search_matches"][0]["title"] for s in emitted_states if s["search_matches"]]
    assert titles == ["Interim Result", "Final Result"]


async def test_an_interim_result_can_be_resolved_the_moment_it_is_shown(
    tmp_path: Path,
) -> None:
    """The catalog has to arrive with the results, not when the search finishes.

    Interim results are selectable as soon as they are on screen, and every
    lookup behind that click goes through the catalog. Published late, the first
    click on a fast provider's result failed as unresolvable.
    """
    resolvable: list[bool] = []

    class _Labelled:
        def display_label(self) -> str:
            return "SubDL - interim.srt"

    class _AggregatorWithAnInterimResult(_ProgressiveStubAggregator):
        async def search_catalog(
            self, title, languages, correlation_id=None, on_provider_update=None
        ):
            interim = AggregatedSearchCatalog(
                matches=[],
                results=[
                    AggregatedSubtitleResult(
                        result_id="interim-1",
                        match_id="match-1",
                        provider="subdl",
                        provider_label="SubDL",
                        title="Interim Result",
                        year=None,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="movie",
                        season=None,
                        episode=None,
                        parent_title=None,
                        language="en",
                        download_count=1,
                        file_name="interim.srt",
                        provider_result=_Labelled(),
                    )
                ],
            )
            if on_provider_update is not None:
                await on_provider_update(["subdl"], ["subdl"], interim)
                resolvable.append(self_controller._catalog_result("interim-1") is not None)
            return AggregatedSearchCatalog(matches=[], results=[])

    controller = make_controller(tmp_path / "config.toml")
    self_controller = controller
    controller._aggregator = _AggregatorWithAnInterimResult()

    await controller.search(
        SearchRequest(title="Rick and Morty", source_language="en", target_language="en")
    )

    assert resolvable == [True]


async def test_the_last_provider_landing_does_not_undo_a_preparation(tmp_path: Path) -> None:
    """Results are selectable before the search finishes, so preparing is too.

    Clearing the selection when the final catalog lands is right for a *new*
    search and wrong for the one it completes: the user is told the session is
    ready and then Start fails with "Prepare a session before starting sync".
    """
    controller = make_controller(tmp_path / "config.toml")
    controller._aggregator = _ProgressiveStubAggregator()

    async def prepare_during_the_interim(succeeded, settled, interim) -> None:
        controller._prepared_search_id = controller._active_search_id
        controller._prepared_runtime = object()
        controller._state.prepared_session = object()
        controller._state.selected_source_file_id = "result-1"

    original = _ProgressiveStubAggregator.search_catalog

    async def hooked(self, title, languages, correlation_id=None, on_provider_update=None):
        async def both(succeeded, settled, interim):
            await on_provider_update(succeeded, settled, interim)
            await prepare_during_the_interim(succeeded, settled, interim)

        return await original(
            self, title, languages, correlation_id=correlation_id, on_provider_update=both
        )

    controller._aggregator.search_catalog = hooked.__get__(controller._aggregator)

    await controller.search(
        SearchRequest(title="Rick and Morty", source_language="en", target_language="en")
    )

    assert controller._prepared_runtime is not None
    assert controller._state.prepared_session is not None
    assert controller._state.selected_source_file_id == "result-1"


async def test_a_superseded_search_does_not_clobber_the_newer_ones_state(tmp_path: Path) -> None:
    controller = make_controller(tmp_path / "config.toml")
    controller._aggregator = _ProgressiveStubAggregator()

    real_search_catalog = _ProgressiveStubAggregator.search_catalog

    async def search_catalog_with_hook(
        self, title, languages, correlation_id=None, on_provider_update=None
    ):
        async def hooked(succeeded_codes, settled_codes, interim):
            # Simulate the user retyping and a new search starting before this
            # (now-stale) search's provider callback gets a chance to run.
            controller._active_search_id = "a-newer-search"
            await on_provider_update(succeeded_codes, settled_codes, interim)

        return await real_search_catalog(
            self, title, languages, correlation_id=correlation_id, on_provider_update=hooked
        )

    controller._aggregator.search_catalog = search_catalog_with_hook.__get__(controller._aggregator)

    result = await controller.search(
        SearchRequest(title="Rick and Morty", source_language="en", target_language="en")
    )

    assert result["matches"][0]["title"] == "Final Result"
    # The superseded search's own results are handed back to its caller, but
    # they must not have overwritten the (simulated) newer search's state.
    assert controller._state.search_matches == []


async def test_a_failed_provider_drops_off_the_waiting_on_message(tmp_path: Path) -> None:
    controller = make_controller(tmp_path / "config.toml")

    class FailingAssrtAggregator:
        providers = (_StubProvider("subdl", "SubDL"), _StubProvider("assrt", "ASSRT"))

        async def search_catalog(
            self, title, languages, correlation_id=None, on_provider_update=None
        ):
            empty = AggregatedSearchCatalog(matches=[], results=[])
            if on_provider_update is not None:
                # ASSRT settles (by failing) before SubDL succeeds.
                await on_provider_update([], ["assrt"], empty)
                await on_provider_update(["subdl"], ["assrt", "subdl"], empty)
            return empty

    controller._aggregator = FailingAssrtAggregator()
    messages: list[str] = []

    async def capture(event_type, payload) -> None:
        if event_type == "progress":
            messages.append(payload["progress"]["message"])

    controller._emit_app_event = capture

    await controller.search(
        SearchRequest(title="Rick and Morty", source_language="en", target_language="en")
    )

    assert "ASSRT" not in messages[-2]  # Failed already: not "still waiting on".
    assert "ASSRT" not in messages[-1]


async def test_starting_without_a_capture_region_is_refused(tmp_path: Path) -> None:
    controller = make_controller(tmp_path / "config.toml")
    controller._prepared_runtime = PreparedRuntime(session_mode="ocr_fallback")
    controller._state.prepared_session = object()
    controller.config = replace(controller.config, capture_region=[])

    with pytest.raises(ValueError, match="capture region"):
        await controller.start_session()


def _add_rival_target(controller: GuiController, result_id: str, file_name: str) -> None:
    """A second English subtitle for the same episode, for the alignment weigh-in."""
    rival = replace(
        controller._search_catalog.results[1],
        result_id=result_id,
        file_name=file_name,
        download_count=5,
    )
    controller._search_catalog = replace(
        controller._search_catalog,
        results=[*controller._search_catalog.results, rival],
    )
    controller._state.search_results = [
        *controller._state.search_results,
        {
            "id": result_id,
            "resultId": result_id,
            "matchId": "match-1",
            "provider": "opensubtitles",
            "providerLabel": "OpenSubtitles",
            "language": "en",
            "fileName": file_name,
        },
    ]


@pytest.mark.asyncio
async def test_a_better_aligned_target_is_reported_ahead_of_the_chosen_one(
    tmp_path: Path, mocker
) -> None:
    """The viewer's pick stands; they are shown what it costs them."""
    controller, _, download = _pair_controller(tmp_path, mocker)
    _add_rival_target(controller, "result-3", "rival.srt")

    source = tmp_path / "two-line-source.srt"
    source.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\ns0\n\n2\n00:00:03,000 --> 00:00:05,000\ns1\n",
        encoding="utf-8",
    )
    chosen = tmp_path / "half.srt"
    chosen.write_text("1\n00:00:00,000 --> 00:00:02,000\nt0\n", encoding="utf-8")
    rival = tmp_path / "whole.srt"
    rival.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nt0\n\n2\n00:00:03,000 --> 00:00:05,000\nt1\n",
        encoding="utf-8",
    )
    download.side_effect = [source, chosen, rival]

    payload = await controller.prepare_session(
        mode="subtitle_pair",
        feature_id="match-1",
        source_file_id="result-1",
        target_file_id="result-2",
    )

    alignment = payload["target_alignment"]
    assert [entry["result_id"] for entry in alignment] == ["result-3", "result-2"]
    assert alignment[0]["unpaired_cues"] == 0
    assert alignment[1]["unpaired_cues"] == 1
    assert alignment[1]["unpaired_ms"] == 2000
    assert alignment[1]["chosen"] is True


@pytest.mark.asyncio
async def test_a_candidate_that_will_not_download_is_left_out_rather_than_fatal(
    tmp_path: Path, mocker
) -> None:
    """The weigh-in is advice arriving during preparation, not a step of it."""
    controller, _, download = _pair_controller(tmp_path, mocker)
    _add_rival_target(controller, "result-3", "rival.srt")

    source = tmp_path / "source-again.srt"
    source.write_text("1\n00:00:00,000 --> 00:00:02,000\ns0\n", encoding="utf-8")
    chosen = tmp_path / "chosen-again.srt"
    chosen.write_text("1\n00:00:00,000 --> 00:00:02,000\nt0\n", encoding="utf-8")
    download.side_effect = [source, chosen, RuntimeError("provider is down")]

    payload = await controller.prepare_session(
        mode="subtitle_pair",
        feature_id="match-1",
        source_file_id="result-1",
        target_file_id="result-2",
    )

    assert payload["session_mode"] == "subtitle_pair"
    assert [entry["result_id"] for entry in payload["target_alignment"]] == ["result-2"]
