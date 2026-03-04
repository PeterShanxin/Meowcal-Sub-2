"""Async OpenSubtitles client."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from meocosub2.errors import OpenSubtitlesError
from meocosub2.opensubtitles.types import SearchResult

BASE_URL = "https://api.opensubtitles.com/api/v1"
MAX_RETRIES = 3


class OpenSubtitlesClient:
    def __init__(
        self,
        api_key: str,
        user_agent: str = "MeoCoSub2/0.1.0",
        cache_dir: Path | None = None,
    ) -> None:
        self.api_key = api_key
        self.user_agent = user_agent
        self.cache_dir = cache_dir or (Path.home() / ".cache" / "meocosub2")
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "Api-Key": api_key,
                "User-Agent": user_agent,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "OpenSubtitlesClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        for attempt in range(MAX_RETRIES + 1):
            response = await self._client.request(method, path, **kwargs)
            if response.status_code != 429:
                return response
            if attempt >= MAX_RETRIES:
                raise OpenSubtitlesError("OpenSubtitles rate limit exceeded")

            retry_after = response.headers.get("Retry-After")
            retry_delay = 0
            if retry_after:
                try:
                    retry_delay = int(retry_after)
                except ValueError:
                    retry_delay = 0
            await asyncio.sleep(max(retry_delay, 2**attempt))

        raise OpenSubtitlesError("OpenSubtitles request failed")

    async def search(
        self,
        query: str,
        languages: str,
        media_type: str | None = None,
    ) -> list[SearchResult]:
        params: dict[str, str] = {"query": query, "languages": languages}
        if media_type:
            params["type"] = media_type

        response = await self._request("GET", "/subtitles", params=params)
        if response.status_code != 200:
            raise OpenSubtitlesError(f"OpenSubtitles search failed: {response.status_code}")

        payload = response.json()
        return [self._parse_result(item) for item in payload.get("data", [])]

    async def get_download_link(self, file_id: int) -> tuple[str, int]:
        response = await self._request("POST", "/download", json={"file_id": file_id})
        if response.status_code != 200:
            raise OpenSubtitlesError(f"OpenSubtitles download lookup failed: {response.status_code}")

        payload = response.json()
        link = payload.get("link")
        if not link:
            raise OpenSubtitlesError("OpenSubtitles download response missing link")
        return link, int(payload.get("remaining", 0))

    async def download(self, file_id: int, file_name: str | None = None) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        destination = self.cache_dir / (file_name or f"{file_id}.srt")
        if destination.exists():
            return destination

        link, _ = await self.get_download_link(file_id)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(link)
            response.raise_for_status()
            destination.write_bytes(response.content)
        return destination

    def _parse_result(self, item: dict[str, object]) -> SearchResult:
        attributes = item.get("attributes", {})
        if not isinstance(attributes, dict):
            attributes = {}
        feature_details = attributes.get("feature_details", {})
        if not isinstance(feature_details, dict):
            feature_details = {}
        files = attributes.get("files", [])
        file_info = files[0] if files else {}
        if not isinstance(file_info, dict):
            file_info = {}

        feature_type = str(feature_details.get("feature_type", "")).lower()
        media_type = "episode" if "episode" in feature_type else "movie"
        return SearchResult(
            id=str(item.get("id", "")),
            title=str(feature_details.get("title", "")),
            year=feature_details.get("year"),
            imdb_id=feature_details.get("imdb_id"),
            media_type=media_type,
            season=feature_details.get("season_number"),
            episode=feature_details.get("episode_number"),
            language=str(attributes.get("language", "")),
            download_count=int(attributes.get("download_count", 0)),
            file_id=int(file_info.get("file_id", 0)),
            file_name=str(file_info.get("file_name", "")),
        )
