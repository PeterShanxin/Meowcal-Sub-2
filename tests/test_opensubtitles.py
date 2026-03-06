from pathlib import Path

import httpx
import pytest
import respx

from meocosub2.errors import OpenSubtitlesError
from meocosub2.opensubtitles.client import (
    BASE_URL,
    MAX_RETRIES,
    OpenSubtitlesClient,
    _OpenSubtitlesOrgAliasParser,
)

FEATURE_TVSHOW_RESPONSE = {
    "data": [
        {
            "id": "2239923",
            "type": "feature",
            "attributes": {
                "title": "fate/strange fake",
                "original_title": "Fate/strange Fake",
                "year": "2024",
                "subtitles_count": 9,
                "season_number": 0,
                "episode_number": None,
                "imdb_id": 32864316,
                "tmdb_id": 229858,
                "parent_title": "",
                "parent_imdb_id": None,
                "parent_tmdb_id": None,
                "title_aka": ["Fate/strange Fake"],
                "feature_type": "Tvshow",
            },
        }
    ]
}

FEATURE_ZERO_RESPONSE = {
    "data": [
        {
            "id": "127283",
            "type": "feature",
            "attributes": {
                "title": "fate/zero",
                "original_title": "Fate/Zero",
                "year": "2011",
                "subtitles_count": 12,
                "season_number": 0,
                "episode_number": None,
                "imdb_id": 2051178,
                "tmdb_id": 45845,
                "parent_title": "",
                "parent_imdb_id": None,
                "parent_tmdb_id": None,
                "title_aka": ["Fate/Zero"],
                "feature_type": "Tvshow",
            },
        }
    ]
}

FEATURE_MOVIE_RESPONSE = {
    "data": [
        {
            "id": "42",
            "type": "feature",
            "attributes": {
                "title": "inception",
                "original_title": "Inception",
                "year": "2010",
                "subtitles_count": 12,
                "season_number": None,
                "episode_number": None,
                "imdb_id": 1375666,
                "tmdb_id": 27205,
                "parent_title": "",
                "parent_imdb_id": None,
                "parent_tmdb_id": None,
                "title_aka": ["Inception"],
                "feature_type": "Movie",
            },
        }
    ]
}

FEATURE_SLASH_MOVIE_RESPONSE = {
    "data": [
        {
            "id": "314",
            "type": "feature",
            "attributes": {
                "title": "foo/bar",
                "original_title": "Foo/Bar",
                "year": "2020",
                "subtitles_count": 12,
                "season_number": None,
                "episode_number": None,
                "imdb_id": 3141592,
                "tmdb_id": 314,
                "parent_title": "",
                "parent_imdb_id": None,
                "parent_tmdb_id": None,
                "title_aka": ["Foo/Bar"],
                "feature_type": "Movie",
            },
        }
    ]
}

FEATURE_PARTIAL_SLASH_RESPONSE = {
    "data": [
        {
            "id": "2718",
            "type": "feature",
            "attributes": {
                "title": "the foo/bar show",
                "original_title": "The Foo/Bar Show",
                "year": "2020",
                "subtitles_count": 12,
                "season_number": None,
                "episode_number": None,
                "imdb_id": 2718,
                "tmdb_id": 2718,
                "parent_title": "",
                "parent_imdb_id": None,
                "parent_tmdb_id": None,
                "title_aka": ["The Foo/Bar Show"],
                "feature_type": "Movie",
            },
        }
    ]
}

TVSHOW_SUBTITLE_RESPONSE = {
    "data": [
        {
            "id": "11041820",
            "type": "subtitle",
            "attributes": {
                "language": "en",
                "download_count": 1959,
                "feature_details": {
                    "feature_id": 2399979,
                    "feature_type": "Episode",
                    "year": 2024,
                    "title": "The Heroic Spirit Incident",
                    "movie_name": "Fate/strange Fake - S01E01  The Heroic Spirit Incident",
                    "imdb_id": 34742962,
                    "tmdb_id": 6744143,
                    "season_number": 1,
                    "episode_number": 1,
                    "parent_imdb_id": 32864316,
                    "parent_title": "Fate/strange Fake",
                    "parent_tmdb_id": 229858,
                    "parent_feature_id": 2239923,
                },
                "files": [{"file_id": 11938126, "file_name": "Fate-strange Fake - S01E01.en"}],
            },
        }
    ]
}

ZERO_SUBTITLE_RESPONSE = {
    "data": [
        {
            "id": "200",
            "type": "subtitle",
            "attributes": {
                "language": "en",
                "download_count": 2500,
                "feature_details": {
                    "feature_id": 300,
                    "feature_type": "Episode",
                    "year": 2011,
                    "title": "The End of the Holy Grail War",
                    "movie_name": "Fate/Zero - S01E13  The End of the Holy Grail War",
                    "imdb_id": 2051178,
                    "tmdb_id": 1,
                    "season_number": 1,
                    "episode_number": 13,
                    "parent_imdb_id": 2051178,
                    "parent_title": "Fate/Zero",
                    "parent_tmdb_id": 45845,
                    "parent_feature_id": 127283,
                },
                "files": [{"file_id": 200, "file_name": "fate-zero.srt"}],
            },
        }
    ]
}

MOVIE_SUBTITLE_RESPONSE = {
    "data": [
        {
            "id": "123",
            "type": "subtitle",
            "attributes": {
                "language": "en",
                "download_count": 5000,
                "feature_details": {
                    "feature_id": 42,
                    "feature_type": "Movie",
                    "year": 2010,
                    "title": "Inception",
                    "movie_name": "Inception",
                    "imdb_id": 1375666,
                    "tmdb_id": 27205,
                    "season_number": None,
                    "episode_number": None,
                    "parent_imdb_id": None,
                    "parent_title": None,
                    "parent_tmdb_id": None,
                    "parent_feature_id": None,
                },
                "files": [{"file_id": 9001, "file_name": "Inception.srt"}],
            },
        }
    ]
}

SLASH_MOVIE_SUBTITLE_RESPONSE = {
    "data": [
        {
            "id": "314",
            "type": "subtitle",
            "attributes": {
                "language": "en",
                "download_count": 4000,
                "feature_details": {
                    "feature_id": 314,
                    "feature_type": "Movie",
                    "year": 2020,
                    "title": "Foo/Bar",
                    "movie_name": "Foo/Bar",
                    "imdb_id": 3141592,
                    "tmdb_id": 314,
                    "season_number": None,
                    "episode_number": None,
                    "parent_imdb_id": None,
                    "parent_title": None,
                    "parent_tmdb_id": None,
                    "parent_feature_id": None,
                },
                "files": [{"file_id": 314, "file_name": "foo-bar.srt"}],
            },
        }
    ]
}

PARTIAL_SLASH_MOVIE_SUBTITLE_RESPONSE = {
    "data": [
        {
            "id": "2718",
            "type": "subtitle",
            "attributes": {
                "language": "en",
                "download_count": 6000,
                "feature_details": {
                    "feature_id": 2718,
                    "feature_type": "Movie",
                    "year": 2020,
                    "title": "The Foo/Bar Show",
                    "movie_name": "The Foo/Bar Show",
                    "imdb_id": 2718,
                    "tmdb_id": 2718,
                    "season_number": None,
                    "episode_number": None,
                    "parent_imdb_id": None,
                    "parent_title": None,
                    "parent_tmdb_id": None,
                    "parent_feature_id": None,
                },
                "files": [{"file_id": 2718, "file_name": "foo-bar-show.srt"}],
            },
        }
    ]
}

EMPTY_RESPONSE = {"data": []}

DOWNLOAD_RESPONSE = {
    "link": "https://dl.opensubtitles.com/abc/Inception.srt",
    "file_name": "Inception.srt",
    "remaining": 19,
}


@pytest.fixture
def client(tmp_path: Path) -> OpenSubtitlesClient:
    return OpenSubtitlesClient(api_key="test-key", user_agent="Meowcal-Sub-2/0.1", cache_dir=tmp_path)


@respx.mock
@pytest.mark.asyncio
async def test_search_uses_feature_pipeline_and_alias_variants(client: OpenSubtitlesClient) -> None:
    feature_route = respx.get(f"{BASE_URL}/features").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=FEATURE_TVSHOW_RESPONSE
            if request.url.params.get("query") in {"Fate strange Fake", "Fate/strange Fake"}
            else EMPTY_RESPONSE,
        )
    )
    subtitle_route = respx.get(f"{BASE_URL}/subtitles").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=TVSHOW_SUBTITLE_RESPONSE
            if request.url.params.get("parent_feature_id") == "2239923"
            else EMPTY_RESPONSE,
        )
    )

    results = await client.search("Fate/Fake", languages="en")

    assert results
    assert results[0].parent_title == "Fate/strange Fake"
    assert results[0].display_label().startswith("Fate/strange Fake S01E01 - The Heroic Spirit Incident")
    queried_titles = {call.request.url.params.get("query") for call in feature_route.calls}
    assert "Fate strange Fake" in queried_titles
    assert "Fate/strange Fake" in queried_titles
    assert any(call.request.url.params.get("languages") == "en" for call in subtitle_route.calls)


@respx.mock
@pytest.mark.asyncio
async def test_search_preserves_unicode_queries(client: OpenSubtitlesClient) -> None:
    feature_route = respx.get(f"{BASE_URL}/features").mock(return_value=httpx.Response(200, json=EMPTY_RESPONSE))
    respx.get(f"{BASE_URL}/subtitles").mock(return_value=httpx.Response(200, json=EMPTY_RESPONSE))

    await client.search("君の名は", languages="ja")

    assert feature_route.called
    assert any(call.request.url.params.get("query") == "君の名は" for call in feature_route.calls)


@respx.mock
@pytest.mark.asyncio
async def test_search_does_not_generate_generic_slash_variant(client: OpenSubtitlesClient) -> None:
    feature_route = respx.get(f"{BASE_URL}/features").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=FEATURE_MOVIE_RESPONSE if request.url.params.get("query") == "Star Wars" else EMPTY_RESPONSE,
        )
    )
    respx.get(f"{BASE_URL}/subtitles").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=MOVIE_SUBTITLE_RESPONSE if request.url.params.get("id") == "42" else EMPTY_RESPONSE,
        )
    )

    await client.search("Star Wars", languages="en")

    queried_titles = {call.request.url.params.get("query") for call in feature_route.calls}
    assert "Star Wars" in queried_titles
    assert "Star/Wars" not in queried_titles


@respx.mock
@pytest.mark.asyncio
async def test_search_does_not_strip_leading_year_from_title(client: OpenSubtitlesClient) -> None:
    feature_route = respx.get(f"{BASE_URL}/features").mock(return_value=httpx.Response(200, json=EMPTY_RESPONSE))
    respx.get(f"{BASE_URL}/subtitles").mock(return_value=httpx.Response(200, json=EMPTY_RESPONSE))

    await client.search("2001: A Space Odyssey", languages="en")

    assert feature_route.called
    first_call = feature_route.calls[0].request
    assert first_call.url.params.get("query") == "2001: A Space Odyssey"
    assert "year" not in first_call.url.params


@respx.mock
@pytest.mark.asyncio
async def test_search_uses_slash_variant_after_weak_initial_results(client: OpenSubtitlesClient) -> None:
    feature_route = respx.get(f"{BASE_URL}/features").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=FEATURE_ZERO_RESPONSE if request.url.params.get("query") == "Fate/Zero" else EMPTY_RESPONSE,
        )
    )
    respx.get(f"{BASE_URL}/subtitles").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=ZERO_SUBTITLE_RESPONSE if request.url.params.get("parent_feature_id") == "127283" else EMPTY_RESPONSE,
        )
    )

    results = await client.search("Fate Zero", languages="en")

    queried_titles = {call.request.url.params.get("query") for call in feature_route.calls}
    assert "Fate/Zero" in queried_titles
    assert results
    assert results[0].parent_title == "Fate/Zero"


@respx.mock
@pytest.mark.asyncio
async def test_search_uses_generic_slash_retry_only_after_empty_results(client: OpenSubtitlesClient) -> None:
    feature_route = respx.get(f"{BASE_URL}/features").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=FEATURE_SLASH_MOVIE_RESPONSE if request.url.params.get("query") == "Foo/Bar" else EMPTY_RESPONSE,
        )
    )
    respx.get(f"{BASE_URL}/subtitles").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=SLASH_MOVIE_SUBTITLE_RESPONSE if request.url.params.get("id") == "314" else EMPTY_RESPONSE,
        )
    )

    results = await client.search("Foo Bar", languages="en")

    queried_titles = {call.request.url.params.get("query") for call in feature_route.calls}
    assert "Foo/Bar" in queried_titles
    assert results
    assert results[0].title == "Foo/Bar"


@respx.mock
@pytest.mark.asyncio
async def test_search_rejects_weak_generic_slash_retry_hits(client: OpenSubtitlesClient) -> None:
    feature_route = respx.get(f"{BASE_URL}/features").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=FEATURE_PARTIAL_SLASH_RESPONSE if request.url.params.get("query") == "Foo/Bar" else EMPTY_RESPONSE,
        )
    )
    respx.get(f"{BASE_URL}/subtitles").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=PARTIAL_SLASH_MOVIE_SUBTITLE_RESPONSE if request.url.params.get("id") == "2718" else EMPTY_RESPONSE,
        )
    )

    results = await client.search("Foo Bar", languages="en")

    queried_titles = {call.request.url.params.get("query") for call in feature_route.calls}
    assert "Foo/Bar" in queried_titles
    assert results == []


@respx.mock
@pytest.mark.asyncio
async def test_search_follows_redirects(client: OpenSubtitlesClient) -> None:
    redirected = {"done": False}

    def feature_handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("query") != "Inception":
            return httpx.Response(200, json=EMPTY_RESPONSE)
        if not redirected["done"]:
            redirected["done"] = True
            return httpx.Response(301, headers={"Location": "/api/v1/features?full_search=true&query=Inception"})
        return httpx.Response(200, json=FEATURE_MOVIE_RESPONSE)

    respx.get(f"{BASE_URL}/features").mock(side_effect=feature_handler)
    respx.get(f"{BASE_URL}/subtitles").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=MOVIE_SUBTITLE_RESPONSE if request.url.params.get("id") == "42" else EMPTY_RESPONSE,
        )
    )

    results = await client.search("Inception", languages="en")

    assert redirected["done"] is True
    assert len(results) == 1
    assert results[0].title == "Inception"
    assert results[0].file_id == 9001


@respx.mock
@pytest.mark.asyncio
async def test_search_uses_org_fallback_only_when_enabled(tmp_path: Path, mocker) -> None:
    feature_route = respx.get(f"{BASE_URL}/features").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=FEATURE_TVSHOW_RESPONSE if request.url.params.get("query") == "Fate/strange Fake" else EMPTY_RESPONSE,
        )
    )
    respx.get(f"{BASE_URL}/subtitles").mock(
        side_effect=lambda request: httpx.Response(
            200,
            json=TVSHOW_SUBTITLE_RESPONSE if request.url.params.get("parent_feature_id") == "2239923" else EMPTY_RESPONSE,
        )
    )

    disabled_client = OpenSubtitlesClient(api_key="test-key", user_agent="Meowcal-Sub-2/0.1", cache_dir=tmp_path)
    mocker.patch.object(disabled_client, "_search_org_aliases", new=mocker.AsyncMock(return_value=["Fate/strange Fake"]))
    assert await disabled_client.search("Mystery Title", languages="en") == []

    enabled_client = OpenSubtitlesClient(
        api_key="test-key",
        user_agent="Meowcal-Sub-2/0.1",
        cache_dir=tmp_path,
        enable_org_fallback=True,
    )
    mocker.patch.object(enabled_client, "_search_org_aliases", new=mocker.AsyncMock(return_value=["Fate/strange Fake"]))

    results = await enabled_client.search("Mystery Title", languages="en")

    assert results
    assert results[0].parent_title == "Fate/strange Fake"
    assert any(call.request.url.params.get("query") == "Fate/strange Fake" for call in feature_route.calls)


@respx.mock
@pytest.mark.asyncio
async def test_org_alias_can_lift_exact_feature_into_resolution_window(tmp_path: Path, mocker) -> None:
    many_candidates = {
        "data": [
            {
                "id": str(index),
                "type": "feature",
                "attributes": {
                    "title": f"Fake Show {index}",
                    "original_title": f"Fake Show {index}",
                    "year": "2020",
                    "subtitles_count": 50 - index,
                    "season_number": 0,
                    "episode_number": None,
                    "imdb_id": 1000 + index,
                    "tmdb_id": 2000 + index,
                    "parent_title": "",
                    "parent_imdb_id": None,
                    "parent_tmdb_id": None,
                    "title_aka": [f"Fake Show {index}"],
                    "feature_type": "Tvshow",
                },
            }
            for index in range(1, 7)
        ]
        + FEATURE_TVSHOW_RESPONSE["data"]
    }

    def feature_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=many_candidates if request.url.params.get("query") == "Fate/strange Fake" else EMPTY_RESPONSE)

    def subtitle_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=TVSHOW_SUBTITLE_RESPONSE if request.url.params.get("parent_feature_id") == "2239923" else EMPTY_RESPONSE,
        )

    respx.get(f"{BASE_URL}/features").mock(side_effect=feature_handler)
    respx.get(f"{BASE_URL}/subtitles").mock(side_effect=subtitle_handler)

    client = OpenSubtitlesClient(
        api_key="test-key",
        user_agent="Meowcal-Sub-2/0.1",
        cache_dir=tmp_path,
        enable_org_fallback=True,
    )
    mocker.patch.object(client, "_search_org_aliases", new=mocker.AsyncMock(return_value=["Fate/strange Fake"]))

    results = await client.search("Need rare alias", languages="en")

    assert results
    assert results[0].parent_title == "Fate/strange Fake"


@respx.mock
@pytest.mark.asyncio
async def test_org_fallback_aliases_are_used_for_ranking(tmp_path: Path, mocker) -> None:
    def feature_handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params.get("query")
        if query == "Fate/strange Fake":
            return httpx.Response(200, json=FEATURE_TVSHOW_RESPONSE)
        if query == "Fate/Zero":
            return httpx.Response(200, json=FEATURE_ZERO_RESPONSE)
        return httpx.Response(200, json=EMPTY_RESPONSE)

    def subtitle_handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("parent_feature_id") == "2239923":
            return httpx.Response(200, json=TVSHOW_SUBTITLE_RESPONSE)
        if request.url.params.get("parent_feature_id") == "127283":
            return httpx.Response(200, json=ZERO_SUBTITLE_RESPONSE)
        if request.url.params.get("query") == "Fate fake london":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "bad",
                            "type": "subtitle",
                            "attributes": {
                                "language": "en",
                                "download_count": 9000,
                                "feature_details": {
                                    "feature_id": 999,
                                    "feature_type": "Movie",
                                    "year": 2017,
                                    "title": "Fake Tattoos",
                                    "movie_name": "Fake Tattoos",
                                    "imdb_id": 123,
                                    "tmdb_id": 456,
                                    "season_number": None,
                                    "episode_number": None,
                                    "parent_imdb_id": None,
                                    "parent_title": None,
                                    "parent_tmdb_id": None,
                                    "parent_feature_id": None,
                                },
                                "files": [{"file_id": 100, "file_name": "fake.srt"}],
                            },
                        }
                    ]
                },
            )
        return httpx.Response(200, json=EMPTY_RESPONSE)

    respx.get(f"{BASE_URL}/features").mock(side_effect=feature_handler)
    respx.get(f"{BASE_URL}/subtitles").mock(side_effect=subtitle_handler)

    client = OpenSubtitlesClient(
        api_key="test-key",
        user_agent="Meowcal-Sub-2/0.1",
        cache_dir=tmp_path,
        enable_org_fallback=True,
    )
    mocker.patch.object(client, "_search_org_aliases", new=mocker.AsyncMock(return_value=["Fate/strange Fake", "Fate/Zero"]))

    results = await client.search("Fate fake london", languages="en")

    assert results
    assert results[0].parent_title == "Fate/strange Fake"
    assert any(result.parent_title == "Fate/Zero" for result in results)
    assert results[0].match_score > next(result.match_score for result in results if result.parent_title == "Fate/Zero")


@respx.mock
@pytest.mark.asyncio
async def test_get_download_link(client: OpenSubtitlesClient) -> None:
    respx.post(f"{BASE_URL}/download").mock(return_value=httpx.Response(200, json=DOWNLOAD_RESPONSE))
    link, remaining = await client.get_download_link(file_id=9001)
    assert link == DOWNLOAD_RESPONSE["link"]
    assert remaining == 19


@respx.mock
@pytest.mark.asyncio
async def test_rate_limit_retry(client: OpenSubtitlesClient, mocker) -> None:
    sleep = mocker.patch("meocosub2.opensubtitles.client.asyncio.sleep", new=mocker.AsyncMock())
    route = respx.get(f"{BASE_URL}/features").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "1"}, json={}),
            httpx.Response(200, json=EMPTY_RESPONSE),
            httpx.Response(200, json=EMPTY_RESPONSE),
        ]
    )
    respx.get(f"{BASE_URL}/subtitles").mock(return_value=httpx.Response(200, json=EMPTY_RESPONSE))

    await client.search("Inception", languages="en")

    assert route.call_count >= 2
    sleep.assert_awaited_once_with(1)


@respx.mock
@pytest.mark.asyncio
async def test_request_raises_after_max_retries(client: OpenSubtitlesClient, mocker) -> None:
    sleep = mocker.patch("meocosub2.opensubtitles.client.asyncio.sleep", new=mocker.AsyncMock())
    route = respx.get(f"{BASE_URL}/features").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "1"}, json={})] * (MAX_RETRIES + 1)
    )

    with pytest.raises(OpenSubtitlesError):
        await client.search("Inception", languages="en")

    assert route.call_count == MAX_RETRIES + 1
    assert sleep.await_count == MAX_RETRIES


@respx.mock
@pytest.mark.asyncio
async def test_download_uses_cache(client: OpenSubtitlesClient) -> None:
    path = client.cache_dir / "9001.srt"
    path.write_text("cached", encoding="utf-8")
    downloaded = await client.download(9001)
    assert downloaded == path


def test_org_alias_parser_extracts_titles() -> None:
    parser = _OpenSubtitlesOrgAliasParser()
    parser.feed(
        """
        <a class="bnone" title="Subtitles - Fate/strange Fake" href="/en/search/sublanguageid-all/idmovie-1796469">
          Fate/strange Fake (2024)
        </a>
        <a class="bnone" title="subtitles - &quot;Fate/strange Fake&quot; The Heroic Spirit Incident" href="/en/search/sublanguageid-all/idmovie-1797350">
          The Heroic Spirit Incident
        </a>
        """
    )

    assert parser.titles == ["Fate/strange Fake", '"Fate/strange Fake" The Heroic Spirit Incident']
