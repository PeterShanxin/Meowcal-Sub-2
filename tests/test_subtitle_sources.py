import pytest

from meocosub2.config import AppConfig
from meocosub2.errors import SubtitleSourceError
from meocosub2.subtitle_sources.aggregator import SubtitleSearchAggregator
from meocosub2.subtitle_sources.subdl import SubdlProvider
from meocosub2.subtitle_sources.types import AggregatedWork, ProviderSearchCatalog, ProviderSubtitleMatch, ProviderSubtitleResult
from meocosub2.subtitle_sources.utils import canonical_title, map_subdl_language


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


class QueryRecorderProvider(FakeProvider):
    def __init__(self):
        super().__init__("recorder", "Recorder", ProviderSearchCatalog(matches=[], results=[]))
        self.queries: list[str] = []

    async def search_catalog(self, query: str, languages: str) -> ProviderSearchCatalog:
        self.queries.append(query)
        return await super().search_catalog(query, languages)


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


def test_canonical_title_strips_accents_and_lowercases() -> None:
    assert canonical_title("Café au Lait") == "cafe au lait"


def test_canonical_title_converts_ampersand_to_and() -> None:
    assert canonical_title("Lock & Stock") == "lock and stock"


def test_canonical_title_unescapes_html_entities() -> None:
    assert canonical_title("Lock &amp; Stock") == "lock and stock"


def test_canonical_title_removes_underscores() -> None:
    assert canonical_title("my_movie_title") == "my movie title"


def test_canonical_title_removes_quotes() -> None:
    assert canonical_title("He Said 'Hi'") == "he said hi"


def test_canonical_title_preserves_apostrophe_boundaries() -> None:
    assert canonical_title("Rock'n'Roll") == "rock n roll"


def test_canonical_title_keeps_possessive_queries_exact() -> None:
    assert canonical_title("Schindler's List") == "schindlers list"


def test_canonical_title_empty_and_none() -> None:
    assert canonical_title(None) == ""
    assert canonical_title("") == ""


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


def test_subdl_parse_page_subtitles_infers_zero_episode_from_title() -> None:
    provider = SubdlProvider(AppConfig())

    results = provider._parse_page_subtitles(
        title="From",
        year=2022,
        match_id="subdl-match-sd1656864",
        requested_languages={"en"},
        page_props={
            "groupedSubtitles": {
                "english": [
                    {
                        "id": 3409485,
                        "title": "From.S03E02.WEB",
                        "season": 3,
                        "episode": 0,
                        "downloads": 17,
                        "link": "3409485-8332893.zip",
                        "releases": ["From.S03E02.WEB"],
                    }
                ]
            }
        },
    )

    assert len(results) == 1
    assert results[0].media_type == "episode"
    assert results[0].season == 3
    assert results[0].episode == 2
    assert results[0].parent_title == "From"


def test_subdl_parse_page_subtitles_normalizes_unicode_digits_for_episode_inference() -> None:
    provider = SubdlProvider(AppConfig())

    results = provider._parse_page_subtitles(
        title="From",
        year=2026,
        match_id="subdl-match-sd1656864",
        requested_languages={"en"},
        page_props={
            "groupedSubtitles": {
                "english": [
                    {
                        "id": 3576745,
                        "title": "[CoffeePrison] FROM S𝟬𝟰E𝟬𝟭 PRIME AMZN WEB",
                        "season": 4,
                        "episode": 0,
                        "downloads": 5,
                        "link": "3576745-8495217.zip",
                        "releases": ["[CoffeePrison] FROM S𝟬𝟰E𝟬𝟭 PRIME AMZN WEB"],
                    }
                ]
            }
        },
    )

    assert len(results) == 1
    assert results[0].media_type == "episode"
    assert results[0].season == 4
    assert results[0].episode == 1


def test_subdl_parse_page_subtitles_corrects_unreasonable_episode_field_from_releases() -> None:
    provider = SubdlProvider(AppConfig())

    results = provider._parse_page_subtitles(
        title="From",
        year=2023,
        match_id="subdl-match-sd1656864",
        requested_languages={"en"},
        page_props={
            "groupedSubtitles": {
                "english": [
                    {
                        "id": 3065884,
                        "title": "FromS02E011080pWEB-DLDD+5.1H.264(RETAiL)",
                        "season": 2,
                        "episode": 11080,
                        "downloads": 10,
                        "link": "3065884-3074995.zip",
                        "releases": [
                            "From S02E01 1080p WEB-DL DD 5.1 H.264 (RETAiL)",
                            "From S02E01 720p WEB-DL DD 5.1 H.264 (RETAiL)",
                        ],
                    }
                ]
            }
        },
    )

    assert len(results) == 1
    assert results[0].media_type == "episode"
    assert results[0].season == 2
    assert results[0].episode == 1


def test_subdl_limit_subtitles_keeps_episode_coverage_before_duplicates() -> None:
    provider = SubdlProvider(AppConfig())
    subtitles = [
        _subdl_result(f"dupe-{i}", season=1, episode=1, score=99.0, downloads=100 - i)
        for i in range(45)
    ]
    subtitles.append(_subdl_result("episode-2", season=1, episode=2, score=10.0, downloads=1))
    subtitles.append(_subdl_result("episode-3", season=2, episode=1, score=9.0, downloads=1))

    limited = provider._limit_subtitles(subtitles)

    assert len(limited) == 40
    retained_episode_keys = {(item.season, item.episode) for item in limited}
    assert (1, 2) in retained_episode_keys
    assert (2, 1) in retained_episode_keys


def test_subdl_limit_subtitles_keeps_best_ranked_episode_representatives() -> None:
    provider = SubdlProvider(AppConfig())
    subtitles = [
        _subdl_result(f"low-{episode}", season=1, episode=episode, score=1.0, downloads=episode)
        for episode in range(1, 41)
    ]
    subtitles.append(_subdl_result("high-late-season", season=4, episode=10, score=99.0, downloads=100))

    limited = provider._limit_subtitles(subtitles)

    retained_episode_keys = {(item.season, item.episode) for item in limited}
    assert len(limited) == 40
    assert (4, 10) in retained_episode_keys
    assert (1, 1) not in retained_episode_keys


def _subdl_result(
    result_id: str,
    *,
    season: int,
    episode: int,
    score: float,
    downloads: int,
) -> ProviderSubtitleResult:
    return ProviderSubtitleResult(
        id=result_id,
        match_id="subdl-match-sd1656864",
        provider="subdl",
        provider_label="SubDL",
        title=f"From.S{season:02d}E{episode:02d}",
        year=2022,
        imdb_id=None,
        media_type="episode",
        season=season,
        episode=episode,
        parent_title="From",
        language="en",
        download_count=downloads,
        file_name=f"{result_id}.zip",
        match_score=score,
        download_ref=f"{result_id}.zip",
    )

def test_aggregator_work_sort_prefers_exact_series_and_franchise_movies() -> None:
    aggregator = SubtitleSearchAggregator(AppConfig())
    works = [
        AggregatedWork(
            id="movie-2018",
            title="Overlord",
            media_type="movie",
            year=2018,
            year_end=None,
            imdb_id="tt4530422",
            tmdb_id="438799",
            providers=("opensubtitles",),
            provider_labels=("OpenSubtitles",),
            total_subtitles=214,
            match_score=492.0,
        ),
        AggregatedWork(
            id="anime-series",
            title="Overlord",
            media_type="series",
            year=2015,
            year_end=2022,
            imdb_id="tt4869896",
            tmdb_id="64196",
            providers=("assrt", "opensubtitles"),
            provider_labels=("ASSRT", "OpenSubtitles"),
            total_episodes=52,
            total_subtitles=281,
            match_score=510.0,
        ),
        AggregatedWork(
            id="anime-movie",
            title="OVERLORD: The Sacred Kingdom",
            media_type="movie",
            year=2024,
            year_end=None,
            imdb_id="tt14603848",
            tmdb_id="1014505",
            providers=("opensubtitles",),
            provider_labels=("OpenSubtitles",),
            total_subtitles=14,
            match_score=202.0,
        ),
        AggregatedWork(
            id="unrelated-2018",
            title="Noisy Provider Hit",
            media_type="movie",
            year=2018,
            year_end=None,
            imdb_id="tt-noisy",
            tmdb_id="999",
            providers=("opensubtitles",),
            provider_labels=("OpenSubtitles",),
            total_subtitles=999,
            match_score=999.0,
        ),
    ]

    sorted_works = aggregator._sort_works(works, "Overlord")

    assert [work.id for work in sorted_works[:3]] == ["anime-series", "anime-movie", "movie-2018"]
    assert aggregator._sort_works(works, "Overlord", query_year=2018)[0].id == "movie-2018"
    assert aggregator._sort_works(works, "Overlord", query_year=2015)[0].id == "anime-series"


@pytest.mark.asyncio
async def test_aggregator_rewrites_fate_faker_alias_before_provider_search() -> None:
    provider = QueryRecorderProvider()
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (provider,)

    await aggregator.search_catalog("Fate Faker", "en")

    assert provider.queries == ["Fate/strange Fake"]


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

    # The two providers' tvshow matches merge by canonical title; the per-
    # episode results are promoted to a separate episode-level group so the UI
    # can break them out later.
    tvshow_matches = [m for m in catalog.matches if m.media_type in ("tvshow", "series")]
    assert len(tvshow_matches) == 1
    assert tvshow_matches[0].provider_count == 2
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


@pytest.mark.asyncio
async def test_aggregator_collapses_series_seasons_into_one_work() -> None:
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider(
            "opensubtitles",
            "OpenSubtitles",
            ProviderSearchCatalog(
                matches=[
                    ProviderSubtitleMatch(
                        id="os-series",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="Overlord",
                        year=2015,
                        imdb_id="tt4869896",
                        tmdb_id=None,
                        media_type="tvshow",
                        subtitles_count=120,
                        match_score=300.0,
                    ),
                    ProviderSubtitleMatch(
                        id="os-s1e1",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="The End and the Beginning",
                        year=2015,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="episode",
                        season=1,
                        episode=1,
                        parent_title="Overlord",
                        subtitles_count=12,
                        match_score=260.0,
                    ),
                    ProviderSubtitleMatch(
                        id="os-s2e4",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="A Boy's Dream",
                        year=2018,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="episode",
                        season=2,
                        episode=4,
                        parent_title="Overlord",
                        subtitles_count=8,
                        match_score=250.0,
                    ),
                ],
                results=[
                    ProviderSubtitleResult(
                        id="os-result-1",
                        match_id="os-s1e1",
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
                        download_count=5000,
                        file_name="Overlord.S01E01.srt",
                        match_score=260.0,
                    ),
                ],
            ),
        ),
        FakeProvider(
            "subdl",
            "SubDL",
            ProviderSearchCatalog(
                matches=[
                    ProviderSubtitleMatch(
                        id="sd-s2e4",
                        provider="subdl",
                        provider_label="SubDL",
                        title="A Boy's Dream",
                        year=2018,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="episode",
                        season=2,
                        episode=4,
                        parent_title="Overlord",
                        subtitles_count=3,
                        match_score=210.0,
                    ),
                ],
                results=[],
            ),
        ),
    )

    catalog = await aggregator.search_catalog("Overlord", "en")

    assert len(catalog.works) == 1, catalog.works
    work = catalog.works[0]
    assert work.media_type == "series"
    assert work.imdb_id == "tt4869896"
    assert len(work.seasons) == 2
    season_numbers = sorted(s.season_number for s in work.seasons)
    assert season_numbers == [1, 2]
    assert work.total_episodes == 2
    assert "opensubtitles" in work.providers
    assert "subdl" in work.providers
    chip_kinds = [chip.kind for chip in work.info_chips]
    assert "imdb" in chip_kinds
    assert "episodes" in chip_kinds


@pytest.mark.asyncio
async def test_aggregator_merges_roman_and_s_suffix_season_movies_into_series() -> None:
    """Providers that tag each season as a movie still fold into one work."""
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider(
            "subdl",
            "SubDL",
            ProviderSearchCatalog(
                matches=[
                    ProviderSubtitleMatch(
                        id="sd-s1",
                        provider="subdl",
                        provider_label="SubDL",
                        title="Overlord",
                        year=2015,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="tvshow",
                        subtitles_count=120,
                        match_score=300.0,
                    ),
                    ProviderSubtitleMatch(
                        id="sd-s2",
                        provider="subdl",
                        provider_label="SubDL",
                        title="Overlord II",
                        year=2018,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="movie",
                        subtitles_count=77,
                        match_score=260.0,
                    ),
                    ProviderSubtitleMatch(
                        id="sd-s4-s",
                        provider="subdl",
                        provider_label="SubDL",
                        title="OVERLORD S4",
                        year=2022,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="movie",
                        subtitles_count=30,
                        match_score=240.0,
                    ),
                ],
                results=[
                    ProviderSubtitleResult(
                        id="sd-res-1",
                        match_id="sd-s2",
                        provider="subdl",
                        provider_label="SubDL",
                        title="Overlord II",
                        year=2018,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="movie",
                        language="en",
                        download_count=520,
                        file_name="overlord-ii.srt",
                    ),
                    ProviderSubtitleResult(
                        id="sd-res-2",
                        match_id="sd-s4-s",
                        provider="subdl",
                        provider_label="SubDL",
                        title="OVERLORD S4",
                        year=2022,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="movie",
                        language="en",
                        download_count=100,
                        file_name="overlord-s4.srt",
                    ),
                ],
            ),
        ),
    )

    catalog = await aggregator.search_catalog("Overlord", "en")

    series_works = [w for w in catalog.works if w.media_type == "series"]
    assert len(series_works) == 1, catalog.works
    work = series_works[0]
    seasons = sorted(s.season_number for s in work.seasons)
    # S2 via roman, S4 via "S" prefix, S1 none (series-level match has no
    # season marker so it supplies the primary_match_id, not an episode row).
    assert 2 in seasons
    assert 4 in seasons


@pytest.mark.asyncio
async def test_aggregator_keeps_movie_sequels_separate_works() -> None:
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider(
            "opensubtitles",
            "OpenSubtitles",
            ProviderSearchCatalog(
                matches=[
                    ProviderSubtitleMatch(
                        id="os-avengers",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="The Avengers",
                        year=2012,
                        imdb_id="tt0848228",
                        tmdb_id=None,
                        media_type="movie",
                        subtitles_count=400,
                        match_score=280.0,
                    ),
                    ProviderSubtitleMatch(
                        id="os-endgame",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="Avengers: Endgame",
                        year=2019,
                        imdb_id="tt4154796",
                        tmdb_id=None,
                        media_type="movie",
                        subtitles_count=520,
                        match_score=270.0,
                    ),
                ],
                results=[],
            ),
        ),
    )

    catalog = await aggregator.search_catalog("Avengers", "en")

    movie_works = [w for w in catalog.works if w.media_type == "movie"]
    assert len(movie_works) == 2
    imdb_ids = {w.imdb_id for w in movie_works}
    assert imdb_ids == {"tt0848228", "tt4154796"}
    for work in movie_works:
        assert work.seasons == []
        assert work.primary_match_id is not None
