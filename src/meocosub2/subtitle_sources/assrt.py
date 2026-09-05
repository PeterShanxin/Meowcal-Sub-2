"""ASSRT provider implementation."""

from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path

import httpx

from meocosub2.config import AppConfig
from meocosub2.errors import SubtitleSourceError
from meocosub2.event_log import log_event
from meocosub2.http_timeouts import provider_timeout
from meocosub2.subtitle_sources.types import ProviderCapabilities, ProviderSearchCatalog, ProviderSubtitleResult
from meocosub2.subtitle_sources.cache_paths import (
    contained_path,
    safe_segment,
    subtitle_file_name,
)
from meocosub2.subtitle_sources.utils import (
    SUBTITLE_EXTENSIONS,
    best_title_guess,
    canonical_title,
    extract_episode_info,
    extract_year,
    map_assrt_language,
    title_similarity,
)

API_BASE = "https://api.assrt.net/v1"
MAX_RESULTS = 15
YEAR_SUFFIX_PATTERN = re.compile(r"\s*[\(（]?(?:19|20|21)\d{2}[\)）]?\s*$")
LATIN_TITLE_SEGMENT_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9'’&:.\- ]*[A-Za-z0-9)]?")
TRAILING_SEASON_PATTERN = re.compile(r"\bS\d{1,2}\s*$", re.IGNORECASE)


class AssrtProvider:
    provider_code = "assrt"
    provider_label = "ASSRT"
    capabilities = ProviderCapabilities(search=True, download=True, requires_auth=True)

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._cache_dir = Path.home() / ".cache" / "meowcal-sub-2" / "assrt"

    @property
    def enabled(self) -> bool:
        return self.config.assrt_enabled

    async def search_catalog(self, query: str, languages: str) -> ProviderSearchCatalog:
        if not self.config.assrt_enabled:
            return ProviderSearchCatalog(matches=[], results=[], warnings=["ASSRT is disabled."])
        if not self.config.assrt_token:
            return ProviderSearchCatalog(matches=[], results=[], warnings=["ASSRT token is not configured."])

        requested_languages = {code.strip() for code in languages.split(",") if code.strip()}
        payload = await self._request(
            "/sub/search",
            {"token": self.config.assrt_token, "q": query, "cnt": MAX_RESULTS, "filelist": 1},
        )
        subtitles = payload.get("sub", {}).get("subs", [])
        results: list[ProviderSubtitleResult] = []
        for item in subtitles:
            if not isinstance(item, dict):
                continue
            lang_block = item.get("lang") if isinstance(item.get("lang"), dict) else {}
            lang = map_assrt_language(
                str(lang_block.get("desc", "")),
                lang_block.get("langlist") if isinstance(lang_block.get("langlist"), dict) else None,
            )
            if requested_languages and lang not in requested_languages:
                continue
            native_name = str(item.get("native_name") or "")
            videoname = str(item.get("videoname") or "")
            filelist = item.get("filelist") if isinstance(item.get("filelist"), list) else []
            file_names = [
                str(entry.get("f"))
                for entry in filelist
                if isinstance(entry, dict) and entry.get("f")
            ]
            primary_file_name = next(
                (name for name in file_names if name.casefold().endswith(SUBTITLE_EXTENSIONS)),
                file_names[0]
                if file_names
                else str(item.get("videoname") or item.get("native_name") or f"{item.get('id')}.srt"),
            )
            metadata_values = [native_name, videoname, *file_names]
            season, episode = extract_episode_info(*metadata_values)
            guessed_title = best_title_guess(query, *metadata_values)
            parent_title = (
                self._episode_parent_title(query, *metadata_values, fallback=guessed_title)
                if episode
                else None
            )
            display_title = parent_title or guessed_title
            year = extract_year(*metadata_values)
            results.append(
                ProviderSubtitleResult(
                    id=f"assrt-result-{item.get('id')}",
                    match_id=f"assrt-match-{item.get('id')}",
                    provider=self.provider_code,
                    provider_label=self.provider_label,
                    title=display_title,
                    year=year,
                    imdb_id=None,
                    tmdb_id=None,
                    media_type="episode" if episode else "movie",
                    season=season,
                    episode=episode,
                    parent_title=parent_title,
                    language=lang,
                    download_count=self._coerce_int(item.get("down_count")) or 0,
                    file_name=primary_file_name,
                    match_score=title_similarity(query, [native_name, videoname, guessed_title]),
                    download_ref=str(item.get("id") or ""),
                )
            )
        return ProviderSearchCatalog(matches=[], results=results)

    async def download(self, result: ProviderSubtitleResult) -> Path:
        subtitle_id = str(result.download_ref or "")
        if not subtitle_id:
            raise SubtitleSourceError("ASSRT result is missing a subtitle id.")
        payload = await self._request("/sub/detail", {"token": self.config.assrt_token, "id": subtitle_id})
        subs = payload.get("sub", {}).get("subs", [])
        if not subs:
            raise SubtitleSourceError("ASSRT detail did not return subtitle files.")
        item = subs[0]
        if not isinstance(item, dict):
            raise SubtitleSourceError("ASSRT detail payload is malformed.")
        filelist = item.get("filelist") if isinstance(item.get("filelist"), list) else []
        direct_url = None
        file_name = result.file_name
        for entry in filelist:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("f") or "")
            if name.casefold().endswith((".srt", ".ass", ".ssa", ".vtt")) and entry.get("url"):
                direct_url = str(entry["url"])
                file_name = name
                break
        if not direct_url and item.get("url"):
            direct_url = str(item.get("url"))
        if not direct_url:
            raise SubtitleSourceError("ASSRT detail did not return a usable subtitle download URL.")
        destination = contained_path(
            self._cache_dir,
            safe_segment(result.id, "assrt"),
            subtitle_file_name(file_name, "subtitle"),
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=provider_timeout(30.0), follow_redirects=True) as client:
            response = await client.get(direct_url)
            response.raise_for_status()
            destination.write_bytes(response.content)
        return destination

    async def _request(self, path: str, params: dict[str, object]) -> dict[str, object]:
        async with httpx.AsyncClient(timeout=provider_timeout(30.0), follow_redirects=True) as client:
            started = time.perf_counter()
            response = await client.get(f"{API_BASE}{path}", params=params)
            log_event(
                "provider.http",
                layer="backend",
                provider="assrt",
                method="GET",
                path=path,
                status_code=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000),
                params={key: value for key, value in params.items() if key != "token"},
            )
            response.raise_for_status()
        payload = response.json()
        if payload.get("status") not in {0, "0"}:
            raise SubtitleSourceError(str(payload))
        return payload

    def _coerce_int(self, value: object) -> int | None:
        try:
            return int(value) if value not in {None, ""} else None
        except (TypeError, ValueError):
            return None

    def _episode_parent_title(self, query: str, *values: str, fallback: str) -> str:
        query_key = canonical_title(self._strip_episode_or_season_marker(query))
        if not query_key:
            return fallback
        for value in values:
            for segment in self._latin_title_segments(value):
                if canonical_title(segment) == query_key:
                    return segment
        return fallback

    def _strip_episode_or_season_marker(self, value: str) -> str:
        text = unicodedata.normalize("NFKC", value)
        text = re.sub(r"\bS\d{1,2}E\d{1,3}\b.*$", "", text, flags=re.IGNORECASE)
        text = TRAILING_SEASON_PATTERN.sub("", text)
        return text.strip(" -_:.")

    def _latin_title_segments(self, value: str) -> list[str]:
        text = unicodedata.normalize("NFKC", value)
        text = re.sub(r"\bS\d{1,2}E\d{1,3}\b.*$", "", text, flags=re.IGNORECASE)
        text = YEAR_SUFFIX_PATTERN.sub("", text).strip()
        segments: list[str] = []
        for match in LATIN_TITLE_SEGMENT_PATTERN.finditer(text):
            segment = match.group(0).strip(" -_:.'’")
            if segment:
                segments.append(segment)
        return segments
