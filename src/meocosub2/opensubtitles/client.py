"""Async OpenSubtitles client."""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote_plus

import httpx
from rapidfuzz import fuzz

from meocosub2.errors import OpenSubtitlesError
from meocosub2.event_log import log_event
from meocosub2.languages import normalize_source_language
from meocosub2.opensubtitles.types import FeatureCandidate, SearchCatalog, SearchResult
from meocosub2.titleutil import canonical_title

logger = logging.getLogger(__name__)

BASE_URL = "https://api.opensubtitles.com/api/v1"
MAX_RETRIES = 3
MAX_QUERY_VARIANTS = 6
MAX_FEATURES_PER_QUERY = 25
MAX_FEATURES_TO_RESOLVE = 15
MAX_SUBTITLE_RESULTS_PER_QUERY = 200
MAX_SUBTITLE_PAGES_PER_QUERY = 4
MAX_PARALLEL_SUBTITLE_FETCHES = 5
MAX_SEARCH_RESULTS = 400
_TITLE_BONUS_EXACT = 120.0    # added when canonical alias == canonical title
_TITLE_BONUS_PREFIX = 72.0    # added when one is a prefix of the other
_TITLE_BONUS_SUBSTR = 42.0    # added when one contains the other
STRONG_MATCH_THRESHOLD = 185.0  # exact title ratio plus _TITLE_BONUS_EXACT exceeds this
ORG_SEARCH_URL = "https://www.opensubtitles.org/en/search2/moviename-{query}/sublanguageid-all"
ORG_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0 Safari/537.36"
PAREN_YEAR_SUFFIX_PATTERN = re.compile(r"^(?P<title>.+?)\s*\((?P<year>19\d{2}|20\d{2}|21\d{2})\)\s*$")
TRAILING_YEAR_SUFFIX_PATTERN = re.compile(r"^(?P<title>.+?)\s+(?P<year>19\d{2}|20\d{2}|21\d{2})\s*$")
EPISODE_PATTERN = re.compile(r"\bS(?P<season>\d{1,2})E(?P<episode>\d{1,3})\b", re.IGNORECASE)


@dataclass(frozen=True)
class SearchIntent:
    original_query: str
    query: str
    normalized_query: str
    aliases: tuple[str, ...]
    normalized_aliases: tuple[str, ...]
    media_type: str | None
    year: int | None = None
    season: int | None = None
    episode: int | None = None


class _OpenSubtitlesOrgAliasParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.titles: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return

        attributes = {name: value or "" for name, value in attrs}
        title = attributes.get("title", "")
        css = attributes.get("class", "")
        if "bnone" not in css or not title.lower().startswith("subtitles - "):
            return

        cleaned = html.unescape(title[len("subtitles - "):]).strip()
        if cleaned:
            self.titles.append(re.sub(r"\s+", " ", cleaned))


class OpenSubtitlesClient:
    def __init__(
        self,
        api_key: str,
        user_agent: str = "Meowcal-Sub-2/0.1.0",
        cache_dir: Path | None = None,
        enable_org_fallback: bool = False,
    ) -> None:
        self.api_key = api_key
        self.user_agent = user_agent
        self.cache_dir = cache_dir or (Path.home() / ".cache" / "meowcal-sub-2")
        self.enable_org_fallback = enable_org_fallback
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "Api-Key": api_key,
                "User-Agent": user_agent,
                "Content-Type": "application/json",
            },
            follow_redirects=True,
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
            started = time.perf_counter()
            response = await self._client.request(method, path, **kwargs)
            log_event(
                "provider.http",
                layer="backend",
                provider="opensubtitles",
                method=method,
                path=path,
                status_code=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000),
                attempt=attempt + 1,
                params=kwargs.get("params"),
            )
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
        return (await self.search_catalog(query, languages, media_type=media_type)).results

    async def search_catalog(
        self,
        query: str,
        languages: str,
        media_type: str | None = None,
    ) -> SearchCatalog:
        intent = self._build_search_intent(query, media_type)
        normalized_languages = self._normalize_languages(languages)
        results, matches = await self._search_with_queries(intent, normalized_languages, list(intent.aliases))

        if self.enable_org_fallback and not self._has_strong_results(results):
            org_aliases = await self._search_org_aliases(intent.query)
            extra_queries = self._dedupe_queries(
                [alias for alias in org_aliases if alias.casefold() not in {item.casefold() for item in intent.aliases}]
            )
            for extra_query in extra_queries:
                extra_results, extra_matches = await self._search_with_queries(
                    intent,
                    normalized_languages,
                    [extra_query],
                    feature_hint_alias=extra_query,
                )
                for result in extra_results:
                    query_alignment = self._score_alias_values(intent.normalized_query, [extra_query]) if intent.normalized_query else 0.0
                    alias_bonus = min(
                        60.0,
                        self._score_alias_values(
                            canonical_title(extra_query),
                            [result.parent_title or "", result.title, result.movie_name or ""],
                        )
                        * min(1.0, query_alignment / 180.0)
                        * 0.3,
                    )
                    result.match_score += alias_bonus
                results = self._merge_results(results, extra_results)
                matches = self._merge_features(matches, extra_matches)

        slash_variant = self._maybe_slash_variant(intent.query)
        if slash_variant and slash_variant.casefold() not in {alias.casefold() for alias in intent.aliases} and not results:
            slash_results, slash_matches = await self._search_with_queries(intent, normalized_languages, [slash_variant])
            if slash_matches:
                matches = self._merge_features(matches, slash_matches)
            if self._has_strong_title_results(intent, slash_results):
                results = self._merge_results(results, slash_results)

        return SearchCatalog(results=self._sort_results(results), matches=self._sort_features(matches))

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
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(link)
            response.raise_for_status()
            destination.write_bytes(response.content)
        return destination

    async def _search_with_queries(
        self,
        intent: SearchIntent,
        languages: str,
        queries: list[str],
        feature_hint_alias: str | None = None,
    ) -> tuple[list[SearchResult], list[FeatureCandidate]]:
        collected: dict[str, SearchResult] = {}
        matched_features: dict[int, FeatureCandidate] = {}
        ranked_features = await self._collect_ranked_features(intent, queries, feature_hint_alias=feature_hint_alias)
        for feature in ranked_features:
            matched_features[feature.id] = feature

        sem = asyncio.Semaphore(MAX_PARALLEL_SUBTITLE_FETCHES)

        async def _fetch_guarded(feature: FeatureCandidate) -> list[SearchResult]:
            async with sem:
                return await self._fetch_feature_subtitles(feature, languages, intent)

        candidates = ranked_features[:MAX_FEATURES_TO_RESOLVE]
        all_feature_results = await asyncio.gather(*[_fetch_guarded(f) for f in candidates])
        for feature, feature_results in zip(candidates, all_feature_results):
            for result in feature_results:
                result.match_score = max(result.match_score, feature.match_score + self._score_search_result(intent, result))
                self._store_result(collected, result)

        direct_exact_only = self._should_run_exact_direct_recovery(intent, list(collected.values()))
        if direct_exact_only or self._should_run_direct_subtitle_lookup(intent, list(collected.values())):
            for query_index, query_variant in enumerate(queries[:MAX_QUERY_VARIANTS]):
                direct_results = await self._search_direct_subtitles(intent, languages, query_variant)
                query_bonus = max(0.0, 10.0 - (query_index * 2.0))
                for result in direct_results:
                    if direct_exact_only and not self._result_matches_query_exactly(intent, result):
                        continue
                    result.match_score = max(result.match_score, self._score_search_result(intent, result) + query_bonus)
                    self._store_result(collected, result)

        return list(collected.values()), list(matched_features.values())

    async def _collect_ranked_features(
        self,
        intent: SearchIntent,
        queries: list[str],
        feature_hint_alias: str | None = None,
    ) -> list[FeatureCandidate]:
        features_by_id: dict[int, FeatureCandidate] = {}
        hint_alias = canonical_title(feature_hint_alias or "")
        for query_index, query_variant in enumerate(queries[:MAX_QUERY_VARIANTS]):
            params: dict[str, str] = {"query": query_variant, "full_search": "true"}
            feature_type = self._feature_type_filter(intent.media_type)
            if feature_type:
                params["type"] = feature_type
            if intent.year is not None:
                params["year"] = str(intent.year)

            response = await self._request("GET", "/features", params=params)
            if response.status_code != 200:
                raise OpenSubtitlesError(f"OpenSubtitles feature search failed: {response.status_code}")

            payload = response.json()
            logger.debug("OS /features query=%r → %d features", query_variant, len(payload.get("data", [])))
            for item in payload.get("data", [])[:MAX_FEATURES_PER_QUERY]:
                feature = self._parse_feature(item)
                score = self._score_feature(intent, feature, query_index)
                if hint_alias:
                    score += min(
                        50.0,
                        self._score_alias_values(hint_alias, [feature.title, feature.parent_title or "", *feature.aka_titles]) * 0.2,
                    )
                feature.match_score = score
                existing = features_by_id.get(feature.id)
                if existing is None or score > existing.match_score:
                    features_by_id[feature.id] = feature

        return sorted(
            features_by_id.values(),
            key=lambda feature: (feature.match_score, feature.subtitles_count, feature.id),
            reverse=True,
        )

    async def _fetch_feature_subtitles(
        self,
        feature: FeatureCandidate,
        languages: str,
        intent: SearchIntent,
    ) -> list[SearchResult]:
        params: dict[str, str] = {"languages": self._to_api_languages(languages)}
        subtitle_type = self._subtitle_type_filter(intent.media_type or feature.media_type)
        if subtitle_type:
            params["type"] = subtitle_type

        if feature.media_type == "tvshow":
            params["parent_feature_id"] = str(feature.id)
            if intent.season is not None:
                params["season_number"] = str(intent.season)
            if intent.episode is not None:
                params["episode_number"] = str(intent.episode)
            results = await self._search_subtitles_by_params(params)
            if results:
                return results
            for id_key, id_val in [("imdb_id", feature.imdb_id), ("tmdb_id", feature.tmdb_id)]:
                if not id_val:
                    continue
                fallback: dict[str, str] = {"languages": params["languages"], id_key: id_val, "type": "episode"}
                if intent.season is not None:
                    fallback["season_number"] = str(intent.season)
                if intent.episode is not None:
                    fallback["episode_number"] = str(intent.episode)
                results = await self._search_subtitles_by_params(fallback)
                if results:
                    return results
            return []

        params["id"] = str(feature.id)
        results = await self._search_subtitles_by_params(params)
        if results:
            return results

        fallback_params: list[dict[str, str]] = []
        api_languages = self._to_api_languages(languages)
        if feature.imdb_id:
            fallback = {"imdb_id": feature.imdb_id, "languages": api_languages}
            if subtitle_type:
                fallback["type"] = subtitle_type
            if intent.year is not None:
                fallback["year"] = str(intent.year)
            fallback_params.append(fallback)
        if feature.tmdb_id:
            fallback = {"tmdb_id": feature.tmdb_id, "languages": api_languages}
            if subtitle_type:
                fallback["type"] = subtitle_type
            if intent.year is not None:
                fallback["year"] = str(intent.year)
            fallback_params.append(fallback)

        for fallback in fallback_params:
            results = await self._search_subtitles_by_params(fallback)
            if results:
                return results
        return []

    async def _search_direct_subtitles(
        self,
        intent: SearchIntent,
        languages: str,
        query: str,
    ) -> list[SearchResult]:
        params: dict[str, str] = {"query": query, "languages": self._to_api_languages(languages)}
        subtitle_type = self._subtitle_type_filter(intent.media_type)
        if subtitle_type:
            params["type"] = subtitle_type
        if intent.year is not None:
            params["year"] = str(intent.year)
        if intent.season is not None:
            params["season_number"] = str(intent.season)
        if intent.episode is not None:
            params["episode_number"] = str(intent.episode)
        return await self._search_subtitles_by_params(params)

    async def _search_subtitles_by_params(self, params: dict[str, str]) -> list[SearchResult]:
        results: list[SearchResult] = []
        for page in range(1, MAX_SUBTITLE_PAGES_PER_QUERY + 1):
            paged = dict(params)
            paged["page"] = str(page)
            response = await self._request("GET", "/subtitles", params=paged)
            if response.status_code != 200:
                raise OpenSubtitlesError(f"OpenSubtitles search failed: {response.status_code}")
            payload = response.json()
            data = payload.get("data", [])
            if not isinstance(data, list) or not data:
                break
            for item in data:
                results.append(self._parse_result(item))
                if len(results) >= MAX_SUBTITLE_RESULTS_PER_QUERY:
                    break
            if len(results) >= MAX_SUBTITLE_RESULTS_PER_QUERY:
                break
            total_pages = payload.get("total_pages")
            if isinstance(total_pages, int) and page >= total_pages:
                break
        lang_summary = ",".join(sorted({r.language for r in results})) if results else "none"
        logger.debug("OS /subtitles params=%s → %d results [langs: %s]", params, len(results), lang_summary)
        return results

    async def _search_org_aliases(self, query: str) -> list[str]:
        slug = quote_plus(" ".join(query.split()))
        if not slug:
            return []

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=20.0,
                headers={"User-Agent": ORG_USER_AGENT},
            ) as client:
                response = await client.get(ORG_SEARCH_URL.format(query=slug))
        except Exception:
            return []

        if response.status_code != 200:
            return []

        parser = _OpenSubtitlesOrgAliasParser()
        parser.feed(response.text)
        return self._dedupe_queries(parser.titles)[:MAX_QUERY_VARIANTS]

    def _build_search_intent(self, query: str, media_type: str | None) -> SearchIntent:
        original_query = " ".join(query.split())
        working_query = original_query
        year: int | None = None
        season: int | None = None
        episode: int | None = None

        episode_match = EPISODE_PATTERN.search(working_query)
        if episode_match:
            season = int(episode_match.group("season"))
            episode = int(episode_match.group("episode"))
            working_query = EPISODE_PATTERN.sub(" ", working_query)
            media_type = media_type or "episode"

        working_query, year = self._extract_trailing_year(working_query)

        cleaned_query = re.sub(r"\s+", " ", working_query).strip(" -_:/")
        query_value = cleaned_query or original_query
        aliases = tuple(self._build_query_variants(query_value))
        normalized_aliases = tuple(canonical_title(alias) for alias in aliases)
        return SearchIntent(
            original_query=original_query,
            query=query_value,
            normalized_query=canonical_title(query_value),
            aliases=aliases,
            normalized_aliases=normalized_aliases,
            media_type=media_type,
            year=year,
            season=season,
            episode=episode,
        )

    def _build_query_variants(self, query: str) -> list[str]:
        query = " ".join(query.split())
        if not query:
            return []

        variants = [query]
        relaxed = re.sub(r"[\"'`]", "", query)
        relaxed = re.sub(r"[:|]", " ", relaxed)
        relaxed = re.sub(r"[\\/]+", " ", relaxed)
        relaxed = re.sub(r"[-_.]+", " ", relaxed)
        relaxed = re.sub(r"\s+", " ", relaxed).strip()
        if relaxed:
            variants.append(relaxed)

        tokens = canonical_title(query).split()
        if tokens:
            variants.append(" ".join(token.capitalize() for token in tokens))
        if tokens == ["fate", "fake"]:
            variants.extend(["Fate strange Fake", "Fate/strange Fake"])
        if tokens == ["fate", "zero"]:
            variants.append("Fate/Zero")

        return self._dedupe_queries(variants)[:MAX_QUERY_VARIANTS]

    def _feature_type_filter(self, media_type: str | None) -> str | None:
        if media_type in {"movie", "episode", "tvshow"}:
            return media_type
        return None

    def _subtitle_type_filter(self, media_type: str | None) -> str | None:
        if media_type == "tvshow":
            return "episode"
        if media_type in {"movie", "episode"}:
            return media_type
        return None

    def _normalize_languages(self, languages: str) -> str:
        codes = sorted({part.strip() for part in languages.split(",") if part.strip()})
        return ",".join(codes)

    # OpenSubtitles API uses BCP-47 region codes: "zh-cn" Simplified, "zh-tw"
    # Traditional. Our internal codes are "zh" / "zht". The legacy "zhs" / "zht"
    # codes return 0 results from the v1 API.
    _INTERNAL_TO_OS_LANG: dict[str, str] = {"zh": "zh-cn", "zht": "zh-tw"}

    def _to_api_languages(self, languages: str) -> str:
        codes = [c.strip() for c in languages.split(",") if c.strip()]
        return ",".join(self._INTERNAL_TO_OS_LANG.get(c, c) for c in codes)

    def _score_feature(self, intent: SearchIntent, feature: FeatureCandidate, query_index: int) -> float:
        title_score = self._score_title_values(
            intent,
            [feature.title, feature.parent_title or "", *feature.aka_titles],
        )
        score = title_score + min(feature.subtitles_count, 20) + max(0.0, 12.0 - (query_index * 2.0))

        if intent.media_type:
            score += 24.0 if feature.media_type == intent.media_type else -16.0
        if intent.year is not None and feature.year is not None:
            if feature.year == intent.year:
                score += 24.0
            else:
                score -= min(abs(feature.year - intent.year), 5) * 4.0
        if intent.season is not None and feature.season == intent.season:
            score += 14.0
        if intent.episode is not None and feature.episode == intent.episode:
            score += 14.0

        return score

    def _score_search_result(self, intent: SearchIntent, result: SearchResult) -> float:
        title_score = self._score_title_values(
            intent,
            [result.parent_title or "", result.title, result.movie_name or ""],
        )
        score = title_score + min(result.download_count / 50.0, 20.0)

        if intent.media_type:
            score += 20.0 if result.media_type == intent.media_type else -14.0
        elif result.media_type == "episode" and result.parent_title:
            score += 8.0

        if intent.year is not None and result.year is not None:
            if result.year == intent.year:
                score += 20.0
            else:
                score -= min(abs(result.year - intent.year), 5) * 4.0
        if intent.season is not None and result.season == intent.season:
            score += 14.0
        if intent.episode is not None and result.episode == intent.episode:
            score += 14.0
        if result.parent_title and result.media_type == "episode":
            score += 10.0

        return score

    def _score_title_values(self, intent: SearchIntent, values: list[str]) -> float:
        best = 0.0
        for alias in intent.normalized_aliases:
            if not alias:
                continue
            best = max(best, self._score_alias_values(alias, values))
        return best

    def _dedupe_queries(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            cleaned = re.sub(r"\s+", " ", value).strip()
            dedupe_key = cleaned.casefold()
            if not cleaned or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            deduped.append(cleaned)
        return deduped

    def _extract_trailing_year(self, query: str) -> tuple[str, int | None]:
        for pattern in (PAREN_YEAR_SUFFIX_PATTERN, TRAILING_YEAR_SUFFIX_PATTERN):
            match = pattern.match(query)
            if match:
                title = re.sub(r"\s+", " ", match.group("title")).strip(" -_:/")
                if title:
                    return title, int(match.group("year"))
        return query, None

    def _maybe_slash_variant(self, query: str) -> str | None:
        if "/" in query:
            return None
        tokens = re.findall(r"\w+", query, flags=re.UNICODE)
        if len(tokens) != 2:
            return None
        return f"{tokens[0].capitalize()}/{tokens[1].capitalize()}"

    def _score_alias_values(self, alias: str, values: list[str]) -> float:
        best = 0.0
        for value in values:
            normalized_value = canonical_title(value)
            if not normalized_value:
                continue
            score = max(
                fuzz.ratio(alias, normalized_value),
                fuzz.token_set_ratio(alias, normalized_value),
            )
            if normalized_value == alias:
                score += _TITLE_BONUS_EXACT
            elif normalized_value.startswith(alias) or alias.startswith(normalized_value):
                score += _TITLE_BONUS_PREFIX
            elif alias in normalized_value or normalized_value in alias:
                score += _TITLE_BONUS_SUBSTR
            best = max(best, score)
        return best

    def _has_strong_results(self, results: list[SearchResult]) -> bool:
        return any(result.match_score >= STRONG_MATCH_THRESHOLD for result in results)

    def _should_run_direct_subtitle_lookup(self, intent: SearchIntent, results: list[SearchResult]) -> bool:
        if not self._has_strong_results(results):
            return True
        return False

    def _should_run_exact_direct_recovery(self, intent: SearchIntent, results: list[SearchResult]) -> bool:
        if not self._has_strong_results(results):
            return False
        if not self._is_short_generic_query(intent):
            return False
        return not any(self._result_matches_query_exactly(intent, result) for result in results)

    def _is_short_generic_query(self, intent: SearchIntent) -> bool:
        tokens = intent.normalized_query.split()
        return (
            intent.media_type is None
            and intent.year is None
            and intent.season is None
            and intent.episode is None
            and len(tokens) == 1
            and tokens[0].isascii()
            and tokens[0].isalnum()
            and len(tokens[0]) <= 4
        )

    def _result_matches_query_exactly(self, intent: SearchIntent, result: SearchResult) -> bool:
        if not intent.normalized_query:
            return False
        values = [result.parent_title or "", result.title, result.movie_name or ""]
        return any(canonical_title(value) == intent.normalized_query for value in values)

    def _has_strong_title_results(self, intent: SearchIntent, results: list[SearchResult]) -> bool:
        for result in results:
            if (
                self._score_title_values(intent, [result.parent_title or "", result.title, result.movie_name or ""])
                >= STRONG_MATCH_THRESHOLD
            ):
                return True
            if (
                intent.normalized_query
                and result.season is not None
                and result.episode is not None
                and canonical_title(result.movie_name or "").startswith(intent.normalized_query)
            ):
                return True
        return False

    def _merge_results(self, left: list[SearchResult], right: list[SearchResult]) -> list[SearchResult]:
        merged: dict[str, SearchResult] = {}
        for result in [*left, *right]:
            self._store_result(merged, result)
        return list(merged.values())

    def _merge_features(self, left: list[FeatureCandidate], right: list[FeatureCandidate]) -> list[FeatureCandidate]:
        merged: dict[int, FeatureCandidate] = {}
        for feature in [*left, *right]:
            current = merged.get(feature.id)
            if current is None or (feature.match_score, feature.subtitles_count) > (current.match_score, current.subtitles_count):
                merged[feature.id] = feature
        return list(merged.values())

    def _sort_results(self, results: list[SearchResult]) -> list[SearchResult]:
        return sorted(
            results,
            key=lambda result: (result.match_score, result.download_count, result.file_id),
            reverse=True,
        )[:MAX_SEARCH_RESULTS]

    def _sort_features(self, matches: list[FeatureCandidate]) -> list[FeatureCandidate]:
        return sorted(
            matches,
            key=lambda feature: (feature.match_score, feature.subtitles_count, feature.id),
            reverse=True,
        )[:MAX_SEARCH_RESULTS]

    def _store_result(self, collected: dict[str, SearchResult], result: SearchResult) -> None:
        key = str(result.file_id or result.id)
        current = collected.get(key)
        if current is None or (result.match_score, result.download_count) > (
            current.match_score,
            current.download_count,
        ):
            collected[key] = result

    def _parse_feature(self, item: dict[str, object]) -> FeatureCandidate:
        attributes = item.get("attributes", {})
        if not isinstance(attributes, dict):
            attributes = {}

        feature_type = str(attributes.get("feature_type", "")).lower()
        if "tvshow" in feature_type:
            media_type = "tvshow"
        elif "episode" in feature_type:
            media_type = "episode"
        else:
            media_type = "movie"

        title = str(attributes.get("original_title") or attributes.get("title") or "")
        aka_titles_raw = attributes.get("title_aka", [])
        aka_titles = tuple(str(title_aka) for title_aka in aka_titles_raw if str(title_aka).strip()) if isinstance(aka_titles_raw, list) else ()

        return FeatureCandidate(
            id=self._coerce_int(item.get("id") or attributes.get("feature_id")),
            title=title,
            year=self._coerce_optional_int(attributes.get("year")),
            imdb_id=self._coerce_optional_string(attributes.get("imdb_id")),
            tmdb_id=self._coerce_optional_string(attributes.get("tmdb_id")),
            media_type=media_type,
            season=self._coerce_optional_int(attributes.get("season_number")),
            episode=self._coerce_optional_int(attributes.get("episode_number")),
            parent_title=self._coerce_optional_string(attributes.get("parent_title")),
            parent_imdb_id=self._coerce_optional_string(attributes.get("parent_imdb_id")),
            parent_tmdb_id=self._coerce_optional_string(attributes.get("parent_tmdb_id")),
            subtitles_count=self._coerce_int(attributes.get("subtitles_count")),
            aka_titles=aka_titles,
        )

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
            year=self._coerce_optional_int(feature_details.get("year")),
            imdb_id=self._coerce_optional_string(feature_details.get("imdb_id")),
            media_type=media_type,
            season=self._coerce_optional_int(feature_details.get("season_number")),
            episode=self._coerce_optional_int(feature_details.get("episode_number")),
            language=normalize_source_language(str(attributes.get("language", ""))),
            download_count=self._coerce_int(attributes.get("download_count")),
            file_id=self._coerce_int(file_info.get("file_id")),
            file_name=str(file_info.get("file_name", "")),
            parent_title=self._coerce_optional_string(feature_details.get("parent_title")),
            parent_imdb_id=self._coerce_optional_string(feature_details.get("parent_imdb_id")),
            parent_feature_id=self._coerce_optional_int(feature_details.get("parent_feature_id")),
            tmdb_id=self._coerce_optional_string(feature_details.get("tmdb_id")),
            parent_tmdb_id=self._coerce_optional_string(feature_details.get("parent_tmdb_id")),
            feature_id=self._coerce_optional_int(feature_details.get("feature_id")),
            movie_name=self._coerce_optional_string(feature_details.get("movie_name")),
        )

    def _coerce_int(self, value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _coerce_optional_int(self, value: object) -> int | None:
        try:
            return int(value) if value not in {None, ""} else None
        except (TypeError, ValueError):
            return None

    def _coerce_optional_string(self, value: object) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None
