"""TMDb v3 client used to unify cross-lingual series identity.

Many providers return culture-native titles ("オーバーロード" from OpenSubtitles,
"Overlord" from SubDL). Without an external registry they never collapse into a
single work. TMDb exposes both the canonical name and IMDb cross-references,
which gives us a stable per-series key.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from rapidfuzz import fuzz

from meocosub2.http_timeouts import provider_timeout

logger = logging.getLogger(__name__)

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p"
CACHE_TTL_SECONDS = 90 * 24 * 3600
CACHE_MAX_ENTRIES = 10_000
SEARCH_TIMEOUT_SECONDS = 6.0
MAX_CONCURRENT_LOOKUPS = 6
MIN_TITLE_SCORE = 72.0


@dataclass(frozen=True)
class TMDbSeries:
    tmdb_id: int
    imdb_id: str | None
    name: str
    original_name: str
    first_air_year: int | None
    poster_path: str | None = None


class TMDbCache:
    """Persistent JSON cache keyed by (verb, params). Best-effort, never fatal."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, dict[str, Any]] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._data = {
                        str(k): v for k, v in raw.items() if isinstance(v, dict)
                    }
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("TMDb cache read failed: %s", exc)
            self._data = {}

    def get(self, key: str) -> Any | None:
        entry = self._data.get(key)
        if not entry:
            return None
        ts = entry.get("ts")
        if not isinstance(ts, (int, float)) or time.time() - ts > CACHE_TTL_SECONDS:
            return None
        return entry.get("value")

    def set(self, key: str, value: Any) -> None:
        if len(self._data) >= CACHE_MAX_ENTRIES:
            # Drop oldest half — simple, no LRU needed for this volume.
            sorted_keys = sorted(
                self._data.keys(),
                key=lambda k: self._data[k].get("ts", 0),
            )
            for k in sorted_keys[: len(sorted_keys) // 2]:
                self._data.pop(k, None)
        self._data[key] = {"ts": time.time(), "value": value}
        self._dirty = True

    def flush(self) -> None:
        if not self._dirty:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
            self._dirty = False
        except OSError as exc:
            logger.warning("TMDb cache write failed: %s", exc)


def default_cache_path() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home()))
    return Path(appdata) / "meowcal-sub-2" / "tmdb_cache.json"


def _normalize_for_key(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text).casefold().strip()
    return " ".join(normalized.split())


def _title_score(query: str, candidate: dict[str, Any]) -> float:
    q = _normalize_for_key(query)
    best = 0.0
    for field in ("name", "original_name"):
        value = candidate.get(field)
        if not value:
            continue
        score = float(fuzz.token_sort_ratio(q, _normalize_for_key(str(value))))
        if score > best:
            best = score
    aliases = candidate.get("alternative_titles") or []
    if isinstance(aliases, list):
        for alias in aliases:
            title = alias.get("title") if isinstance(alias, dict) else alias
            if not title:
                continue
            score = float(fuzz.token_sort_ratio(q, _normalize_for_key(str(title))))
            if score > best:
                best = score
    return best


def _extract_year(value: Any) -> int | None:
    if not isinstance(value, str) or len(value) < 4:
        return None
    try:
        return int(value[:4])
    except ValueError:
        return None


def poster_url_from_path(path: str | None, size: str = "w92") -> str | None:
    if not path:
        return None
    cleaned = path.strip()
    if not cleaned:
        return None
    if cleaned.startswith(("http://", "https://")):
        return cleaned
    if not cleaned.startswith("/"):
        cleaned = f"/{cleaned}"
    return f"{TMDB_IMAGE_BASE_URL}/{size}{cleaned}"


class TMDbClient:
    """Thin TMDb v3 wrapper with persistent cache and concurrency limit.

    Returns None on any failure (missing key, network error, no results). Never
    raises — cross-lingual merge is opportunistic, not load-bearing.
    """

    def __init__(
        self,
        api_key: str,
        *,
        cache: TMDbCache | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.cache = cache or TMDbCache(default_cache_path())
        self._client = http_client
        self._owns_client = http_client is None
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_LOOKUPS)

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def close(self) -> None:
        self.cache.flush()
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _client_obj(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=provider_timeout(SEARCH_TIMEOUT_SECONDS))
        return self._client

    async def find_by_imdb(self, imdb_id: str) -> TMDbSeries | None:
        if not self.enabled or not imdb_id:
            return None
        key = f"tmdb:find_imdb:{imdb_id.lower()}"
        cached = self.cache.get(key)
        if cached is not None:
            return _deserialize_series(cached)
        async with self._semaphore:
            data = await self._fetch(
                f"/find/{imdb_id}",
                {"external_source": "imdb_id"},
            )
        if data is None:
            return None
        tv_hits = data.get("tv_results") or []
        if not isinstance(tv_hits, list) or not tv_hits:
            self.cache.set(key, None)
            return None
        best = tv_hits[0]
        series = await self._detail_to_series(best, imdb_id_hint=imdb_id)
        self.cache.set(key, _serialize_series(series))
        return series

    async def search_tv(self, query: str, year_hint: int | None = None) -> TMDbSeries | None:
        if not self.enabled or not query:
            return None
        key = f"tmdb:search_tv:{_normalize_for_key(query)}|{year_hint or ''}"
        cached = self.cache.get(key)
        if cached is not None:
            return _deserialize_series(cached)
        params = {"query": query, "include_adult": "false"}
        if year_hint is not None:
            params["first_air_date_year"] = str(year_hint)
        async with self._semaphore:
            data = await self._fetch("/search/tv", params)
        if data is None:
            return None
        results = data.get("results") or []
        if not isinstance(results, list) or not results:
            self.cache.set(key, None)
            return None
        ranked = sorted(
            results,
            key=lambda item: (
                _title_score(query, item),
                float(item.get("popularity") or 0.0),
            ),
            reverse=True,
        )
        best = ranked[0]
        if _title_score(query, best) < MIN_TITLE_SCORE:
            self.cache.set(key, None)
            return None
        series = await self._detail_to_series(best)
        self.cache.set(key, _serialize_series(series))
        return series

    async def _detail_to_series(
        self,
        candidate: dict[str, Any],
        *,
        imdb_id_hint: str | None = None,
    ) -> TMDbSeries | None:
        tmdb_id = candidate.get("id")
        if not isinstance(tmdb_id, int):
            return None
        imdb_id = imdb_id_hint
        if not imdb_id:
            external = await self._external_ids(tmdb_id)
            imdb_id = external.get("imdb_id") if external else None
        return TMDbSeries(
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            name=str(candidate.get("name") or ""),
            original_name=str(candidate.get("original_name") or ""),
            first_air_year=_extract_year(candidate.get("first_air_date")),
            poster_path=str(candidate.get("poster_path") or "") or None,
        )

    async def fetch_series_details(self, tmdb_id: int) -> dict[str, Any] | None:
        """Calls /tv/{id} and returns {number_of_seasons, name}."""
        key = f"tmdb:series_details:{tmdb_id}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached if isinstance(cached, dict) else None
        async with self._semaphore:
            data = await self._fetch(f"/tv/{tmdb_id}", {})
        if data is None:
            self.cache.set(key, {})
            return None
        result = {
            "number_of_seasons": data.get("number_of_seasons"),
            "name": data.get("name") or "",
            "poster_path": data.get("poster_path") or "",
        }
        self.cache.set(key, result)
        return result

    async def fetch_poster_url(self, tmdb_id: int, media_type: str) -> str | None:
        """Fetch a poster URL for a TMDb movie or TV work."""
        if not self.enabled or not tmdb_id:
            return None
        kind = "movie" if media_type == "movie" else "tv"
        key = f"tmdb:poster:{kind}:{tmdb_id}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached if isinstance(cached, str) and cached else None
        async with self._semaphore:
            data = await self._fetch(f"/{kind}/{tmdb_id}", {})
        path = (data or {}).get("poster_path")
        url = poster_url_from_path(path if isinstance(path, str) else None)
        self.cache.set(key, url or "")
        return url

    async def fetch_season(self, tmdb_id: int, season_number: int) -> list[dict[str, Any]]:
        """Calls /tv/{id}/season/{n} and returns [{episode_number, name, air_date}]."""
        key = f"tmdb:season:{tmdb_id}:{season_number}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached if isinstance(cached, list) else []
        async with self._semaphore:
            data = await self._fetch(f"/tv/{tmdb_id}/season/{season_number}", {})
        raw_episodes = (data or {}).get("episodes") or []
        result = [
            {
                "episode_number": ep.get("episode_number"),
                "name": ep.get("name") or "",
                "air_date": ep.get("air_date") or "",
            }
            for ep in raw_episodes
            if isinstance(ep, dict) and isinstance(ep.get("episode_number"), int)
        ]
        self.cache.set(key, result)
        return result

    async def _external_ids(self, tmdb_id: int) -> dict[str, Any] | None:
        key = f"tmdb:external_ids:{tmdb_id}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        async with self._semaphore:
            data = await self._fetch(f"/tv/{tmdb_id}/external_ids", {})
        self.cache.set(key, data or {})
        return data

    async def _fetch(self, path: str, params: dict[str, str]) -> dict[str, Any] | None:
        query_params = dict(params)
        headers: dict[str, str] = {}
        # v4 read access tokens are JWTs ("eyJ..."); v3 keys are 32-char hex.
        if self.api_key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            query_params["api_key"] = self.api_key
        url = f"{TMDB_BASE_URL}{path}"
        try:
            client = await self._client_obj()
            response = await client.get(url, params=query_params, headers=headers)
        except (TimeoutError, httpx.HTTPError) as exc:
            logger.warning("TMDb request failed (%s): %s", path, exc)
            return None
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            logger.warning("TMDb %s returned %s", path, response.status_code)
            return None
        try:
            return response.json()
        except ValueError:
            return None


def _serialize_series(series: TMDbSeries | None) -> Any:
    if series is None:
        return None
    return {
        "tmdb_id": series.tmdb_id,
        "imdb_id": series.imdb_id,
        "name": series.name,
        "original_name": series.original_name,
        "first_air_year": series.first_air_year,
        "poster_path": series.poster_path,
    }


def _deserialize_series(value: Any) -> TMDbSeries | None:
    if not isinstance(value, dict):
        return None
    tmdb_id = value.get("tmdb_id")
    if not isinstance(tmdb_id, int):
        return None
    return TMDbSeries(
        tmdb_id=tmdb_id,
        imdb_id=value.get("imdb_id"),
        name=str(value.get("name") or ""),
        original_name=str(value.get("original_name") or ""),
        first_air_year=value.get("first_air_year") if isinstance(value.get("first_air_year"), int) else None,
        poster_path=value.get("poster_path") if isinstance(value.get("poster_path"), str) else None,
    )
