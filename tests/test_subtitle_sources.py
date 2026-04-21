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
