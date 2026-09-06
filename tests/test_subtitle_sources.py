import asyncio
import zipfile

import httpx
import pytest

import meocosub2.subtitle_sources.aggregator as aggregator_module
import meocosub2.subtitle_sources.subdl as subdl_module
from meocosub2.config import AppConfig
from meocosub2.errors import SubtitleSourceError
from meocosub2.subtitle_sources.aggregator import SubtitleSearchAggregator
from meocosub2.subtitle_sources.assrt import AssrtProvider
from meocosub2.subtitle_sources.subdl import SubdlProvider
from meocosub2.subtitle_sources.types import (
    AggregatedWork,
    ProviderSearchCatalog,
    ProviderSubtitleMatch,
    ProviderSubtitleResult,
)
from meocosub2.subtitle_sources.utils import (
    canonical_title,
    looks_like_release_name,
    map_subdl_language,
)


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


def test_subdl_parse_page_subtitles_keeps_valid_structured_episode_over_text() -> None:
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
                        "id": 4000001,
                        "title": "From.S01E01-E10.Pack",
                        "season": 1,
                        "episode": 5,
                        "downloads": 3,
                        "link": "4000001-1.zip",
                        "releases": ["From.S01E01-E10.Mixed"],
                    }
                ]
            }
        },
    )

    assert len(results) == 1
    assert results[0].media_type == "episode"
    assert results[0].season == 1
    assert results[0].episode == 5


def test_subdl_parse_page_subtitles_preserves_inferred_season_zero_special() -> None:
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
                        "id": 4000002,
                        "title": "From.S00E01.Special",
                        "season": 0,
                        "episode": 0,
                        "downloads": 2,
                        "link": "4000002-1.zip",
                    }
                ]
            }
        },
    )

    assert len(results) == 1
    assert results[0].media_type == "episode"
    assert results[0].season == 0
    assert results[0].episode == 1


@pytest.mark.asyncio
async def test_subdl_search_requires_api_key() -> None:
    provider = SubdlProvider(AppConfig(subdl_enabled=True, subdl_api_key=""))

    catalog = await provider.search_catalog("from", "en")

    assert catalog.results == []
    assert catalog.warnings == ["SubDL API key is not configured."]


def test_subdl_capabilities_require_auth() -> None:
    assert SubdlProvider.capabilities.requires_auth is True


@pytest.mark.asyncio
async def test_subdl_download_rejects_non_subdl_absolute_url() -> None:
    provider = SubdlProvider(AppConfig(subdl_api_key="subdl-key"))
    result = ProviderSubtitleResult(
        id="subdl-result-unsafe",
        match_id="subdl-match-sd1656864",
        provider="subdl",
        provider_label="SubDL",
        title="From",
        year=2022,
        imdb_id=None,
        media_type="episode",
        language="en",
        download_count=0,
        file_name="subtitle.zip",
        download_ref="https://example.com/subtitle.zip",
        raw={"link": "https://example.com/subtitle.zip"},
    )

    with pytest.raises(SubtitleSourceError, match="host is not allowed"):
        await provider.download(result)


@pytest.mark.asyncio
async def test_subdl_download_writes_raw_unpacked_subtitle(monkeypatch, tmp_path) -> None:
    class FakeResponse:
        content = b"1\n00:00:00,000 --> 00:00:01,000\nHello\n"
        status_code = 200

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.url = ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str):
            self.url = url
            return FakeResponse()

    monkeypatch.setattr(subdl_module.httpx, "AsyncClient", FakeAsyncClient)
    provider = SubdlProvider(AppConfig(subdl_api_key="subdl-key"))
    provider._cache_dir = tmp_path
    result = ProviderSubtitleResult(
        id="subdl-result-s04e01",
        match_id="subdl-match-sd1656864",
        provider="subdl",
        provider_label="SubDL",
        title="From.S04E01.srt",
        year=2022,
        imdb_id=None,
        media_type="episode",
        season=4,
        episode=1,
        parent_title="From",
        language="en",
        download_count=0,
        file_name="From.S04E01.srt",
        download_ref="3576745/s04e01",
        raw={"link": "3576745/s04e01", "file_n_id": "s04e01"},
    )

    path = await provider.download(result)

    assert path == tmp_path / "subdl-result-s04e01" / "From.S04E01.srt"
    assert path.read_bytes() == FakeResponse.content


@pytest.mark.asyncio
async def test_subdl_download_keeps_bad_zip_failures_for_packs(monkeypatch, tmp_path) -> None:
    class FakeResponse:
        content = b"<html>not a zip</html>"
        status_code = 200

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get(self, url: str):
            return FakeResponse()

    monkeypatch.setattr(subdl_module.httpx, "AsyncClient", FakeAsyncClient)
    provider = SubdlProvider(AppConfig(subdl_api_key="subdl-key"))
    provider._cache_dir = tmp_path
    result = ProviderSubtitleResult(
        id="subdl-result-pack",
        match_id="subdl-match-sd1656864",
        provider="subdl",
        provider_label="SubDL",
        title="From.S04.Pack.zip",
        year=2022,
        imdb_id=None,
        media_type="episode",
        season=4,
        episode=None,
        parent_title="From",
        language="en",
        download_count=0,
        file_name="From.S04.Pack.zip",
        download_ref="3576745-8495217.zip",
        raw={"link": "3576745-8495217.zip"},
    )

    with pytest.raises(zipfile.BadZipFile):
        await provider.download(result)


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
    subtitles.append(
        _subdl_result("high-late-season", season=4, episode=10, score=99.0, downloads=100)
    )

    limited = provider._limit_subtitles(subtitles)

    retained_episode_keys = {(item.season, item.episode) for item in limited}
    assert len(limited) == 40
    assert (4, 10) in retained_episode_keys
    assert (1, 1) not in retained_episode_keys


def test_subdl_safe_identifier_bounds_path_like_fallbacks() -> None:
    provider = SubdlProvider(AppConfig())
    value = "https://dl.subdl.com/subtitle/" + ("season/four/" * 12) + "from.zip"

    safe = provider._safe_identifier(value)

    assert "/" not in safe
    assert "\\" not in safe
    assert len(safe) <= 80


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


@pytest.mark.asyncio
async def test_subdl_search_uses_api_results_and_subtitles(monkeypatch) -> None:
    provider = SubdlProvider(AppConfig(subdl_api_key="subdl-key"))
    calls: list[dict[str, object]] = []

    async def fake_fetch_api(client, params: dict[str, object]) -> dict[str, object]:
        calls.append(dict(params))
        if "film_name" in params:
            return {
                "status": True,
                "results": [
                    {
                        "sd_id": 1656864,
                        "name": "From",
                        "type": "tv",
                        "year": 2022,
                        "imdb_id": "tt9813792",
                        "tmdb_id": 124364,
                        "subtitles_count": 7,
                    }
                ],
            }
        return {
            "status": True,
            "subtitles": [
                {
                    "id": 3576745,
                    "language": "English",
                    "name": "From.S04E01.1080p.WEB",
                    "season": 4,
                    "episode": 1,
                    "downloads": 5,
                    "url": "/subtitle/3576745-8495217.zip",
                    "releases": ["From.S04E01.1080p.WEB"],
                },
                {
                    "id": 3576746,
                    "language": "Traditional Chinese",
                    "name": "From.S04E01.1080p.WEB.CHT",
                    "season": 4,
                    "episode": 1,
                    "downloads": 2,
                    "url": "3576746-8495218.zip",
                },
            ],
        }

    monkeypatch.setattr(provider, "_fetch_api", fake_fetch_api)

    catalog = await provider.search_catalog("from", "en,zht")

    assert calls[0]["film_name"] == "from"
    assert calls[0]["languages"] == "EN,ZH"
    assert calls[0]["unpack"] == "1"
    assert calls[1]["sd_id"] == "1656864"
    assert calls[1]["full_season"] == "1"
    assert calls[1]["unpack"] == "1"
    assert catalog.matches[0].title == "From"
    assert catalog.matches[0].imdb_id == "tt9813792"
    assert len(catalog.results) == 2
    assert catalog.results[0].season == 4
    assert catalog.results[0].episode == 1
    assert catalog.results[0].download_ref == "3576745-8495217.zip"


@pytest.mark.asyncio
async def test_subdl_movie_search_omits_full_season(monkeypatch) -> None:
    provider = SubdlProvider(AppConfig(subdl_api_key="subdl-key"))
    calls: list[dict[str, object]] = []

    async def fake_fetch_api(client, params: dict[str, object]) -> dict[str, object]:
        calls.append(dict(params))
        if "film_name" in params:
            return {
                "status": True,
                "results": [
                    {
                        "sd_id": 4567,
                        "name": "Inception",
                        "type": "movie",
                        "year": 2010,
                        "imdb_id": "tt1375666",
                        "subtitles_count": 4,
                    }
                ],
            }
        return {
            "status": True,
            "subtitles": [
                {
                    "id": 1234,
                    "language": "English",
                    "name": "Inception.2010.1080p.BluRay",
                    "downloads": 9,
                    "url": "/subtitle/1234-5678.zip",
                }
            ],
        }

    monkeypatch.setattr(provider, "_fetch_api", fake_fetch_api)

    catalog = await provider.search_catalog("inception", "en")

    assert calls[1]["sd_id"] == "4567"
    assert "full_season" not in calls[1]
    assert len(catalog.results) == 1


@pytest.mark.asyncio
async def test_subdl_search_keeps_matches_when_one_detail_fetch_is_forbidden(monkeypatch) -> None:
    provider = SubdlProvider(AppConfig(subdl_api_key="subdl-key"))
    request = httpx.Request(
        "GET", "https://api.subdl.com/api/v1/subtitles?api_key=subdl-key&sd_id=bad"
    )
    forbidden = httpx.HTTPStatusError(
        "Client error '403 Forbidden'",
        request=request,
        response=httpx.Response(403, request=request),
    )

    async def fake_fetch_api(client, params: dict[str, object]) -> dict[str, object]:
        if "film_name" in params:
            return {
                "status": True,
                "results": [
                    {"sd_id": 1, "name": "From", "type": "tv", "year": 2022, "subtitles_count": 7},
                    {
                        "sd_id": "bad",
                        "name": "From: Blocked",
                        "type": "tv",
                        "year": 2022,
                        "subtitles_count": 3,
                    },
                ],
            }
        if params["sd_id"] == "bad":
            raise forbidden
        return {
            "status": True,
            "subtitles": [
                {
                    "id": 3576745,
                    "language": "English",
                    "name": "From.S04E01.1080p.WEB",
                    "season": 4,
                    "episode": 1,
                    "downloads": 5,
                    "url": "/subtitle/3576745-8495217.zip",
                }
            ],
        }

    monkeypatch.setattr(provider, "_fetch_api", fake_fetch_api)

    catalog = await provider.search_catalog("from", "en")

    assert [match.title for match in catalog.matches] == ["From", "From: Blocked"]
    assert len(catalog.results) == 1
    assert catalog.results[0].episode == 1
    assert catalog.warnings == [
        "SubDL: authentication failed (HTTP 403). Check the saved API key or token."
    ]


@pytest.mark.asyncio
async def test_subdl_search_suppresses_non_auth_detail_misses_when_results_survive(
    monkeypatch,
) -> None:
    provider = SubdlProvider(AppConfig(subdl_api_key="subdl-key"))

    async def fake_fetch_api(client, params: dict[str, object]) -> dict[str, object]:
        if "film_name" in params:
            return {
                "status": True,
                "results": [
                    {"sd_id": 1, "name": "From", "type": "tv", "year": 2022, "subtitles_count": 7},
                    {
                        "sd_id": 2,
                        "name": "From Out",
                        "type": "movie",
                        "year": 2016,
                        "subtitles_count": 1,
                    },
                ],
            }
        if str(params["sd_id"]) == "2":
            raise SubtitleSourceError("can't find movie or tv")
        return {
            "status": True,
            "subtitles": [
                {
                    "id": 3576745,
                    "language": "English",
                    "name": "From.S04E01.1080p.WEB",
                    "season": 4,
                    "episode": 1,
                    "downloads": 5,
                    "url": "/subtitle/3576745-8495217.zip",
                }
            ],
        }

    monkeypatch.setattr(provider, "_fetch_api", fake_fetch_api)

    catalog = await provider.search_catalog("from", "en")

    assert len(catalog.results) == 1
    assert catalog.warnings == []


@pytest.mark.asyncio
async def test_subdl_search_returns_safe_warning_when_root_fetch_forbidden(monkeypatch) -> None:
    provider = SubdlProvider(AppConfig(subdl_api_key="subdl-key"))
    request = httpx.Request(
        "GET", "https://api.subdl.com/api/v1/subtitles?api_key=subdl-key&film_name=from"
    )
    forbidden = httpx.HTTPStatusError(
        "Client error '403 Forbidden'",
        request=request,
        response=httpx.Response(403, request=request),
    )

    async def fake_fetch_api(client, params: dict[str, object]) -> dict[str, object]:
        raise forbidden

    monkeypatch.setattr(provider, "_fetch_api", fake_fetch_api)

    catalog = await provider.search_catalog("from", "en")

    assert catalog.matches == []
    assert catalog.results == []
    assert catalog.warnings == [
        "SubDL: authentication failed (HTTP 403). Check the saved API key or token."
    ]


@pytest.mark.asyncio
async def test_subdl_search_reraises_unknown_detail_fetch_errors(monkeypatch) -> None:
    provider = SubdlProvider(AppConfig(subdl_api_key="subdl-key"))

    async def fake_fetch_api(client, params: dict[str, object]) -> dict[str, object]:
        if "film_name" in params:
            return {
                "status": True,
                "results": [
                    {"sd_id": 1, "name": "From", "type": "tv", "year": 2022, "subtitles_count": 7}
                ],
            }
        raise RuntimeError("subdl detail exploded")

    monkeypatch.setattr(provider, "_fetch_api", fake_fetch_api)

    with pytest.raises(RuntimeError, match="subdl detail exploded"):
        await provider.search_catalog("from", "en")


def test_subdl_api_parser_expands_unpacked_season_files() -> None:
    provider = SubdlProvider(AppConfig(subdl_api_key="subdl-key"))

    results = provider._parse_api_subtitles(
        title="From",
        year=2022,
        match_id="subdl-match-1656864",
        requested_languages={"en"},
        item={"sd_id": 1656864, "type": "tv", "name": "From"},
        subtitles=[
            {
                "id": 3576745,
                "language": "English",
                "name": "From.Season.4.Pack.zip",
                "url": "/subtitle/3576745-8495217.zip",
                "season": 4,
                "episode_from": 1,
                "episode_end": 2,
                "full_season": True,
                "unpack_files": [
                    {
                        "file_n_id": "s04e01",
                        "name": "From.S04E01.srt",
                        "season": 4,
                        "episode": 1,
                        "language": "EN",
                        "url": "/subtitle/3576745/s04e01",
                    },
                    {
                        "file_n_id": "s04e02",
                        "name": "From.S04E02.srt",
                        "season": 4,
                        "episode": 2,
                        "language": "EN",
                        "url": "/subtitle/3576745/s04e02",
                    },
                ],
            }
        ],
    )

    assert [(result.season, result.episode) for result in results] == [(4, 1), (4, 2)]
    assert len({result.id for result in results}) == 2
    assert results[0].download_ref == "3576745/s04e01"
    assert results[0].raw["pack_link"] == "/subtitle/3576745-8495217.zip"
    assert results[1].file_name == "From.S04E02.srt"


def test_subdl_api_parser_scopes_unpacked_ids_by_pack() -> None:
    provider = SubdlProvider(AppConfig(subdl_api_key="subdl-key"))

    results = provider._parse_api_subtitles(
        title="From",
        year=2022,
        match_id="subdl-match-1656864",
        requested_languages={"en"},
        item={"sd_id": 1656864, "type": "tv", "name": "From"},
        subtitles=[
            {
                "id": 111,
                "language": "English",
                "name": "Pack A",
                "url": "/subtitle/111.zip",
                "unpack_files": [
                    {
                        "file_n_id": "s04e01",
                        "name": "From.S04E01.A.srt",
                        "season": 4,
                        "episode": 1,
                        "language": "EN",
                    }
                ],
            },
            {
                "id": 222,
                "language": "English",
                "name": "Pack B",
                "url": "/subtitle/222.zip",
                "unpack_files": [
                    {
                        "file_n_id": "s04e01",
                        "name": "From.S04E01.B.srt",
                        "season": 4,
                        "episode": 1,
                        "language": "EN",
                    }
                ],
            },
        ],
    )

    assert [result.id for result in results] == [
        "subdl-result-111-s04e01",
        "subdl-result-222-s04e01",
    ]


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


def test_aggregator_work_sort_prefers_exact_title_before_prefix_without_exact_series() -> None:
    aggregator = SubtitleSearchAggregator(AppConfig())
    works = [
        AggregatedWork(
            id="prefix-movie",
            title="From Paris with Love",
            media_type="movie",
            year=2010,
            year_end=None,
            imdb_id="tt1179034",
            tmdb_id="26389",
            providers=("opensubtitles",),
            provider_labels=("OpenSubtitles",),
            total_subtitles=344,
            match_score=396.0,
        ),
        AggregatedWork(
            id="exact-movie",
            title="From",
            media_type="movie",
            year=2026,
            year_end=None,
            imdb_id=None,
            tmdb_id="2964302",
            providers=("opensubtitles",),
            provider_labels=("OpenSubtitles",),
            total_subtitles=5,
            match_score=230.0,
        ),
    ]

    assert aggregator._sort_works(works, "from")[0].id == "exact-movie"


@pytest.mark.asyncio
async def test_assrt_search_extracts_exact_english_parent_title_for_cjk_episode(mocker) -> None:
    config = AppConfig(assrt_enabled=True, assrt_token="token")
    provider = AssrtProvider(config)
    mocker.patch.object(
        provider,
        "_request",
        new=mocker.AsyncMock(
            return_value={
                "status": 0,
                "sub": {
                    "subs": [
                        {
                            "id": 1,
                            "native_name": "梦魇绝镇 第四季 From (2026) S04E05",
                            "videoname": "梦魇绝镇 第四季 From (2026) S04E05",
                            "lang": {"desc": "简体中文", "langlist": {"langchs": 1}},
                            "down_count": 2,
                            "filelist": [{"f": "From.S04E05.zh.srt"}],
                        },
                        {
                            "id": 2,
                            "native_name": "怪奇物语：1985故事集 Stranger Things: Tales From '85 (2026) S01E02",
                            "videoname": "Stranger Things: Tales From '85 (2026) S01E02",
                            "lang": {"desc": "简体中文", "langlist": {"langchs": 1}},
                            "down_count": 1,
                            "filelist": [{"f": "Stranger.Things.Tales.From.85.S01E02.zh.srt"}],
                        },
                    ]
                },
            }
        ),
    )

    catalog = await provider.search_catalog("from", "zh")

    assert catalog.results[0].parent_title == "From"
    assert catalog.results[0].title == "From"
    assert catalog.results[0].media_type == "episode"
    assert catalog.results[0].season == 4
    assert catalog.results[0].episode == 5
    assert catalog.results[1].parent_title != "From"


@pytest.mark.asyncio
async def test_assrt_search_strips_episode_marker_from_hydration_query_filelist(mocker) -> None:
    config = AppConfig(assrt_enabled=True, assrt_token="token")
    provider = AssrtProvider(config)
    mocker.patch.object(
        provider,
        "_request",
        new=mocker.AsyncMock(
            return_value={
                "status": 0,
                "sub": {
                    "subs": [
                        {
                            "id": 3,
                            "native_name": "Release pack",
                            "videoname": "",
                            "lang": {"desc": "简体中文", "langlist": {"langchs": 1}},
                            "down_count": 4,
                            "filelist": [
                                {"f": "README.nfo"},
                                {
                                    "f": "From S03E01 Shatter 1080p AMZN WEB-DL DDP5 1 H 264-FLUX.ass"
                                },
                            ],
                        }
                    ]
                },
            }
        ),
    )

    catalog = await provider.search_catalog("From S03E01", "zh")

    assert catalog.results[0].parent_title == "From"
    assert catalog.results[0].title == "From"
    assert catalog.results[0].media_type == "episode"
    assert catalog.results[0].season == 3
    assert catalog.results[0].episode == 1
    assert catalog.results[0].file_name.endswith(".ass")


@pytest.mark.asyncio
async def test_aggregator_groups_assrt_exact_from_episodes_under_series() -> None:
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider(
            "opensubtitles",
            "OpenSubtitles",
            ProviderSearchCatalog(
                matches=[
                    ProviderSubtitleMatch(
                        id="os-prefix",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="From Paris with Love",
                        year=2010,
                        imdb_id="tt1179034",
                        tmdb_id="26389",
                        media_type="movie",
                        subtitles_count=344,
                        match_score=396.0,
                    )
                ],
                results=[],
            ),
        ),
        FakeProvider(
            "assrt",
            "ASSRT",
            ProviderSearchCatalog(
                matches=[],
                results=[
                    ProviderSubtitleResult(
                        id="assrt-from-5",
                        match_id="assrt-from-5",
                        provider="assrt",
                        provider_label="ASSRT",
                        title="From",
                        year=2026,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="episode",
                        season=4,
                        episode=5,
                        parent_title="From",
                        language="zh",
                        download_count=2,
                        file_name="From.S04E05.zh.srt",
                        match_score=220,
                    ),
                    ProviderSubtitleResult(
                        id="assrt-from-4",
                        match_id="assrt-from-4",
                        provider="assrt",
                        provider_label="ASSRT",
                        title="From",
                        year=2026,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="episode",
                        season=4,
                        episode=4,
                        parent_title="From",
                        language="zh",
                        download_count=1,
                        file_name="From.S04E04.zh.srt",
                        match_score=220,
                    ),
                ],
            ),
        ),
    )

    catalog = await aggregator.search_catalog("from", "en,zh")

    assert catalog.works[0].title == "From"
    assert catalog.works[0].media_type == "series"
    assert catalog.works[0].total_episodes == 2
    assert catalog.works[1].title == "From Paris with Love"


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
    assert "ASSRT: boom" in catalog.warnings


@pytest.mark.asyncio
async def test_aggregator_redacts_provider_error_secrets() -> None:
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider(
            "opensubtitles",
            "OpenSubtitles",
            ProviderSearchCatalog(
                matches=[],
                results=[
                    ProviderSubtitleResult(
                        id="result-1",
                        match_id="match-1",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="Movie",
                        year=None,
                        imdb_id=None,
                        media_type="movie",
                        language="en",
                        download_count=10,
                        file_name="movie.srt",
                    )
                ],
            ),
        ),
        FakeProvider(
            "subdl",
            "SubDL",
            error=RuntimeError(
                "GET https://api.subdl.com/api/v1/subtitles?api_key=secret-value&q=from failed"
            ),
        ),
    )

    catalog = await aggregator.search_catalog("Movie", "en")

    assert any("api_key=[redacted]" in warning for warning in catalog.warnings)
    assert all("secret-value" not in warning for warning in catalog.warnings)


@pytest.mark.asyncio
async def test_aggregator_turns_provider_auth_status_into_safe_warning() -> None:
    request = httpx.Request(
        "GET", "https://api.subdl.com/api/v1/subtitles?api_key=secret-value&q=from"
    )
    response = httpx.Response(403, request=request)
    error = httpx.HTTPStatusError(
        "Client error '403 Forbidden' for url 'https://api.subdl.com/api/v1/subtitles?api_key=secret-value&q=from'",
        request=request,
        response=response,
    )
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider(
            "opensubtitles",
            "OpenSubtitles",
            ProviderSearchCatalog(
                matches=[],
                results=[
                    ProviderSubtitleResult(
                        id="result-1",
                        match_id="match-1",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="Movie",
                        year=None,
                        imdb_id=None,
                        media_type="movie",
                        language="en",
                        download_count=10,
                        file_name="movie.srt",
                    )
                ],
            ),
        ),
        FakeProvider("subdl", "SubDL", error=error),
    )

    catalog = await aggregator.search_catalog("Movie", "en")

    assert (
        "SubDL: authentication failed (HTTP 403). Check the saved API key or token."
        in catalog.warnings
    )
    assert all("secret-value" not in warning for warning in catalog.warnings)


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


class HangingProvider(FakeProvider):
    """Answers only after the deadline the aggregator gives it."""

    def __init__(self, delay: float = 5.0):
        super().__init__("hanging", "Hanging", ProviderSearchCatalog(matches=[], results=[]))
        self._delay = delay

    async def search_catalog(self, query: str, languages: str) -> ProviderSearchCatalog:
        await asyncio.sleep(self._delay)
        return await super().search_catalog(query, languages)


def _catalog_with_one_result(code: str, label: str) -> ProviderSearchCatalog:
    return ProviderSearchCatalog(
        matches=[
            ProviderSubtitleMatch(
                id=f"{code}-match-1",
                provider=code,
                provider_label=label,
                title="Rick and Morty",
                year=2019,
                imdb_id=None,
                tmdb_id=None,
                media_type="episode",
                season=4,
                episode=8,
                parent_title="Rick and Morty",
                subtitles_count=1,
                match_score=90.0,
            )
        ],
        results=[
            ProviderSubtitleResult(
                id=f"{code}-result-1",
                match_id=f"{code}-match-1",
                provider=code,
                provider_label=label,
                title="Rick and Morty",
                year=2019,
                imdb_id=None,
                media_type="episode",
                language="en",
                download_count=10,
                file_name="rick.srt",
                season=4,
                episode=8,
                parent_title="Rick and Morty",
                tmdb_id=None,
                match_score=90.0,
                download_ref=None,
                raw={},
            )
        ],
    )


@pytest.mark.asyncio
async def test_a_hanging_provider_does_not_hold_back_the_ones_that_answered(monkeypatch) -> None:
    monkeypatch.setattr(aggregator_module, "PROVIDER_SEARCH_DEADLINE_S", 0.2)
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider("subdl", "SubDL", _catalog_with_one_result("subdl", "SubDL")),
        HangingProvider(delay=5.0),
    )

    catalog = await asyncio.wait_for(aggregator.search_catalog("Rick and Morty", "en"), timeout=3.0)

    assert [result.provider for result in catalog.results] == ["subdl"]
    assert any("Hanging" in warning for warning in catalog.warnings)


@pytest.mark.asyncio
async def test_every_provider_failing_reports_which_ones_and_why() -> None:
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider("subdl", "SubDL", error=RuntimeError("429 Too Many Requests")),
        FakeProvider("assrt", "ASSRT", error=RuntimeError("connection refused")),
    )

    with pytest.raises(SubtitleSourceError) as excinfo:
        await aggregator.search_catalog("Rick and Morty", "en")

    message = str(excinfo.value)
    assert "SubDL" in message and "429" in message
    assert "ASSRT" in message and "connection refused" in message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ConnectTimeout(""), "could not be reached"),
        (TimeoutError(), "took too long"),
        (httpx.ReadTimeout(""), "took too long"),
    ],
)
async def test_a_wordless_provider_failure_still_says_what_happened(error, expected) -> None:
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider("subdl", "SubDL", _catalog_with_one_result("subdl", "SubDL")),
        FakeProvider("assrt", "ASSRT", error=error),
    )

    catalog = await aggregator.search_catalog("Rick and Morty", "en")

    warning = next(w for w in catalog.warnings if w.startswith("ASSRT"))
    assert expected in warning


class ConnectFailingProvider(FakeProvider):
    """Counts how many times the aggregator actually dialled it."""

    def __init__(self):
        super().__init__("assrt", "ASSRT", ProviderSearchCatalog(matches=[], results=[]))
        self.calls = 0

    async def search_catalog(self, query: str, languages: str) -> ProviderSearchCatalog:
        self.calls += 1
        raise httpx.ConnectTimeout("")


@pytest.mark.asyncio
async def test_an_unreachable_provider_is_not_dialled_on_every_later_search() -> None:
    aggregator_module.provider_availability.reset()
    unreachable = ConnectFailingProvider()
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider("subdl", "SubDL", _catalog_with_one_result("subdl", "SubDL")),
        unreachable,
    )

    for _ in range(4):
        await aggregator.search_catalog("Rick and Morty", "en")

    assert unreachable.calls == aggregator_module.CONNECT_FAILURES_BEFORE_SKIP


@pytest.mark.asyncio
async def test_a_skipped_provider_still_tells_the_user_it_is_missing() -> None:
    aggregator_module.provider_availability.reset()
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider("subdl", "SubDL", _catalog_with_one_result("subdl", "SubDL")),
        ConnectFailingProvider(),
    )

    for _ in range(3):
        catalog = await aggregator.search_catalog("Rick and Morty", "en")

    assert "ASSRT: could not be reached." in catalog.warnings


@pytest.mark.asyncio
async def test_a_provider_that_answers_with_an_error_is_still_dialled_again() -> None:
    # A 429 or a bad response proves the host is reachable; only a failure to
    # connect at all means dialling again is wasted time.
    aggregator_module.provider_availability.reset()
    rate_limited = FakeProvider("assrt", "ASSRT", error=RuntimeError("429 Too Many Requests"))
    calls = {"n": 0}
    original = rate_limited.search_catalog

    async def counting(query: str, languages: str):
        calls["n"] += 1
        return await original(query, languages)

    rate_limited.search_catalog = counting
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider("subdl", "SubDL", _catalog_with_one_result("subdl", "SubDL")),
        rate_limited,
    )

    for _ in range(4):
        await aggregator.search_catalog("Rick and Morty", "en")

    assert calls["n"] == 4


@pytest.mark.parametrize(
    "title",
    [
        "Rick.and.Morty.S03E01.1080p.BluRay.x264-YELLOWBiRD.srt",
        "Rick.and.Morty.S04E08.720p.WEB-DL.x265",
        "rick and morty s02e01 hdtv x264-batv",
    ],
)
def test_release_names_are_not_offered_as_episode_titles(title) -> None:
    assert looks_like_release_name(title)


@pytest.mark.parametrize(
    "title",
    [
        "The Vat of Acid Episode",
        "Edge of Tomorty: Rick Die Rickpeat",
        "M. Night Shaym-Aliens!",
        "Pickle Rick",
    ],
)
def test_real_episode_titles_survive(title) -> None:
    assert not looks_like_release_name(title)


@pytest.mark.asyncio
async def test_a_season_built_from_release_names_shows_plain_episode_numbers() -> None:
    aggregator_module.provider_availability.reset()
    catalog = _catalog_with_one_result("subdl", "SubDL")
    catalog.matches[0].title = "Rick.and.Morty.S04E08.1080p.WEB-DL.x264-GROUP.srt"
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (FakeProvider("subdl", "SubDL", catalog),)

    aggregated = await aggregator.search_catalog("Rick and Morty", "en")

    episodes = [
        ep for work in aggregated.works for season in work.seasons for ep in season.episodes
    ]
    assert episodes and all(ep.title == "" for ep in episodes)


class GatedProvider(FakeProvider):
    """Only answers once the test releases it, so completion order is deterministic."""

    def __init__(self, code: str, label: str, catalog: ProviderSearchCatalog, gate: asyncio.Event):
        super().__init__(code, label, catalog)
        self._gate = gate

    async def search_catalog(self, query: str, languages: str) -> ProviderSearchCatalog:
        await self._gate.wait()
        return await super().search_catalog(query, languages)


@pytest.mark.asyncio
async def test_progressive_updates_land_per_provider_with_ids_stable_into_the_final_merge() -> None:
    aggregator_module.provider_availability.reset()
    gate = asyncio.Event()
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider("subdl", "SubDL", _catalog_with_one_result("subdl", "SubDL")),
        GatedProvider("assrt", "ASSRT", _catalog_with_one_result("assrt", "ASSRT"), gate),
    )

    updates: list[tuple[list[str], ProviderSearchCatalog]] = []

    async def on_update(succeeded_codes: list[str], settled_codes: list[str], interim) -> None:
        updates.append((list(succeeded_codes), interim))
        assert succeeded_codes == settled_codes  # No provider fails in this test.
        if len(updates) == 1:
            gate.set()  # Let ASSRT answer only after SubDL's interim update landed.

    final = await aggregator.search_catalog("Rick and Morty", "en", on_provider_update=on_update)

    assert len(updates) == 2
    first_done, first_interim = updates[0]
    second_done, second_interim = updates[1]
    assert first_done == ["subdl"]
    assert sorted(second_done) == ["assrt", "subdl"]

    # SubDL's interim result is shown before ASSRT answers.
    assert len(first_interim.matches) == 1
    assert first_interim.matches[0].providers == ("subdl",)

    # The final merge folds ASSRT into the same episode, but keeps the id the
    # interim update already showed the user — nothing the user clicked on
    # while SubDL-only results were on screen becomes stale.
    assert len(second_interim.matches) == 1
    assert first_interim.matches[0].id == second_interim.matches[0].id == final.matches[0].id
    assert sorted(final.matches[0].providers) == ["assrt", "subdl"]


def _movie_catalog(code: str, label: str, title: str) -> ProviderSearchCatalog:
    return ProviderSearchCatalog(
        matches=[
            ProviderSubtitleMatch(
                id=f"{code}-match-1",
                provider=code,
                provider_label=label,
                title=title,
                year=2019,
                imdb_id=None,
                tmdb_id=None,
                media_type="movie",
                season=None,
                episode=None,
                parent_title=None,
                subtitles_count=1,
                match_score=90.0,
            )
        ],
        results=[
            ProviderSubtitleResult(
                id=f"{code}-result-1",
                match_id=f"{code}-match-1",
                provider=code,
                provider_label=label,
                title=title,
                year=2019,
                imdb_id=None,
                media_type="movie",
                language="en",
                download_count=10,
                file_name=f"{code}.srt",
                season=None,
                episode=None,
                parent_title=None,
                tmdb_id=None,
                match_score=90.0,
                download_ref=None,
                raw={},
            )
        ],
    )


@pytest.mark.asyncio
async def test_a_late_provider_does_not_renumber_works_the_user_can_already_see() -> None:
    """A provider that answers last must not change the identity of a visible card.

    Interim merges keep providers in a fixed order, so a provider listed early
    but answering late inserts its works ahead of a later provider's. With
    positional ids that silently repointed a card the user was already looking
    at at something else.
    """
    aggregator_module.provider_availability.reset()
    gate = asyncio.Event()
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider("subdl", "SubDL", _movie_catalog("subdl", "SubDL", "Rick and Morty")),
        GatedProvider("assrt", "ASSRT", _movie_catalog("assrt", "ASSRT", "Solar Opposites"), gate),
        FakeProvider(
            "opensubtitles",
            "OpenSubtitles",
            _movie_catalog("opensubtitles", "OpenSubtitles", "Bojack Horseman"),
        ),
    )

    interim_ids: list[dict[str, str]] = []
    interim_result_ids: list[dict[str, str]] = []

    async def on_update(succeeded_codes, settled_codes, interim) -> None:
        interim_ids.append({work.title: work.id for work in interim.works})
        interim_result_ids.append({r.file_name: r.result_id for r in interim.results})
        if "opensubtitles" in succeeded_codes and "assrt" not in succeeded_codes:
            gate.set()  # ASSRT answers only after the user can see the other two.

    final = await aggregator.search_catalog("movies", "en", on_provider_update=on_update)

    final_ids = {work.title: work.id for work in final.works}
    assert set(final_ids) == {"Rick and Morty", "Solar Opposites", "Bojack Horseman"}
    # Every card the user could already see keeps the identity it was shown with,
    # including the one ASSRT's late answer pushed down the merged list.
    assert any("Bojack Horseman" in snapshot for snapshot in interim_ids)
    for snapshot in interim_ids:
        for title, work_id in snapshot.items():
            assert final_ids[title] == work_id

    # Same for the subtitle files themselves: the studio remembers the picked
    # source by result id, so a shifted id downloads a different file.
    final_result_ids = {r.file_name: r.result_id for r in final.results}
    for snapshot in interim_result_ids:
        for file_name, result_id in snapshot.items():
            assert final_result_ids[file_name] == result_id


@pytest.mark.asyncio
async def test_a_failing_provider_is_settled_even_though_it_never_succeeds() -> None:
    """A provider that errors out must still drop off "still waiting on...".

    Only successes went into the done list at first, so a failed provider
    stayed "pending" forever even after it had already given up.
    """
    aggregator_module.provider_availability.reset()
    aggregator = SubtitleSearchAggregator(AppConfig())
    aggregator.providers = (
        FakeProvider("subdl", "SubDL", _catalog_with_one_result("subdl", "SubDL")),
        FakeProvider("assrt", "ASSRT", error=RuntimeError("connection refused")),
    )

    updates: list[tuple[list[str], list[str]]] = []

    async def on_update(succeeded_codes, settled_codes, interim) -> None:
        updates.append((list(succeeded_codes), list(settled_codes)))

    await aggregator.search_catalog("Rick and Morty", "en", on_provider_update=on_update)

    assert len(updates) == 2
    succeeded, settled = updates[-1]
    assert succeeded == ["subdl"]
    assert sorted(settled) == ["assrt", "subdl"]


def test_a_source_switched_off_is_never_dialled() -> None:
    """A disabled provider used to answer with an empty catalog.

    That counted as an answer: the progress line credited it, and the search
    spent one of the account's request slots to be told nothing.
    """
    aggregator = SubtitleSearchAggregator(
        AppConfig(assrt_enabled=False, subdl_enabled=True, opensubtitles_enabled=True)
    )
    codes = [provider.provider_code for provider in aggregator.providers]
    assert "assrt" not in codes
    assert sorted(codes) == ["opensubtitles", "subdl"]


@pytest.mark.asyncio
async def test_switching_every_source_off_says_so_rather_than_reporting_failure() -> None:
    aggregator = SubtitleSearchAggregator(
        AppConfig(assrt_enabled=False, subdl_enabled=False, opensubtitles_enabled=False)
    )
    assert aggregator.providers == ()
    with pytest.raises(SubtitleSourceError) as excinfo:
        await aggregator.search_catalog("Rick and Morty", "en")
    assert "switched off" in str(excinfo.value)
