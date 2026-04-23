import pytest

from meocosub2.config import AppConfig
from meocosub2.errors import SubtitleSourceError
from meocosub2.subtitle_sources.aggregator import SubtitleSearchAggregator
from meocosub2.subtitle_sources.subdl import SubdlProvider
from meocosub2.subtitle_sources.types import ProviderSearchCatalog, ProviderSubtitleMatch, ProviderSubtitleResult
from meocosub2.subtitle_sources.utils import map_subdl_language


class FakeProvider:
    def __init__(self, code, label, catalog=None, error=None):
        self.provider_code = code
        self.provider_label = label
        self._catalog = catalog
        self._error = error

    async def search_catalog(self, query: str, languages: str) -> ProviderSearchCatalog:
        if self._error is not None:
            raise self._error
        return self._catalog

    async def download(self, result: ProviderSubtitleResult):
        return result.file_name


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("farsi_persian", "fa"),
        ("big_5_code", "zht"),
        ("big-5-code", "zht"),
        ("gb_code", "zh"),
        ("chinese-bg-code", "zht"),
        ("chinese_gb_code", "zh"),
    ],
)
def test_map_subdl_language_normalizes_separator_variants(value: str, expected: str) -> None:
    assert map_subdl_language(value) == expected


def test_subdl_parse_page_subtitles_keeps_big_5_code_results_for_chinese_requests() -> None:
    provider = SubdlProvider(AppConfig())

    results = provider._parse_page_subtitles(
        title="Overlord",
        year=2015,
        match_id="subdl-match-sd1300064",
        requested_languages={"en", "zh", "zht"},
        page_props={
            "groupedSubtitles": {
                "big_5_code": [
                    {
                        "id": 3309711,
                        "title": "[Crazy-SoL]OverlordIIIEp01-13",
                        "season": 0,
                        "episode": 0,
                        "downloads": 31,
                        "link": "3309711-3332811.zip",
                    }
                ]
            }
        },
    )

    assert len(results) == 1
    assert results[0].language == "zht"
    assert results[0].file_name == "[Crazy-SoL]OverlordIIIEp01-13"


@pytest.mark.asyncio
async def test_aggregator_merges_duplicate_titles_and_prefers_provider_order() -> None:
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider(
            "subdl",
            "SubDL",
            ProviderSearchCatalog(
                matches=[
                    ProviderSubtitleMatch(
                        id="subdl-match-1",
                        provider="subdl",
                        provider_label="SubDL",
                        title="Fate/strange Fake",
                        year=2024,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="tvshow",
                        subtitles_count=3,
                        match_score=220,
                    )
                ],
                results=[
                    ProviderSubtitleResult(
                        id="subdl-result-1",
                        match_id="subdl-match-1",
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
                        language="en",
                        download_count=80,
                        file_name="subdl.srt",
                        match_score=210,
                    )
                ],
            ),
        ),
        FakeProvider(
            "opensubtitles",
            "OpenSubtitles",
            ProviderSearchCatalog(
                matches=[
                    ProviderSubtitleMatch(
                        id="os-match-1",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="Fate strange Fake",
                        year=2024,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="tvshow",
                        subtitles_count=2,
                        match_score=205,
                    )
                ],
                results=[
                    ProviderSubtitleResult(
                        id="os-result-1",
                        match_id="os-match-1",
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
                        download_count=180,
                        file_name="opensubtitles.srt",
                        match_score=210,
                    )
                ],
            ),
        ),
    )

    catalog = await aggregator.search_catalog("Fate/strange Fake", "en,zht")

    assert len(catalog.matches) == 1
    assert catalog.matches[0].provider_count == 2
    assert catalog.results[0].provider == "subdl"
    assert catalog.results[1].provider == "opensubtitles"


@pytest.mark.asyncio
async def test_aggregator_prefers_parent_series_over_episode_for_bare_title() -> None:
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider(
            "opensubtitles",
            "OpenSubtitles",
            ProviderSearchCatalog(
                matches=[
                    ProviderSubtitleMatch(
                        id="os-match-series",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="Overlord",
                        year=2015,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="tvshow",
                        subtitles_count=349,
                        match_score=205,
                    ),
                    ProviderSubtitleMatch(
                        id="os-match-episode",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="Overlord",
                        year=2015,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="episode",
                        season=2,
                        episode=4,
                        parent_title="Overlord",
                        subtitles_count=43,
                        match_score=260,
                    ),
                ],
                results=[
                    ProviderSubtitleResult(
                        id="os-result-series",
                        match_id="os-match-series",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="Overlord",
                        year=2015,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="episode",
                        season=1,
                        episode=1,
                        parent_title="Overlord",
                        language="en",
                        download_count=100,
                        file_name="overlord-season-1.srt",
                        match_score=205,
                    ),
                    ProviderSubtitleResult(
                        id="os-result-episode",
                        match_id="os-match-episode",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="Overlord",
                        year=2015,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="episode",
                        season=2,
                        episode=4,
                        parent_title="Overlord",
                        language="en",
                        download_count=40,
                        file_name="overlord-s02e04.srt",
                        match_score=260,
                    ),
                ],
            ),
        ),
    )

    catalog = await aggregator.search_catalog("Overlord", "en")

    assert catalog.matches[0].media_type == "tvshow"
    assert catalog.matches[0].title == "Overlord"
    assert catalog.matches[1].media_type == "episode"


@pytest.mark.asyncio
async def test_aggregator_keeps_episode_first_when_query_names_episode() -> None:
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider(
            "opensubtitles",
            "OpenSubtitles",
            ProviderSearchCatalog(
                matches=[
                    ProviderSubtitleMatch(
                        id="os-match-series",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="Overlord",
                        year=2015,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="tvshow",
                        subtitles_count=349,
                        match_score=205,
                    ),
                    ProviderSubtitleMatch(
                        id="os-match-episode",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="Overlord",
                        year=2015,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="episode",
                        season=2,
                        episode=4,
                        parent_title="Overlord",
                        subtitles_count=43,
                        match_score=260,
                    ),
                ],
                results=[
                    ProviderSubtitleResult(
                        id="os-result-series",
                        match_id="os-match-series",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="Overlord",
                        year=2015,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="episode",
                        season=1,
                        episode=1,
                        parent_title="Overlord",
                        language="en",
                        download_count=100,
                        file_name="overlord-season-1.srt",
                        match_score=205,
                    ),
                    ProviderSubtitleResult(
                        id="os-result-episode",
                        match_id="os-match-episode",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="Overlord",
                        year=2015,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="episode",
                        season=2,
                        episode=4,
                        parent_title="Overlord",
                        language="en",
                        download_count=40,
                        file_name="overlord-s02e04.srt",
                        match_score=260,
                    ),
                ],
            ),
        ),
    )

    catalog = await aggregator.search_catalog("Overlord S02E04", "en")

    assert catalog.matches[0].media_type == "episode"
    assert catalog.matches[0].season == 2
    assert catalog.matches[0].episode == 4


@pytest.mark.asyncio
async def test_aggregator_prefers_series_even_when_episode_title_scores_higher() -> None:
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider(
            "opensubtitles",
            "OpenSubtitles",
            ProviderSearchCatalog(
                matches=[
                    ProviderSubtitleMatch(
                        id="os-match-manhattan",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="overlord",
                        year=2015,
                        imdb_id="4626998",
                        tmdb_id="1116912",
                        media_type="episode",
                        season=2,
                        episode=4,
                        parent_title="Manhattan",
                        subtitles_count=43,
                        match_score=510.0,
                    ),
                    ProviderSubtitleMatch(
                        id="os-match-anime",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="オーバーロード",
                        year=2015,
                        imdb_id="4869896",
                        tmdb_id="64196",
                        media_type="tvshow",
                        subtitles_count=61,
                        match_score=499.46,
                    ),
                ],
                results=[
                    ProviderSubtitleResult(
                        id="os-result-manhattan",
                        match_id="os-match-manhattan",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="Overlord",
                        year=2015,
                        imdb_id="4626998",
                        tmdb_id="1116912",
                        media_type="episode",
                        season=2,
                        episode=4,
                        parent_title="Manhattan",
                        language="en",
                        download_count=757,
                        file_name="Manhattan.S02E04.srt",
                        match_score=505.14,
                    ),
                    ProviderSubtitleResult(
                        id="os-result-anime",
                        match_id="os-match-anime",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="End and Beginning",
                        year=2015,
                        imdb_id="4875502",
                        tmdb_id="64196",
                        media_type="episode",
                        season=1,
                        episode=1,
                        parent_title="Overlord",
                        language="en",
                        download_count=473,
                        file_name="Overlord.S01E01.srt",
                        match_score=494.0,
                    ),
                ],
            ),
        ),
    )

    catalog = await aggregator.search_catalog("Overlord", "en")

    assert catalog.matches[0].media_type == "tvshow"
    assert catalog.matches[0].title == "オーバーロード"
    assert catalog.matches[1].parent_title == "Manhattan"


@pytest.mark.asyncio
async def test_aggregator_returns_partial_results_when_one_provider_fails() -> None:
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider(
            "subdl",
            "SubDL",
            ProviderSearchCatalog(
                matches=[],
                results=[
                    ProviderSubtitleResult(
                        id="subdl-result-1",
                        match_id="subdl-match-1",
                        provider="subdl",
                        provider_label="SubDL",
                        title="Movie",
                        year=2024,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="movie",
                        language="en",
                        download_count=10,
                        file_name="movie.srt",
                    )
                ],
            ),
        ),
        FakeProvider("assrt", "ASSRT", error=RuntimeError("boom")),
    )

    catalog = await aggregator.search_catalog("Movie", "en")

    assert len(catalog.results) == 1
    assert any("ASSRT" in warning for warning in catalog.warnings)


@pytest.mark.asyncio
async def test_aggregator_raises_when_all_providers_fail() -> None:
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider("subdl", "SubDL", error=RuntimeError("subdl failed")),
        FakeProvider("assrt", "ASSRT", error=RuntimeError("assrt failed")),
    )

    with pytest.raises(SubtitleSourceError):
        await aggregator.search_catalog("Movie", "en")
