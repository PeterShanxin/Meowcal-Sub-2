"""ASSRT provider implementation."""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from meocosub2.config import AppConfig
from meocosub2.errors import SubtitleSourceError
from meocosub2.event_log import log_event
from meocosub2.subtitle_sources.types import ProviderCapabilities, ProviderSearchCatalog, ProviderSubtitleResult
from meocosub2.subtitle_sources.utils import (
    best_title_guess,
    extract_episode_info,
    extract_year,
    map_assrt_language,
    title_similarity,
)

API_BASE = "https://api.assrt.net/v1"
MAX_RESULTS = 15


class AssrtProvider:
    provider_code = "assrt"
    provider_label = "ASSRT"
    capabilities = ProviderCapabilities(search=True, download=True, requires_auth=True)

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._cache_dir = Path.home() / ".cache" / "meowcal-sub-2" / "assrt"

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
            season, episode = extract_episode_info(native_name, videoname)
            guessed_title = best_title_guess(query, native_name, videoname)
            year = extract_year(native_name, videoname)
            filelist = item.get("filelist") if isinstance(item.get("filelist"), list) else []
            primary_file_name = (
                str(filelist[0].get("f"))
                if filelist and isinstance(filelist[0], dict) and filelist[0].get("f")
                else str(item.get("videoname") or item.get("native_name") or f"{item.get('id')}.srt")
            )
            results.append(
                ProviderSubtitleResult(
                    id=f"assrt-result-{item.get('id')}",
                    match_id=f"assrt-match-{item.get('id')}",
                    provider=self.provider_code,
                    provider_label=self.provider_label,
                    title=guessed_title,
                    year=year,
                    imdb_id=None,
                    tmdb_id=None,
                    media_type="episode" if episode else "movie",
                    season=season,
                    episode=episode,
                    parent_title=guessed_title if episode else None,
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
        destination = self._cache_dir / result.id / Path(file_name).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(direct_url)
            response.raise_for_status()
            destination.write_bytes(response.content)
        return destination

    async def _request(self, path: str, params: dict[str, object]) -> dict[str, object]:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
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
