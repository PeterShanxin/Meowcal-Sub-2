"""SubDL provider implementation using the official API plus legacy parsers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import unicodedata
import zipfile
from pathlib import Path
from urllib.parse import urlparse

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
from meocosub2.subtitle_sources.cache_paths import (
    contained_path,
    safe_segment,
    subtitle_file_name,
)
from meocosub2.subtitle_sources.utils import (
    extract_episode_info,
    extract_zip_bytes,
    map_subdl_language,
    title_similarity,
)

NEXT_DATA_PATTERN = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>')
BASE_URL = "https://subdl.com"
API_URL = "https://api.subdl.com/api/v1/subtitles"
DOWNLOAD_URL = "https://dl.subdl.com/subtitle/{link}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0 Safari/537.36"
MAX_TITLES = 5
MAX_SUBTITLES = 40
MAX_PARALLEL_SEASON_FETCHES = 4
MAX_REASONABLE_EPISODE = 999


class SubdlProvider:
    provider_code = "subdl"
    provider_label = "SubDL"
    capabilities = ProviderCapabilities(search=True, download=True, requires_auth=True)

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._cache_dir = Path.home() / ".cache" / "meowcal-sub-2" / "subdl"

    async def search_catalog(self, query: str, languages: str) -> ProviderSearchCatalog:
        if not self.config.subdl_enabled:
            return ProviderSearchCatalog(matches=[], results=[], warnings=["SubDL is disabled."])
        if not self.config.subdl_api_key:
            return ProviderSearchCatalog(matches=[], results=[], warnings=["SubDL API key is not configured."])

        requested_languages = {code.strip() for code in languages.split(",") if code.strip()}
        warnings: list[str] = []
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers={"Accept": "application/json"}) as client:
            try:
                page = await self._fetch_api(
                    client,
                    {
                        "film_name": query,
                        "languages": self._to_api_languages(requested_languages),
                        "subs_per_page": "30",
                        "comment": "1",
                        "releases": "1",
                        "hi": "1",
                        "unpack": "1",
                    },
                )
            except Exception as exc:
                warning = self._provider_warning_for_error(exc)
                if warning:
                    return ProviderSearchCatalog(matches=[], results=[], warnings=[warning])
                raise
            items = page.get("results", [])
            matches: list[ProviderSubtitleMatch] = []
            results: list[ProviderSubtitleResult] = []

            selected_items = [item for item in items[:MAX_TITLES] if isinstance(item, dict)]
            for item in selected_items:
                matches.append(
                    ProviderSubtitleMatch(
                        id=f"subdl-match-{item.get('sd_id')}",
                        provider=self.provider_code,
                        provider_label=self.provider_label,
                        title=str(item.get("name") or item.get("original_name") or query),
                        year=self._coerce_int(item.get("year")),
                        imdb_id=self._coerce_optional_string(item.get("imdb_id")),
                        tmdb_id=self._coerce_optional_string(item.get("tmdb_id")),
                        media_type="tvshow" if str(item.get("type")) == "tv" else "movie",
                        subtitles_count=self._coerce_int(item.get("subtitles_count")) or 0,
                        match_score=title_similarity(query, [str(item.get("name") or ""), str(item.get("original_name") or "")]),
                    )
                )

            async def collect(item: dict[str, object]) -> list[ProviderSubtitleResult]:
                return await self._collect_api_title_results(item, requested_languages, client)

            collected = await asyncio.gather(*(collect(item) for item in selected_items), return_exceptions=True)
            deferred_warnings: list[str] = []
            for item_results in collected:
                if isinstance(item_results, Exception):
                    warning = self._provider_warning_for_error(item_results)
                    if not warning:
                        raise item_results
                    if "authentication failed" in warning:
                        if warning not in warnings:
                            warnings.append(warning)
                    elif warning not in deferred_warnings:
                        deferred_warnings.append(warning)
                    continue
                results.extend(item_results)
            if not results:
                warnings.extend(item for item in deferred_warnings if item not in warnings)

        return ProviderSearchCatalog(matches=matches, results=results, warnings=warnings)

    async def download(self, result: ProviderSubtitleResult) -> Path:
        link = str(result.raw.get("link") or result.download_ref or "")
        if not link:
            raise SubtitleSourceError("SubDL result is missing a download link.")

        extract_dir = contained_path(self._cache_dir, safe_segment(result.id, "subdl"))
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            response = await client.get(self._download_url(link))
            response.raise_for_status()
            try:
                return extract_zip_bytes(response.content, extract_dir)
            except zipfile.BadZipFile:
                if not result.raw.get("file_n_id"):
                    raise
                return self._write_raw_subtitle(response.content, extract_dir, result)

    async def _collect_title_results(
        self,
        item: dict[str, object],
        requested_languages: set[str],
        client: httpx.AsyncClient | None = None,
        season_sem: asyncio.Semaphore | None = None,
    ) -> list[ProviderSubtitleResult]:
        slug = str(item.get("slug") or "")
        sd_id = str(item.get("sd_id") or "")
        if not slug or not sd_id:
            return []

        detail = await self._fetch_next_data(f"{BASE_URL}/en/subtitle/{sd_id}/{slug}", client)
        movie_info = detail.get("movieInfo", {})
        media_type = "tvshow" if str(movie_info.get("type")) == "tv" else "movie"
        title = str(movie_info.get("name") or item.get("name") or slug)
        year = self._coerce_int(movie_info.get("year")) or self._coerce_int(item.get("year"))
        subtitles: list[ProviderSubtitleResult] = []

        if media_type == "tvshow" and movie_info.get("seasons"):
            seasons = movie_info.get("seasons") or []
            season_urls: list[str] = []
            for season in seasons[:6]:
                if not isinstance(season, dict):
                    continue
                season_slug = str(season.get("number") or "")
                if not season_slug:
                    continue
                season_urls.append(f"{BASE_URL}/en/subtitle/{sd_id}/{slug}/{season_slug}")

            sem = season_sem or asyncio.Semaphore(MAX_PARALLEL_SEASON_FETCHES)

            async def fetch_season(url: str) -> dict[str, object]:
                async with sem:
                    return await self._fetch_next_data(url, client)

            for season_page in await asyncio.gather(*(fetch_season(url) for url in season_urls)):
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

        return self._limit_subtitles(subtitles)

    async def _collect_api_title_results(
        self,
        item: dict[str, object],
        requested_languages: set[str],
        client: httpx.AsyncClient,
    ) -> list[ProviderSubtitleResult]:
        sd_id = str(item.get("sd_id") or "")
        if not sd_id:
            return []
        params: dict[str, object] = {
            "sd_id": sd_id,
            "languages": self._to_api_languages(requested_languages),
            "subs_per_page": "30",
            "comment": "1",
            "releases": "1",
            "hi": "1",
            "full_season": "1",
            "unpack": "1",
        }
        payload = await self._fetch_api(client, params)
        return self._limit_subtitles(
            self._parse_api_subtitles(
                title=str(item.get("name") or item.get("original_name") or ""),
                year=self._coerce_int(item.get("year")),
                match_id=f"subdl-match-{sd_id}",
                requested_languages=requested_languages,
                item=item,
                subtitles=payload.get("subtitles"),
            )
        )

    def _parse_api_subtitles(
        self,
        *,
        title: str,
        year: int | None,
        match_id: str,
        requested_languages: set[str],
        item: dict[str, object],
        subtitles: object,
    ) -> list[ProviderSubtitleResult]:
        if not isinstance(subtitles, list):
            return []

        media_type = "tvshow" if str(item.get("type")) == "tv" else "movie"
        parent_title = title or str(item.get("original_name") or "")
        results: list[ProviderSubtitleResult] = []
        for raw_entry in subtitles:
            for entry in self._expand_api_subtitle_entry(raw_entry):
                parsed = self._parse_api_subtitle_entry(
                    entry=entry,
                    title=title,
                    year=year,
                    match_id=match_id,
                    requested_languages=requested_languages,
                    item=item,
                    media_type=media_type,
                    parent_title=parent_title,
                )
                if parsed is not None:
                    results.append(parsed)
        return results

    def _parse_api_subtitle_entry(
        self,
        *,
        entry: dict[str, object],
        title: str,
        year: int | None,
        match_id: str,
        requested_languages: set[str],
        item: dict[str, object],
        media_type: str,
        parent_title: str,
    ) -> ProviderSubtitleResult | None:
        mapped_language = map_subdl_language(str(entry.get("language") or entry.get("lang") or ""))
        if requested_languages and mapped_language not in requested_languages:
            return None
        season, episode = self._episode_fields(entry)
        raw_title = str(
            entry.get("name")
            or entry.get("release_name")
            or entry.get("title")
            or entry.get("file_name")
            or parent_title
        )
        link = self._normalize_download_ref(entry.get("url") or entry.get("link") or "")
        result_id = self._safe_identifier(self._api_result_key(entry, item, link, raw_title))
        releases = self._string_list(entry.get("releases"))
        subtitle_media_type = "episode" if episode or media_type == "tvshow" else "movie"
        return ProviderSubtitleResult(
            id=f"subdl-result-{result_id}",
            match_id=match_id,
            provider=self.provider_code,
            provider_label=self.provider_label,
            title=raw_title,
            year=year,
            imdb_id=self._coerce_optional_string(item.get("imdb_id")),
            tmdb_id=self._coerce_optional_string(item.get("tmdb_id")),
            media_type=subtitle_media_type,
            season=season,
            episode=episode,
            parent_title=parent_title if subtitle_media_type == "episode" else None,
            language=mapped_language,
            download_count=self._coerce_int(entry.get("downloads")) or 0,
            file_name=raw_title or link or f"{result_id}.zip",
            match_score=title_similarity(title or parent_title, [raw_title, *releases]),
            download_ref=link,
            raw={
                "link": link,
                "sd_id": item.get("sd_id"),
                "api": True,
                "pack_link": entry.get("pack_url"),
                "file_n_id": entry.get("file_n_id"),
            },
        )

    def _api_result_key(
        self,
        entry: dict[str, object],
        item: dict[str, object],
        link: str,
        raw_title: str,
    ) -> object:
        file_n_id = self._coerce_optional_string(entry.get("file_n_id"))
        if file_n_id:
            pack_key = self._coerce_optional_string(
                entry.get("pack_id") or entry.get("pack_url") or entry.get("id") or item.get("sd_id")
            )
            return f"{pack_key}-{file_n_id}" if pack_key else file_n_id
        return link or entry.get("id") or raw_title

    def _expand_api_subtitle_entry(self, entry: object) -> list[dict[str, object]]:
        if not isinstance(entry, dict):
            return []
        unpack_files = entry.get("unpack_files")
        if not isinstance(unpack_files, list) or not unpack_files:
            return [entry]

        expanded: list[dict[str, object]] = []
        for file_entry in unpack_files:
            if not isinstance(file_entry, dict):
                continue
            merged = {**entry, **file_entry}
            merged["pack_id"] = entry.get("id")
            merged["pack_url"] = entry.get("url") or entry.get("link")
            if not merged.get("id") and file_entry.get("file_n_id"):
                merged["id"] = f"{entry.get('id') or entry.get('url') or 'pack'}-{file_entry['file_n_id']}"
            expanded.append(merged)
        return expanded

    async def _fetch_api(self, client: httpx.AsyncClient, params: dict[str, object]) -> dict[str, object]:
        query_params = {"api_key": self.config.subdl_api_key, **params}
        started = time.perf_counter()
        response = await client.get(API_URL, params=query_params)
        safe_params = {key: value for key, value in query_params.items() if key != "api_key"}
        log_event(
            "provider.http",
            layer="backend",
            provider="subdl",
            method="GET",
            path="/api/v1/subtitles",
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000),
            params=safe_params,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") is False:
            raise SubtitleSourceError(str(payload.get("error") or "SubDL API request failed."))
        return payload

    def _provider_warning_for_error(self, exc: Exception) -> str | None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int) and status_code in {401, 403}:
            return f"SubDL: authentication failed (HTTP {status_code}). Check the saved API key or token."
        if isinstance(exc, SubtitleSourceError):
            return f"SubDL: {exc}"
        return None

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
                season, episode = self._episode_fields(entry)
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

    async def _fetch_next_data(self, url: str, client: httpx.AsyncClient | None = None) -> dict[str, object]:
        if client is None:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as scoped_client:
                return await self._fetch_next_data(url, scoped_client)
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

    def _coerce_optional_string(self, value: object) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None

    def _normalize_download_ref(self, value: object) -> str:
        link = str(value or "").strip()
        if link.startswith(DOWNLOAD_URL.format(link="")):
            return link
        return link.removeprefix("/subtitle/").removeprefix("subtitle/")

    def _download_url(self, link: str) -> str:
        if link.startswith(("http://", "https://")):
            parsed = urlparse(link)
            if parsed.scheme != "https" or parsed.netloc.lower() != "dl.subdl.com":
                raise SubtitleSourceError("SubDL download link host is not allowed.")
            return link
        return DOWNLOAD_URL.format(link=link.lstrip("/").removeprefix("subtitle/"))

    def _write_raw_subtitle(self, content: bytes, destination: Path, result: ProviderSubtitleResult) -> Path:
        destination.mkdir(parents=True, exist_ok=True)
        path = contained_path(
            destination, subtitle_file_name(result.file_name or result.id, "subtitle")
        )
        path.write_bytes(content)
        return path

    def _safe_identifier(self, value: object) -> str:
        text = str(value or "").strip()
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip(".-_")
        if safe and len(safe) <= 80:
            return safe
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        prefix = safe[:48].strip(".-_")
        return f"{prefix}-{digest}" if prefix else digest

    def _to_api_languages(self, requested_languages: set[str]) -> str:
        mapped: list[str] = []
        for code in sorted(requested_languages):
            normalized = code.strip().lower()
            if normalized == "zht":
                normalized = "zh"
            if normalized:
                mapped.append(normalized.upper())
        return ",".join(dict.fromkeys(mapped))

    def _episode_fields(self, entry: dict[str, object]) -> tuple[int | None, int | None]:
        raw_season = self._coerce_non_negative_int(entry.get("season"))
        raw_episode = self._coerce_positive_int(entry.get("episode"))
        if raw_episode is not None and raw_episode > MAX_REASONABLE_EPISODE:
            raw_episode = None
        if raw_episode is not None:
            return raw_season, raw_episode

        inferred_season, inferred_episode = extract_episode_info(*self._episode_text_values(entry))
        if inferred_episode is not None:
            season = inferred_season if inferred_season is not None else raw_season
            return season, inferred_episode
        return raw_season, raw_episode

    def _coerce_non_negative_int(self, value: object) -> int | None:
        number = self._coerce_int(value)
        return number if number is not None and number >= 0 else None

    def _coerce_positive_int(self, value: object) -> int | None:
        number = self._coerce_int(value)
        return number if number is not None and number > 0 else None

    def _episode_text_values(self, entry: dict[str, object]) -> list[str]:
        values: list[str] = []
        for key in ("title", "name", "release_name", "file_name", "link", "url", "slug"):
            value = entry.get(key)
            if value:
                values.append(unicodedata.normalize("NFKC", str(value)))
        values.extend(unicodedata.normalize("NFKC", item) for item in self._string_list(entry.get("releases")))
        return values

    def _limit_subtitles(self, subtitles: list[ProviderSubtitleResult]) -> list[ProviderSubtitleResult]:
        ranked = sorted(subtitles, key=self._subtitle_rank, reverse=True)
        selected: list[ProviderSubtitleResult] = []
        selected_ids: set[str] = set()
        episode_representatives: dict[tuple[int, int], ProviderSubtitleResult] = {}

        for subtitle in ranked:
            if subtitle.season is None or subtitle.episode is None:
                continue
            episode_representatives.setdefault((subtitle.season, subtitle.episode), subtitle)

        for subtitle in episode_representatives.values():
            self._add_limited(selected, selected_ids, subtitle)
            if len(selected) >= MAX_SUBTITLES:
                return selected

        for subtitle in ranked:
            self._add_limited(selected, selected_ids, subtitle)
            if len(selected) >= MAX_SUBTITLES:
                break
        return selected

    def _add_limited(
        self,
        selected: list[ProviderSubtitleResult],
        selected_ids: set[str],
        subtitle: ProviderSubtitleResult,
    ) -> None:
        if subtitle.id in selected_ids:
            return
        selected.append(subtitle)
        selected_ids.add(subtitle.id)

    def _subtitle_rank(self, subtitle: ProviderSubtitleResult) -> tuple[float, int]:
        return (subtitle.match_score, subtitle.download_count)

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if item]
