import asyncio
from pathlib import Path

import httpx
import pytest
import respx

from meocosub2.errors import OpenSubtitlesError
from meocosub2.opensubtitles.client import BASE_URL, MAX_RETRIES, OpenSubtitlesClient

SEARCH_RESPONSE = {
    "data": [
        {
            "id": "123",
            "type": "subtitle",
            "attributes": {
                "language": "en",
                "download_count": 5000,
                "feature_details": {
                    "feature_type": "Movie",
                    "title": "Inception",
                    "year": 2010,
                    "imdb_id": "tt1375666",
                    "season_number": None,
                    "episode_number": None,
                },
                "files": [{"file_id": 9001, "file_name": "Inception.srt"}],
            },
        }
    ],
    "total_count": 1,
}

DOWNLOAD_RESPONSE = {
    "link": "https://dl.opensubtitles.com/abc/Inception.srt",
    "file_name": "Inception.srt",
    "remaining": 19,
}


@pytest.fixture
def client(tmp_path: Path) -> OpenSubtitlesClient:
    return OpenSubtitlesClient(api_key="test-key", user_agent="MeoCoSub2/0.1", cache_dir=tmp_path)


@respx.mock
@pytest.mark.asyncio
async def test_search_returns_results(client: OpenSubtitlesClient) -> None:
    respx.get(f"{BASE_URL}/subtitles").mock(return_value=httpx.Response(200, json=SEARCH_RESPONSE))
    results = await client.search("Inception", languages="en")
    assert len(results) == 1
    assert results[0].title == "Inception"
    assert results[0].file_id == 9001
    assert results[0].language == "en"
    assert results[0].download_count == 5000


@respx.mock
@pytest.mark.asyncio
async def test_search_passes_language_param(client: OpenSubtitlesClient) -> None:
    route = respx.get(f"{BASE_URL}/subtitles").mock(return_value=httpx.Response(200, json={"data": []}))
    await client.search("Inception", languages="en,zh")
    assert route.called
    assert route.calls[0].request.url.params["languages"] == "en,zh"


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
    route = respx.get(f"{BASE_URL}/subtitles").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "1"}, json={}),
            httpx.Response(200, json=SEARCH_RESPONSE),
        ]
    )
    results = await client.search("Inception", languages="en")
    assert len(results) == 1
    assert route.call_count == 2
    sleep.assert_awaited_once_with(1)


@respx.mock
@pytest.mark.asyncio
async def test_request_raises_after_max_retries(client: OpenSubtitlesClient, mocker) -> None:
    sleep = mocker.patch("meocosub2.opensubtitles.client.asyncio.sleep", new=mocker.AsyncMock())
    route = respx.get(f"{BASE_URL}/subtitles").mock(
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
