"""Tests for the TMDb client and its integration into the search aggregator."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from meocosub2.config import AppConfig
from meocosub2.subtitle_sources.aggregator import SubtitleSearchAggregator
from meocosub2.subtitle_sources.season_skeleton import build_season_skeleton
from meocosub2.subtitle_sources.tmdb import TMDbCache, TMDbClient, TMDbSeries
from meocosub2.subtitle_sources.types import (
    AggregatedEpisode,
    AggregatedSeason,
    ProviderSearchCatalog,
    ProviderSubtitleMatch,
    ProviderSubtitleResult,
)


class _FakeProvider:
    def __init__(self, code: str, label: str, catalog: ProviderSearchCatalog) -> None:
        self.provider_code = code
        self.provider_label = label
        self._catalog = catalog

    async def search_catalog(self, query: str, languages: str) -> ProviderSearchCatalog:
        return self._catalog

    async def download(self, result: ProviderSubtitleResult) -> Path:
        return Path(result.file_name)


class _StubTMDb:
    """In-memory TMDb double; avoids network and cache side effects."""

    def __init__(
        self,
        search_hits: dict[str, TMDbSeries] | None = None,
        imdb_hits: dict[str, TMDbSeries] | None = None,
        series_details: dict[int, dict] | None = None,
        season_episodes: dict[tuple[int, int], list[dict]] | None = None,
    ) -> None:
        self.enabled = True
        self._search_hits = search_hits or {}
        self._imdb_hits = imdb_hits or {}
        self._series_details = series_details or {}
        self._season_episodes = season_episodes or {}
        self.cache = _NullCache()
        self.searches: list[str] = []
        self.imdb_queries: list[str] = []

    async def search_tv(self, query: str, year_hint: int | None = None) -> TMDbSeries | None:
        self.searches.append(query)
        return self._search_hits.get(query.lower())

    async def find_by_imdb(self, imdb_id: str) -> TMDbSeries | None:
        self.imdb_queries.append(imdb_id)
        return self._imdb_hits.get(imdb_id)

    async def fetch_series_details(self, tmdb_id: int) -> dict | None:
        return self._series_details.get(tmdb_id)

    async def fetch_season(self, tmdb_id: int, season_number: int) -> list[dict]:
        return self._season_episodes.get((tmdb_id, season_number), [])

    async def fetch_poster_url(self, tmdb_id: int, media_type: str) -> str | None:
        return None


class _NullCache:
    def flush(self) -> None:  # pragma: no cover - trivial
        return None


@pytest.mark.asyncio
async def test_tmdb_client_search_returns_best_match_and_caches(tmp_path: Path) -> None:
    cache = TMDbCache(tmp_path / "cache.json")
    client = TMDbClient("secret-key", cache=cache)
    with respx.mock(base_url="https://api.themoviedb.org/3") as router:
        router.get("/search/tv").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": 99999,
                            "name": "Wrong Show",
                            "original_name": "Wrong",
                            "first_air_date": "2001-01-01",
                            "popularity": 1.0,
                        },
                        {
                            "id": 64196,
                            "name": "Overlord",
                            "original_name": "オーバーロード",
                            "first_air_date": "2015-07-07",
                            "poster_path": "/overlord.jpg",
                            "popularity": 80.0,
                        },
                    ]
                },
            )
        )
        router.get("/tv/64196/external_ids").mock(
            return_value=httpx.Response(
                200, json={"imdb_id": "tt4869896"}
            )
        )
        hit = await client.search_tv("Overlord", year_hint=2015)
        cached = await client.search_tv("Overlord", year_hint=2015)
        # Second call must hit cache: only one search + one external_ids call.
        assert router.calls.call_count == 2

    assert hit is not None
    assert hit.tmdb_id == 64196
    assert hit.imdb_id == "tt4869896"
    assert hit.poster_path == "/overlord.jpg"
    assert cached == hit
    await client.close()


@pytest.mark.asyncio
async def test_tmdb_client_returns_none_on_http_error(tmp_path: Path) -> None:
    cache = TMDbCache(tmp_path / "cache.json")
    client = TMDbClient("secret-key", cache=cache)
    with respx.mock(base_url="https://api.themoviedb.org/3") as router:
        router.get("/search/tv").mock(return_value=httpx.Response(500))
        assert await client.search_tv("Overlord") is None
    await client.close()


@pytest.mark.asyncio
async def test_tmdb_client_disabled_when_no_api_key(tmp_path: Path) -> None:
    cache = TMDbCache(tmp_path / "cache.json")
    client = TMDbClient("", cache=cache)
    assert client.enabled is False
    assert await client.search_tv("Overlord") is None
    await client.close()


@pytest.mark.asyncio
async def test_aggregator_merges_cross_lingual_series_via_tmdb() -> None:
    overlord_series = TMDbSeries(
        tmdb_id=64196,
        imdb_id="tt4869896",
        name="Overlord",
        original_name="オーバーロード",
        first_air_year=2015,
    )
    stub = _StubTMDb(
        search_hits={
            "overlord": overlord_series,
            "オーバーロード": overlord_series,
        },
    )
    config = AppConfig(tmdb_api_key="dummy", tmdb_merge_enabled=True)
    aggregator = SubtitleSearchAggregator(config, tmdb_client=stub)
    aggregator.providers = (
        _FakeProvider(
            "subdl",
            "SubDL",
            ProviderSearchCatalog(
                matches=[
                    ProviderSubtitleMatch(
                        id="sd-series",
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
                ],
                results=[
                    ProviderSubtitleResult(
                        id="sd-result",
                        match_id="sd-series",
                        provider="subdl",
                        provider_label="SubDL",
                        title="Overlord",
                        year=2015,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="episode",
                        season=1,
                        episode=1,
                        parent_title="Overlord",
                        language="en",
                        download_count=200,
                        file_name="overlord.srt",
                    ),
                ],
            ),
        ),
        _FakeProvider(
            "opensubtitles",
            "OpenSubtitles",
            ProviderSearchCatalog(
                matches=[
                    ProviderSubtitleMatch(
                        id="os-series",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="オーバーロード",
                        year=2015,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="tvshow",
                        subtitles_count=61,
                        match_score=260.0,
                    ),
                ],
                results=[
                    ProviderSubtitleResult(
                        id="os-result",
                        match_id="os-series",
                        provider="opensubtitles",
                        provider_label="OpenSubtitles",
                        title="オーバーロード",
                        year=2015,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="episode",
                        season=1,
                        episode=1,
                        parent_title="オーバーロード",
                        language="ja",
                        download_count=50,
                        file_name="overlord-ja.srt",
                    ),
                ],
            ),
        ),
    )

    catalog = await aggregator.search_catalog("Overlord", "en,ja")

    series_works = [w for w in catalog.works if w.media_type == "series"]
    assert len(series_works) == 1, catalog.works
    work = series_works[0]
    assert work.tmdb_id == "64196"
    assert work.imdb_id == "tt4869896"
    assert work.poster_url is None
    assert "subdl" in work.providers
    assert "opensubtitles" in work.providers


@pytest.mark.asyncio
async def test_aggregator_applies_skeleton_for_single_series_without_tmdb_id() -> None:
    """A single series result with no provider-supplied tmdb_id still gets enriched
    and skeleton-merged. Regression for S1/S3 missing on Overlord searches.
    """
    overlord_series = TMDbSeries(
        tmdb_id=64196,
        imdb_id="tt4869896",
        name="Overlord",
        original_name="オーバーロード",
        first_air_year=2015,
    )
    stub = _StubTMDb(
        search_hits={"overlord": overlord_series},
        series_details={64196: {"number_of_seasons": 4, "poster_path": "/overlord.jpg"}},
        season_episodes={
            (64196, 1): [
                {"episode_number": 1, "name": "S1E1", "air_date": "2015-07-07"},
                {"episode_number": 2, "name": "S1E2", "air_date": "2015-07-14"},
            ],
            (64196, 2): [
                {"episode_number": 1, "name": "S2E1", "air_date": "2018-01-09"},
            ],
            (64196, 3): [
                {"episode_number": 1, "name": "S3E1", "air_date": "2018-07-10"},
            ],
            (64196, 4): [
                {"episode_number": 1, "name": "S4E1", "air_date": "2022-01-04"},
            ],
        },
    )
    config = AppConfig(tmdb_api_key="dummy", tmdb_merge_enabled=True)
    aggregator = SubtitleSearchAggregator(config, tmdb_client=stub)
    aggregator.providers = (
        _FakeProvider(
            "assrt",
            "ASSRT",
            ProviderSearchCatalog(
                matches=[
                    ProviderSubtitleMatch(
                        id="assrt-series",
                        provider="assrt",
                        provider_label="ASSRT",
                        title="Overlord",
                        year=2015,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="tvshow",
                        subtitles_count=1,
                        match_score=300.0,
                    ),
                    ProviderSubtitleMatch(
                        id="assrt-s2e1",
                        provider="assrt",
                        provider_label="ASSRT",
                        title="Overlord S02E01",
                        year=2018,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="episode",
                        season=2,
                        episode=1,
                        parent_title="Overlord",
                        subtitles_count=1,
                        match_score=290.0,
                    ),
                ],
                results=[
                    ProviderSubtitleResult(
                        id="assrt-result",
                        match_id="assrt-s2e1",
                        provider="assrt",
                        provider_label="ASSRT",
                        title="Overlord",
                        year=2015,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="episode",
                        season=2,
                        episode=1,
                        parent_title="Overlord",
                        language="en",
                        download_count=10,
                        file_name="overlord-s2e1.srt",
                    ),
                ],
            ),
        ),
    )

    catalog = await aggregator.search_catalog("Overlord", "en")

    series_works = [w for w in catalog.works if w.media_type == "series"]
    assert len(series_works) == 1
    work = series_works[0]
    assert work.tmdb_id == "64196"
    assert work.imdb_id == "tt4869896"
    assert work.poster_url == "https://image.tmdb.org/t/p/w92/overlord.jpg"

    season_numbers = sorted(s.season_number for s in work.seasons)
    assert season_numbers == [1, 2, 3, 4], "all four TMDb seasons should be present"

    by_season = {s.season_number: s for s in work.seasons}
    s1_ids = [ep.match_id for ep in by_season[1].episodes]
    assert s1_ids == ["skeleton:1:1", "skeleton:1:2"]
    assert all(ep.subtitles_count == 0 for ep in by_season[1].episodes)

    s2_ids = [ep.match_id for ep in by_season[2].episodes]
    assert any(not mid.startswith("skeleton:") for mid in s2_ids), "S2 keeps the real ASSRT episode"

    assert by_season[3].episodes[0].match_id == "skeleton:3:1"
    assert by_season[4].episodes[0].match_id == "skeleton:4:1"


@pytest.mark.asyncio
async def test_aggregator_skips_tmdb_when_disabled() -> None:
    config = AppConfig(tmdb_api_key="", tmdb_merge_enabled=True)
    aggregator = SubtitleSearchAggregator(config)
    assert aggregator._tmdb_client is None


# ---------------------------------------------------------------------------
# TMDbClient.fetch_season / fetch_series_details
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_season_returns_episode_list(tmp_path: Path) -> None:
    cache = TMDbCache(tmp_path / "cache.json")
    client = TMDbClient("key", cache=cache)
    episode_data = {
        "episodes": [
            {"episode_number": 1, "name": "Ep One", "air_date": "2015-07-07"},
            {"episode_number": 2, "name": "Ep Two", "air_date": "2015-07-14"},
        ]
    }
    with respx.mock(base_url="https://api.themoviedb.org/3") as router:
        router.get("/tv/64196/season/1").mock(
            return_value=httpx.Response(200, json=episode_data)
        )
        episodes = await client.fetch_season(64196, 1)
        cached = await client.fetch_season(64196, 1)
        assert router.calls.call_count == 1

    assert len(episodes) == 2
    assert episodes[0]["episode_number"] == 1
    assert episodes[0]["name"] == "Ep One"
    assert cached == episodes
    await client.close()


@pytest.mark.asyncio
async def test_fetch_season_returns_empty_on_404(tmp_path: Path) -> None:
    cache = TMDbCache(tmp_path / "cache.json")
    client = TMDbClient("key", cache=cache)
    with respx.mock(base_url="https://api.themoviedb.org/3") as router:
        router.get("/tv/99/season/5").mock(return_value=httpx.Response(404))
        episodes = await client.fetch_season(99, 5)
    assert episodes == []
    await client.close()


@pytest.mark.asyncio
async def test_fetch_series_details_returns_season_count(tmp_path: Path) -> None:
    cache = TMDbCache(tmp_path / "cache.json")
    client = TMDbClient("key", cache=cache)
    with respx.mock(base_url="https://api.themoviedb.org/3") as router:
        router.get("/tv/64196").mock(
            return_value=httpx.Response(
                200, json={"number_of_seasons": 4, "name": "Overlord", "poster_path": "/overlord.jpg"}
            )
        )
        details = await client.fetch_series_details(64196)
        cached = await client.fetch_series_details(64196)
        assert router.calls.call_count == 1

    assert details is not None
    assert details["number_of_seasons"] == 4
    assert details["poster_path"] == "/overlord.jpg"
    assert cached == details
    await client.close()


@pytest.mark.asyncio
async def test_fetch_poster_url_returns_tmdb_image_url(tmp_path: Path) -> None:
    cache = TMDbCache(tmp_path / "cache.json")
    client = TMDbClient("key", cache=cache)
    with respx.mock(base_url="https://api.themoviedb.org/3") as router:
        router.get("/movie/27205").mock(
            return_value=httpx.Response(200, json={"poster_path": "/inception.jpg"})
        )
        poster = await client.fetch_poster_url(27205, "movie")
        cached = await client.fetch_poster_url(27205, "movie")
        assert router.calls.call_count == 1

    assert poster == "https://image.tmdb.org/t/p/w92/inception.jpg"
    assert cached == poster
    await client.close()


# ---------------------------------------------------------------------------
# build_season_skeleton
# ---------------------------------------------------------------------------


def test_build_season_skeleton_fills_missing_seasons() -> None:
    tmdb_catalog = [
        (1, [{"episode_number": 1, "name": "Ep 1", "air_date": "2015-07-07"},
             {"episode_number": 2, "name": "Ep 2", "air_date": "2015-07-14"}]),
        (2, [{"episode_number": 1, "name": "S2 Ep 1", "air_date": "2016-07-05"}]),
    ]
    existing_seasons = [
        AggregatedSeason(
            season_number=2,
            episodes=[
                AggregatedEpisode(season=2, episode=1, title="S2 Ep 1", match_id="real-match", subtitles_count=10, providers=("subdl",))
            ],
            subtitles_count=10,
        )
    ]
    result = build_season_skeleton(tmdb_catalog, existing_seasons)

    assert len(result) == 2
    s1, s2 = result
    assert s1.season_number == 1
    assert len(s1.episodes) == 2
    assert s1.episodes[0].match_id == "skeleton:1:1"
    assert s1.episodes[0].subtitles_count == 0
    assert s1.episodes[1].match_id == "skeleton:1:2"

    assert s2.season_number == 2
    assert len(s2.episodes) == 1
    ep = s2.episodes[0]
    assert ep.match_id == "real-match"
    assert ep.subtitles_count == 10


def test_build_season_skeleton_preserves_season_packs() -> None:
    tmdb_catalog = [
        (1, [{"episode_number": 1, "name": "Ep 1", "air_date": "2015-07-07"}]),
    ]
    pack = AggregatedEpisode(season=1, episode=None, title="Season 1 Pack", match_id="pack-match", subtitles_count=5, providers=("subdl",))
    existing_seasons = [
        AggregatedSeason(season_number=1, episodes=[pack], subtitles_count=5)
    ]
    result = build_season_skeleton(tmdb_catalog, existing_seasons)

    assert len(result) == 1
    s1 = result[0]
    ep_ids = [ep.match_id for ep in s1.episodes]
    assert "pack-match" in ep_ids
    assert "skeleton:1:1" in ep_ids


def test_build_season_skeleton_preserves_extra_provider_seasons() -> None:
    tmdb_catalog = [(1, [{"episode_number": 1, "name": "Ep 1", "air_date": "2015-07-07"}])]
    extra = AggregatedSeason(
        season_number=0,
        episodes=[AggregatedEpisode(season=0, episode=1, title="Special", match_id="spec", subtitles_count=3, providers=())],
        subtitles_count=3,
    )
    existing_seasons = [extra]
    result = build_season_skeleton(tmdb_catalog, existing_seasons)

    season_numbers = [s.season_number for s in result]
    assert 0 in season_numbers
    assert 1 in season_numbers
