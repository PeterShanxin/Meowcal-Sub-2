"""SubDL provider implementation using public site data."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import quote

import httpx

from meocosub2.config import AppConfig
from meocosub2.errors import SubtitleSourceError
from meocosub2.event_log import log_event
from meocosub2.subtitle_sources.types import (
    ProviderCapabilities,
    ProviderSearchCatalog,
    ProviderSubtitleMatch,
    ProviderSubtitleResult,
)
from meocosub2.subtitle_sources.utils import extract_zip_bytes, map_subdl_language, title_similarity

NEXT_DATA_PATTERN = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>')
BASE_URL = "https://subdl.com"
DOWNLOAD_URL = "https://dl.subdl.com/subtitle/{link}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0 Safari/537.36"
MAX_TITLES = 5
MAX_SUBTITLES = 40


class SubdlProvider:
    provider_code = "subdl"
    provider_label = "SubDL"
    capabilities = ProviderCapabilities(search=True, download=True, requires_auth=False)

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._cache_dir = Path.home() / ".cache" / "meowcal-sub-2" / "subdl"

    async def search_catalog(self, query: str, languages: str) -> ProviderSearchCatalog:
        if not self.config.subdl_enabled:
            return ProviderSearchCatalog(matches=[], results=[], warnings=["SubDL is disabled."])

        requested_languages = {code.strip() for code in languages.split(",") if code.strip()}
        page = await self._fetch_next_data(f"{BASE_URL}/en/search/{quote(query)}")
        items = page.get("list", [])
        matches: list[ProviderSubtitleMatch] = []
        results: list[ProviderSubtitleResult] = []

        for item in items[:MAX_TITLES]:
            if not isinstance(item, dict):
                continue
            matches.append(
                ProviderSubtitleMatch(
                    id=f"subdl-match-{item.get('sd_id')}",
                    provider=self.provider_code,
                    provider_label=self.provider_label,
                    title=str(item.get("name") or item.get("original_name") or query),
                    year=self._coerce_int(item.get("year")),
                    imdb_id=None,
                    tmdb_id=None,
                    media_type="tvshow" if str(item.get("type")) == "tv" else "movie",
                    subtitles_count=self._coerce_int(item.get("subtitles_count")) or 0,
                    match_score=title_similarity(query, [str(item.get("name") or ""), str(item.get("original_name") or "")]),
                )
            )
            results.extend(await self._collect_title_results(item, requested_languages))

        return ProviderSearchCatalog(matches=matches, results=results)

    async def download(self, result: ProviderSubtitleResult) -> Path:
        link = str(result.raw.get("link") or result.download_ref or "")
        if not link:
            raise SubtitleSourceError("SubDL result is missing a download link.")

        extract_dir = self._cache_dir / result.id
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            response = await client.get(DOWNLOAD_URL.format(link=link))
            response.raise_for_status()
            return extract_zip_bytes(response.content, extract_dir)

    async def _collect_title_results(self, item: dict[str, object], requested_languages: set[str]) -> list[ProviderSubtitleResult]:
        slug = str(item.get("slug") or "")
        sd_id = str(item.get("sd_id") or "")
        if not slug or not sd_id:
            return []

        detail = await self._fetch_next_data(f"{BASE_URL}/en/subtitle/{sd_id}/{slug}")
        movie_info = detail.get("movieInfo", {})
        media_type = "tvshow" if str(movie_info.get("type")) == "tv" else "movie"
        title = str(movie_info.get("name") or item.get("name") or slug)
        year = self._coerce_int(movie_info.get("year")) or self._coerce_int(item.get("year"))
        subtitles: list[ProviderSubtitleResult] = []

        if media_type == "tvshow" and movie_info.get("seasons"):
            seasons = movie_info.get("seasons") or []
            for season in seasons[:6]:
                if not isinstance(season, dict):
                    continue
                season_slug = str(season.get("number") or "")
                if not season_slug:
                    continue
                season_page = await self._fetch_next_data(f"{BASE_URL}/en/subtitle/{sd_id}/{slug}/{season_slug}")
                subtitles.extend(
                    self._parse_page_subtitles(
                        title=title,
                        year=year,
                        match_id=f"subdl-match-{sd_id}",
                        requested_languages=requested_languages,
                        page_props=season_page,
                    )
                )
        else:
            subtitles.extend(
                self._parse_page_subtitles(
                    title=title,
                    year=year,
                    match_id=f"subdl-match-{sd_id}",
                    requested_languages=requested_languages,
                    page_props=detail,
                )
            )

        subtitles.sort(key=lambda item: (item.match_score, item.download_count), reverse=True)
        return subtitles[:MAX_SUBTITLES]

    def _parse_page_subtitles(
        self,
        *,
        title: str,
        year: int | None,
        match_id: str,
        requested_languages: set[str],
        page_props: dict[str, object],
    ) -> list[ProviderSubtitleResult]:
        grouped = page_props.get("groupedSubtitles")
        if not isinstance(grouped, dict):
            return []

        results: list[ProviderSubtitleResult] = []
        for language_name, entries in grouped.items():
            mapped_language = map_subdl_language(str(language_name))
            if requested_languages and mapped_language not in requested_languages:
                continue
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                season = self._coerce_int(entry.get("season"))
                episode = self._coerce_int(entry.get("episode"))
                file_name = str(entry.get("title") or entry.get("link") or f"{title}.zip")
                subtitle_title = str(entry.get("title") or title)
                results.append(
                    ProviderSubtitleResult(
                        id=f"subdl-result-{entry.get('id')}",
                        match_id=match_id,
                        provider=self.provider_code,
                        provider_label=self.provider_label,
                        title=subtitle_title,
                        year=year,
                        imdb_id=None,
                        tmdb_id=None,
                        media_type="episode" if episode else "movie",
                        season=season,
                        episode=episode,
                        parent_title=title if episode else None,
                        language=mapped_language,
                        download_count=self._coerce_int(entry.get("downloads")) or 0,
                        file_name=file_name,
                        match_score=title_similarity(title, [subtitle_title, *self._string_list(entry.get("releases"))]),
                        download_ref=str(entry.get("link") or ""),
                        raw={"link": entry.get("link"), "slug": entry.get("slug")},
                    )
                )
        return results

    async def _fetch_next_data(self, url: str) -> dict[str, object]:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            started = time.perf_counter()
            response = await client.get(url)
            log_event(
                "provider.http",
                layer="backend",
                provider="subdl",
                method="GET",
                path=self._safe_path(url),
                status_code=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
            response.raise_for_status()
        match = NEXT_DATA_PATTERN.search(response.text)
        if not match:
            raise SubtitleSourceError(f"SubDL page did not expose structured data: {url}")
        payload = json.loads(match.group(1))
        return payload.get("props", {}).get("pageProps", {})

    def _safe_path(self, url: str) -> str:
        return url.replace(BASE_URL, "")

    def _coerce_int(self, value: object) -> int | None:
        try:
            return int(value) if value not in {None, ""} else None
        except (TypeError, ValueError):
            return None

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if item]
