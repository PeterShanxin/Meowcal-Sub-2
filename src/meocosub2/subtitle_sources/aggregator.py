"""Subtitle source aggregation and result ranking."""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from meocosub2.config import AppConfig
from meocosub2.errors import SubtitleSourceError
from meocosub2.event_log import event_correlation, log_event
from meocosub2.subtitle_sources.assrt import AssrtProvider
from meocosub2.subtitle_sources.opensubtitles import OpenSubtitlesProvider
from meocosub2.subtitle_sources.subdl import SubdlProvider
from meocosub2.subtitle_sources.season_skeleton import build_season_skeleton
from meocosub2.subtitle_sources.tmdb import TMDbClient, TMDbSeries, poster_url_from_path
from meocosub2.subtitle_sources.types import (
    AggregatedEpisode,
    AggregatedSearchCatalog,
    AggregatedSeason,
    AggregatedSubtitleResult,
    AggregatedTitleMatch,
    AggregatedWork,
    ProviderSearchCatalog,
    ProviderSubtitleMatch,
    ProviderSubtitleResult,
    SubtitleSourceProvider,
    WorkChip,
)
from meocosub2.subtitle_sources.utils import (
    EPISODE_PATTERN,
    PROVIDER_RANK,
    canonical_title,
    extract_season_suffix,
    language_priority,
    match_group_key,
    media_type_category,
    split_query_year,
    title_similarity,
    work_key,
)

PROVIDER_CHIP_LABELS = {
    "opensubtitles": "OpenSubtitles",
    "subdl": "SubDL",
    "assrt": "ASSRT",
}


YEAR_EXACT_BONUS = 20.0
YEAR_NEAR_PENALTY = 4.0
YEAR_MISMATCH_PENALTY = 15.0
YEAR_NEAR_RANGE = 3
BARE_TITLE_SERIES_BONUS = 24.0
BARE_TITLE_EPISODE_PENALTY = 24.0
PARENT_SERIES_BONUS = 50.0
IMPLICIT_EPISODE_PENALTY = 80.0
WORK_RANK_EXACT_SERIES = 520
WORK_RANK_EXACT_MOVIE_YEAR = 540
WORK_RANK_PREFIX = 450
WORK_RANK_EXACT_MOVIE = 420
WORK_RANK_CONTAINS = 380
WORK_RANK_EXACT_MOVIE_WITH_SERIES = 330
WORK_YEAR_EXACT_MOVIE = 500
WORK_YEAR_EXACT_START = 450
WORK_YEAR_IN_RANGE = 300
WORK_YEAR_NEAR_BASE = 100
QUERY_ALIASES = {
    "fate fake": "Fate/strange Fake",
    "fate faker": "Fate/strange Fake",
    "fate strange faker": "Fate/strange Fake",
}
MAX_TMDB_EAGER_WORKS = 24
MAX_TMDB_EAGER_WORKS_FOR_GENERIC_QUERY = 12


class SubtitleSearchAggregator:
    def __init__(
        self,
        config: AppConfig,
        *,
        tmdb_client: TMDbClient | None = None,
    ) -> None:
        self.config = config
        self.providers: tuple[SubtitleSourceProvider, ...] = (
            SubdlProvider(config),
            AssrtProvider(config),
            OpenSubtitlesProvider(config),
        )
        if tmdb_client is None and config.tmdb_api_key and config.tmdb_merge_enabled:
            tmdb_client = TMDbClient(config.tmdb_api_key)
        self._tmdb_client = tmdb_client

    async def search_catalog(
        self,
        query: str,
        languages: str,
        correlation_id: str | None = None,
    ) -> AggregatedSearchCatalog:
        clean_title, query_year = split_query_year(query)
        dispatch_query = _rewrite_query_alias(clean_title or query)
        started = time.perf_counter()
        log_event(
            "aggregator.search.start",
            layer="backend",
            correlation_id=correlation_id,
            query=dispatch_query,
            languages=languages,
            providers=[provider.provider_code for provider in self.providers],
            tmdb_enabled=bool(self._tmdb_client and self._tmdb_client.enabled),
        )
        with event_correlation(correlation_id):
            responses = await asyncio.gather(
                *(self._search_provider(provider, dispatch_query, languages, correlation_id) for provider in self.providers),
                return_exceptions=True,
            )

        catalogs: list[ProviderSearchCatalog] = []
        warnings: list[str] = []
        errors: list[str] = []
        for provider, response in zip(self.providers, responses, strict=False):
            if isinstance(response, Exception):
                errors.append(f"{provider.provider_label}: {response}")
                continue
            catalogs.append(response)
            warnings.extend(response.warnings)

        if not catalogs:
            raise SubtitleSourceError("All subtitle sources failed.")

        merge_started = time.perf_counter()
        aggregated = self._merge_catalogs(catalogs, languages, query_year, dispatch_query)
        log_event(
            "aggregator.merge.done",
            layer="backend",
            correlation_id=correlation_id,
            duration_ms=round((time.perf_counter() - merge_started) * 1000),
            results=len(aggregated.results),
            matches=len(aggregated.matches),
            works=len(aggregated.works),
        )
        aggregated.warnings.extend(warnings)
        if not aggregated.results and errors:
            raise SubtitleSourceError("; ".join(errors))
        aggregated.warnings.extend(errors)
        works_are_ranked = False
        if self._tmdb_client is not None and self._tmdb_client.enabled and aggregated.works:
            tmdb_started = time.perf_counter()
            identified_works = await self._merge_works_via_tmdb(aggregated.works, dispatch_query, correlation_id)
            ranked_works = self._sort_works(identified_works, dispatch_query, query_year)
            works_are_ranked = True
            eager_limit = self._tmdb_eager_limit(dispatch_query, ranked_works)
            eager_works = ranked_works[:eager_limit]
            deferred_works = ranked_works[eager_limit:]
            eager_works = await self._apply_tmdb_season_skeleton(eager_works, correlation_id)
            eager_works = await self._apply_tmdb_posters(eager_works, correlation_id)
            aggregated.works = [*eager_works, *deferred_works]
            log_event(
                "aggregator.tmdb.done",
                layer="backend",
                correlation_id=correlation_id,
                duration_ms=round((time.perf_counter() - tmdb_started) * 1000),
                works=len(aggregated.works),
                enriched_works=len(eager_works),
                deferred_works=len(deferred_works),
            )
        if not works_are_ranked:
            aggregated.works = self._sort_works(aggregated.works, dispatch_query, query_year)
        episode_coverage = _episode_coverage_summary(aggregated.works)
        if episode_coverage:
            log_event(
                "aggregator.episode_coverage",
                layer="backend",
                correlation_id=correlation_id,
                works=episode_coverage,
            )
        log_event(
            "aggregator.search.done",
            layer="backend",
            correlation_id=correlation_id,
            duration_ms=round((time.perf_counter() - started) * 1000),
            results=len(aggregated.results),
            matches=len(aggregated.matches),
            works=len(aggregated.works),
            warnings=len(aggregated.warnings),
            errors=len(errors),
        )
        return aggregated

    def _tmdb_eager_limit(self, query: str, works: list[AggregatedWork]) -> int:
        if len(works) <= MAX_TMDB_EAGER_WORKS:
            return len(works)
        if _is_generic_tmdb_query(query):
            return min(len(works), MAX_TMDB_EAGER_WORKS_FOR_GENERIC_QUERY)
        return min(len(works), MAX_TMDB_EAGER_WORKS)

    async def _search_provider(
        self,
        provider: SubtitleSourceProvider,
        query: str,
        languages: str,
        correlation_id: str | None,
    ) -> ProviderSearchCatalog:
        started = time.perf_counter()
        log_event(
            "provider.search.start",
            layer="backend",
            correlation_id=correlation_id,
            provider=provider.provider_code,
            query=query,
            languages=languages,
        )
        try:
            catalog = await provider.search_catalog(query, languages)
        except Exception as exc:
            log_event(
                "provider.search.error",
                layer="backend",
                level="error",
                correlation_id=correlation_id,
                provider=provider.provider_code,
                duration_ms=round((time.perf_counter() - started) * 1000),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise
        log_event(
            "provider.search.done",
            layer="backend",
            correlation_id=correlation_id,
            provider=provider.provider_code,
            duration_ms=round((time.perf_counter() - started) * 1000),
            matches=len(catalog.matches),
            results=len(catalog.results),
            warnings=len(catalog.warnings),
        )
        return catalog

    async def download(self, result: AggregatedSubtitleResult) -> Path:
        provider = next(item for item in self.providers if item.provider_code == result.provider)
        return await provider.download(result.provider_result)

    def _year_bonus(self, match_year: int | None, query_year: int | None) -> float:
        if query_year is None or match_year is None:
            return 0.0
        if match_year == query_year:
            return YEAR_EXACT_BONUS
        diff = abs(match_year - query_year)
        if diff <= YEAR_NEAR_RANGE:
            return -YEAR_NEAR_PENALTY * diff
        return -YEAR_MISMATCH_PENALTY

    def _merge_catalogs(
        self,
        catalogs: Iterable[ProviderSearchCatalog],
        languages: str,
        query_year: int | None = None,
        query: str = "",
    ) -> AggregatedSearchCatalog:
        requested_languages = {code.strip() for code in languages.split(",") if code.strip()}
        query_requests_episode = bool(EPISODE_PATTERN.search(query))
        all_matches: list[ProviderSubtitleMatch] = []
        all_results: list[ProviderSubtitleResult] = []
        provider_match_map: dict[str, str] = {}
        for catalog in catalogs:
            all_matches.extend(catalog.matches)
            all_results.extend(catalog.results)

        if not all_matches and not all_results:
            return AggregatedSearchCatalog(matches=[], results=[])

        group_order: dict[tuple[str, str, int, int, int], str] = {}
        groups: dict[str, dict[str, object]] = {}

        def ensure_group(
            *,
            title: str,
            media_type: str,
            year: int | None,
            season: int | None,
            episode: int | None,
            parent_title: str | None,
            imdb_id: str | None,
            tmdb_id: str | None,
            provider: str,
            provider_label: str,
            subtitles_count: int,
            match_score: float,
        ) -> str:
            key = match_group_key(title, media_type, year, season, episode, parent_title)
            # Grouping by canonical title metadata keeps the UI stable even when
            # different providers describe the same title with slightly different ids.
            if key in group_order:
                group_id = group_order[key]
                group = groups[group_id]
            else:
                group_id = f"match-{len(group_order) + 1}"
                group_order[key] = group_id
                group = groups[group_id] = {
                    "title": title,
                    "year": year,
                    "imdb_id": imdb_id,
                    "tmdb_id": tmdb_id,
                    "media_type": media_type,
                    "season": season,
                    "episode": episode,
                    "parent_title": parent_title,
                    "subtitles_count": 0,
                    "match_score": 0.0,
                    "providers": set(),
                    "provider_labels": set(),
                }
            group["subtitles_count"] = int(group["subtitles_count"]) + max(subtitles_count, 0)
            group["match_score"] = max(float(group["match_score"]), match_score)
            group["providers"].add(provider)
            group["provider_labels"].add(provider_label)
            return group_id

        for item in all_matches:
            provider_match_map[item.id] = ensure_group(
                title=item.title,
                media_type=item.media_type,
                year=item.year,
                season=item.season,
                episode=item.episode,
                parent_title=item.parent_title,
                imdb_id=item.imdb_id,
                tmdb_id=item.tmdb_id,
                provider=item.provider,
                provider_label=item.provider_label,
                subtitles_count=item.subtitles_count,
                match_score=item.match_score,
            )

        aggregated_results: list[AggregatedSubtitleResult] = []
        for index, item in enumerate(all_results, start=1):
            mapped_match_id = provider_match_map.get(item.match_id)
            # If a result carries explicit episode metadata, route it to a per-
            # episode group instead of collapsing it into the parent tvshow group.
            # OpenSubtitles returns every episode result under the parent feature's
            # match id, so without this we would lose all season/episode breakdown.
            promote_to_episode = (
                item.media_type == "episode"
                and item.season is not None
                and item.episode is not None
            )
            if promote_to_episode:
                match_id = ensure_group(
                    title=item.title,
                    media_type="episode",
                    year=item.year,
                    season=item.season,
                    episode=item.episode,
                    parent_title=item.parent_title,
                    imdb_id=item.imdb_id,
                    tmdb_id=item.tmdb_id,
                    provider=item.provider,
                    provider_label=item.provider_label,
                    subtitles_count=1,
                    match_score=item.match_score,
                )
            elif mapped_match_id is None:
                match_id = ensure_group(
                    title=item.title,
                    media_type=item.media_type,
                    year=item.year,
                    season=item.season,
                    episode=item.episode,
                    parent_title=item.parent_title,
                    imdb_id=item.imdb_id,
                    tmdb_id=item.tmdb_id,
                    provider=item.provider,
                    provider_label=item.provider_label,
                    subtitles_count=1,
                    match_score=item.match_score,
                )
            else:
                match_id = mapped_match_id
                group = groups[match_id]
                group["subtitles_count"] = int(group["subtitles_count"]) + 1
                group["match_score"] = max(float(group["match_score"]), item.match_score)
                group["providers"].add(item.provider)
                group["provider_labels"].add(item.provider_label)
            aggregated_results.append(
                AggregatedSubtitleResult(
                    result_id=f"result-{index}",
                    match_id=match_id,
                    provider=item.provider,
                    provider_label=item.provider_label,
                    title=item.title,
                    year=item.year,
                    imdb_id=item.imdb_id,
                    tmdb_id=item.tmdb_id,
                    media_type=item.media_type,
                    season=item.season,
                    episode=item.episode,
                    parent_title=item.parent_title,
                    language=item.language,
                    download_count=item.download_count,
                    file_name=item.file_name,
                    match_score=item.match_score,
                    provider_rank=PROVIDER_RANK.get(item.provider, 99),
                    provider_result=item,
                )
            )

        # ASSRT sometimes omits year/episode metadata; merge those "orphans" back
        # into a stronger title group when the normalized title already exists.
        assrt_orphans = [
            item
            for item in aggregated_results
            if item.provider == "assrt" and item.year is None and item.season is None and item.episode is None
        ]
        for item in assrt_orphans:
            current_group_id = item.match_id
            orphan_title_key = match_group_key(
                item.title,
                item.media_type,
                item.year,
                item.season,
                item.episode,
                item.parent_title,
            )[0]
            candidate_group_ids = [
                group_id
                for key, group_id in group_order.items()
                if group_id != current_group_id and key[0] == orphan_title_key
            ]
            if not candidate_group_ids:
                continue
            winning_group_id = max(candidate_group_ids, key=lambda group_id: float(groups[group_id]["match_score"]))
            source_group = groups.get(current_group_id)
            winning_group = groups[winning_group_id]
            item.match_id = winning_group_id
            winning_group["subtitles_count"] = int(winning_group["subtitles_count"]) + 1
            winning_group["match_score"] = max(float(winning_group["match_score"]), item.match_score)
            winning_group["providers"].add(item.provider)
            winning_group["provider_labels"].add(item.provider_label)
            if source_group is not None:
                source_group["subtitles_count"] = max(0, int(source_group["subtitles_count"]) - 1)

        referenced_group_ids = {item.match_id for item in aggregated_results}
        provider_match_group_ids = set(provider_match_map.values())
        # Series/tvshow groups can be referenced only by their match (no direct
        # files). Keep those so the title list still surfaces the series row.
        empty_group_ids = set(groups) - referenced_group_ids - provider_match_group_ids

        # Keep a snapshot of every group (including empties) so the work-level
        # builder can still see series-level matches that carry IMDb IDs even
        # if they have no direct subtitle files of their own.
        works_groups_snapshot = {gid: dict(g) for gid, g in groups.items()}
        works_group_order_snapshot = list(group_order.items())

        for group_id in empty_group_ids:
            groups.pop(group_id, None)
        for key, group_id in list(group_order.items()):
            if group_id in empty_group_ids:
                group_order.pop(key, None)

        parent_series_keys: set[tuple[str, int]] = set()
        if not query_requests_episode:
            episode_parent_keys: set[tuple[str, int]] = set()
            for group in groups.values():
                if str(group["media_type"]) == "episode" and group["parent_title"]:
                    year_value = group["year"] if isinstance(group["year"], int) else 0
                    episode_parent_keys.add((canonical_title(str(group["parent_title"])), year_value))
            for group in groups.values():
                media_type = str(group["media_type"])
                if media_type in {"series", "tvshow"}:
                    year_value = group["year"] if isinstance(group["year"], int) else 0
                    group_key = (canonical_title(str(group["title"])), year_value)
                    if group_key in episode_parent_keys:
                        parent_series_keys.add(group_key)

        matches: list[AggregatedTitleMatch] = []
        for group_id, group in groups.items():
            year_value = group["year"] if isinstance(group["year"], int) else None
            adjusted_score = float(group["match_score"]) + self._year_bonus(year_value, query_year)
            media_type = str(group["media_type"])
            if not query_requests_episode:
                if media_type in {"series", "tvshow"}:
                    adjusted_score += BARE_TITLE_SERIES_BONUS
                elif media_type == "episode":
                    adjusted_score -= BARE_TITLE_EPISODE_PENALTY
            if parent_series_keys:
                series_key_year = year_value or 0
                if media_type in {"series", "tvshow"}:
                    if (canonical_title(str(group["title"])), series_key_year) in parent_series_keys:
                        adjusted_score += PARENT_SERIES_BONUS
                elif media_type == "episode" and group["parent_title"]:
                    episode_parent_key = (canonical_title(str(group["parent_title"])), series_key_year)
                    if episode_parent_key in parent_series_keys:
                        adjusted_score -= IMPLICIT_EPISODE_PENALTY
            matches.append(
                AggregatedTitleMatch(
                    id=group_id,
                    title=str(group["title"]),
                    year=year_value,
                    imdb_id=str(group["imdb_id"]) if group["imdb_id"] else None,
                    tmdb_id=str(group["tmdb_id"]) if group["tmdb_id"] else None,
                    media_type=media_type,
                    season=group["season"] if isinstance(group["season"], int) else None,
                    episode=group["episode"] if isinstance(group["episode"], int) else None,
                    parent_title=str(group["parent_title"]) if group["parent_title"] else None,
                    subtitles_count=int(group["subtitles_count"]),
                    match_score=adjusted_score,
                    provider_count=len(group["providers"]),
                    providers=tuple(sorted(group["providers"])),
                    provider_labels=tuple(sorted(group["provider_labels"])),
                )
            )
        matches.sort(key=lambda item: (item.match_score, item.provider_count, item.subtitles_count), reverse=True)

        group_scores = {item.id: item.match_score for item in matches}
        aggregated_results.sort(
            key=lambda item: (
                group_scores.get(item.match_id, 0.0),
                -language_priority(item.language, requested_languages),
                -item.match_score,
                -item.download_count,
                -item.provider_rank,
            ),
            reverse=True,
        )
        aggregated_results = [replace(item, result_id=f"result-{index}") for index, item in enumerate(aggregated_results, start=1)]

        full_matches_for_works = [
            AggregatedTitleMatch(
                id=group_id,
                title=str(group["title"]),
                year=group["year"] if isinstance(group["year"], int) else None,
                imdb_id=str(group["imdb_id"]) if group["imdb_id"] else None,
                tmdb_id=str(group["tmdb_id"]) if group["tmdb_id"] else None,
                media_type=str(group["media_type"]),
                season=group["season"] if isinstance(group["season"], int) else None,
                episode=group["episode"] if isinstance(group["episode"], int) else None,
                parent_title=str(group["parent_title"]) if group["parent_title"] else None,
                subtitles_count=int(group["subtitles_count"]),
                match_score=float(group["match_score"]),
                provider_count=len(group["providers"]),
                providers=tuple(sorted(group["providers"])),
                provider_labels=tuple(sorted(group["provider_labels"])),
            )
            for _, group_id in works_group_order_snapshot
            for group in [works_groups_snapshot[group_id]]
        ]

        works = self._sort_works(self._build_works(full_matches_for_works, aggregated_results), query, query_year)
        return AggregatedSearchCatalog(matches=matches, results=aggregated_results, works=works)

    def _build_works(
        self,
        matches: list[AggregatedTitleMatch],
        results: list[AggregatedSubtitleResult],
    ) -> list[AggregatedWork]:
        """Collapse title matches into top-level works (movies or series)."""
        if not matches:
            return []

        results_by_match: dict[str, list[AggregatedSubtitleResult]] = {}
        for result in results:
            results_by_match.setdefault(result.match_id, []).append(result)

        normalized = [_normalize_match_for_work(match) for match in matches]

        buckets: dict[tuple[str, str], list[AggregatedTitleMatch]] = {}
        bucket_order: list[tuple[str, str]] = []
        for match in normalized:
            key = work_key(
                title=match.title,
                media_type=match.media_type,
                year=match.year,
                parent_title=match.parent_title,
                imdb_id=match.imdb_id,
            )
            if key not in buckets:
                buckets[key] = []
                bucket_order.append(key)
            buckets[key].append(match)

        works: list[AggregatedWork] = []
        for index, key in enumerate(bucket_order, start=1):
            members = buckets[key]
            category = key[0]
            work = (
                self._build_series_work(members, results_by_match, f"work-{index}")
                if category == "series"
                else self._build_movie_work(members, results_by_match, f"work-{index}")
            )
            works.append(work)

        works.sort(
            key=lambda w: (
                1 if w.imdb_id else 0,
                len(w.providers),
                w.match_score,
                w.total_subtitles,
            ),
            reverse=True,
        )
        return works

    def _sort_works(
        self,
        works: list[AggregatedWork],
        query: str,
        query_year: int | None = None,
    ) -> list[AggregatedWork]:
        """Rank top-level work cards by user query fit after all enrichment."""
        if not works:
            return works
        query_key = canonical_title(query)
        exact_series_exists = bool(
            query_key
            and any(w.media_type == "series" and canonical_title(w.title) == query_key for w in works)
        )

        def relation_rank(work: AggregatedWork, title_key: str) -> int:
            if not query_key:
                return 0
            if not title_key:
                return 0
            if title_key == query_key:
                if work.media_type == "movie" and query_year is not None and work.year == query_year:
                    return WORK_RANK_EXACT_MOVIE_YEAR
                if work.media_type == "series":
                    return WORK_RANK_EXACT_SERIES
                return WORK_RANK_EXACT_MOVIE_WITH_SERIES if exact_series_exists else WORK_RANK_EXACT_MOVIE
            if title_key.startswith(f"{query_key} "):
                return WORK_RANK_PREFIX
            if query_key in title_key:
                return WORK_RANK_CONTAINS
            return 0

        def sort_key(work: AggregatedWork) -> tuple[float, ...]:
            title_key = canonical_title(work.title)
            relation = relation_rank(work, title_key)
            similarity = title_similarity(query, [work.title]) if relation == 0 else 0.0
            year_rank = _work_year_rank(work, query_year) if relation > 0 else 0
            return (
                relation,
                year_rank,
                similarity,
                work.total_subtitles,
                1 if work.media_type == "series" and work.total_episodes > 0 else 0,
                1 if work.imdb_id or work.tmdb_id else 0,
                len(work.providers),
                work.total_episodes,
                work.match_score,
            )

        return sorted(
            works,
            key=sort_key,
            reverse=True,
        )

    async def _merge_works_via_tmdb(
        self,
        works: list[AggregatedWork],
        dispatch_query: str,
        correlation_id: str | None = None,
    ) -> list[AggregatedWork]:
        """Enrich each series work with TMDb identity and fold duplicates.

        Lookups run concurrently; failures fall through silently so the UI
        keeps the un-merged list instead of dying on a TMDb outage.
        """
        if self._tmdb_client is None or not self._tmdb_client.enabled:
            return works

        series_indices = [i for i, w in enumerate(works) if w.media_type == "series"]
        if not series_indices:
            return works

        started = time.perf_counter()
        lookups = [self._lookup_series_identity(works[i], dispatch_query) for i in series_indices]
        identities = await asyncio.gather(*lookups, return_exceptions=True)

        enriched: list[AggregatedWork] = list(works)
        for idx, identity in zip(series_indices, identities, strict=False):
            if isinstance(identity, Exception) or identity is None:
                continue
            series = identity
            work = enriched[idx]
            enriched[idx] = replace(
                work,
                imdb_id=work.imdb_id or series.imdb_id,
                tmdb_id=work.tmdb_id or str(series.tmdb_id),
                poster_url=work.poster_url or poster_url_from_path(series.poster_path),
            )

        # Flush cache in the background so the next search benefits.
        self._tmdb_client.cache.flush()
        log_event(
            "tmdb.identity.done",
            layer="backend",
            correlation_id=correlation_id,
            duration_ms=round((time.perf_counter() - started) * 1000),
            series=len(series_indices),
            hits=sum(1 for identity in identities if not isinstance(identity, Exception) and identity is not None),
            errors=sum(1 for identity in identities if isinstance(identity, Exception)),
        )

        # Group by tmdb_id; fold duplicates into the best primary.
        by_tmdb: dict[str, list[int]] = {}
        for i, work in enumerate(enriched):
            if work.media_type != "series" or not work.tmdb_id:
                continue
            by_tmdb.setdefault(work.tmdb_id, []).append(i)

        if not any(len(group) > 1 for group in by_tmdb.values()):
            return enriched

        merged_indices: set[int] = set()
        result: list[AggregatedWork] = []
        for i, work in enumerate(enriched):
            if i in merged_indices:
                continue
            if work.media_type == "series" and work.tmdb_id and len(by_tmdb.get(work.tmdb_id, [])) > 1:
                group_indices = by_tmdb[work.tmdb_id]
                primary_idx = max(
                    group_indices,
                    key=lambda j: (
                        1 if enriched[j].imdb_id else 0,
                        len(enriched[j].providers),
                        enriched[j].total_subtitles,
                        enriched[j].match_score,
                    ),
                )
                if i != primary_idx:
                    # Secondary — handled when we reach the primary.
                    continue
                partners = [enriched[j] for j in group_indices if j != primary_idx]
                merged_indices.update(j for j in group_indices if j != primary_idx)
                result.append(_fold_series_works(enriched[primary_idx], partners))
            else:
                result.append(work)
        return result

    async def _apply_tmdb_season_skeleton(
        self,
        works: list[AggregatedWork],
        correlation_id: str | None = None,
    ) -> list[AggregatedWork]:
        """Fetch full episode catalog from TMDb and scaffold skeleton seasons."""
        if self._tmdb_client is None or not self._tmdb_client.enabled:
            return works

        started = time.perf_counter()

        async def enrich(work: AggregatedWork) -> AggregatedWork:
            if work.media_type != "series" or not work.tmdb_id:
                return work
            try:
                tmdb_id = int(work.tmdb_id)
            except (ValueError, TypeError):
                return work
            details = await self._tmdb_client.fetch_series_details(tmdb_id)
            if not details or not isinstance(details.get("number_of_seasons"), int):
                return work
            n_seasons: int = details["number_of_seasons"]
            if n_seasons < 1:
                return work
            season_results = await asyncio.gather(
                *[self._tmdb_client.fetch_season(tmdb_id, s) for s in range(1, n_seasons + 1)],
                return_exceptions=True,
            )
            catalog = [
                (s, eps if isinstance(eps, list) else [])
                for s, eps in zip(range(1, n_seasons + 1), season_results)
            ]
            new_seasons = build_season_skeleton(catalog, work.seasons)
            total_ep = sum(
                1 for season in new_seasons
                for ep in season.episodes
                if ep.episode is not None
            )
            ep_chip = WorkChip(kind="episodes", label=f"{total_ep} eps")
            other_chips = [c for c in work.info_chips if c.kind != "episodes"]
            return replace(
                work,
                seasons=new_seasons,
                total_episodes=total_ep,
                info_chips=[*other_chips, ep_chip],
                poster_url=work.poster_url or poster_url_from_path(
                    details.get("poster_path") if isinstance(details.get("poster_path"), str) else None
                ),
            )

        results = await asyncio.gather(*[enrich(w) for w in works], return_exceptions=True)
        log_event(
            "tmdb.season_skeleton.done",
            layer="backend",
            correlation_id=correlation_id,
            duration_ms=round((time.perf_counter() - started) * 1000),
            works=len(works),
            enriched=sum(1 for result in results if not isinstance(result, Exception)),
            errors=sum(1 for result in results if isinstance(result, Exception)),
        )
        return [
            r if not isinstance(r, Exception) else works[i]
            for i, r in enumerate(results)
        ]

    async def _apply_tmdb_posters(
        self,
        works: list[AggregatedWork],
        correlation_id: str | None = None,
    ) -> list[AggregatedWork]:
        if self._tmdb_client is None or not self._tmdb_client.enabled:
            return works

        started = time.perf_counter()

        async def enrich(work: AggregatedWork) -> AggregatedWork:
            if work.poster_url or not work.tmdb_id:
                return work
            try:
                tmdb_id = int(work.tmdb_id)
            except (ValueError, TypeError):
                return work
            poster_url = await self._tmdb_client.fetch_poster_url(tmdb_id, work.media_type)
            if not poster_url:
                return work
            return replace(work, poster_url=poster_url)

        results = await asyncio.gather(*[enrich(w) for w in works], return_exceptions=True)
        log_event(
            "tmdb.posters.done",
            layer="backend",
            correlation_id=correlation_id,
            duration_ms=round((time.perf_counter() - started) * 1000),
            works=len(works),
            enriched=sum(1 for result in results if not isinstance(result, Exception)),
            errors=sum(1 for result in results if isinstance(result, Exception)),
        )
        return [
            r if not isinstance(r, Exception) else works[i]
            for i, r in enumerate(results)
        ]

    async def _lookup_series_identity(
        self,
        work: AggregatedWork,
        dispatch_query: str,
    ) -> TMDbSeries | None:
        if self._tmdb_client is None:
            return None
        if work.tmdb_id and work.imdb_id:
            return None  # Already identified; nothing new to learn.
        if work.imdb_id:
            hit = await self._tmdb_client.find_by_imdb(work.imdb_id)
            if hit:
                return hit
        candidates: list[str] = []
        if work.title:
            candidates.append(work.title)
        if dispatch_query and dispatch_query.lower() != work.title.lower():
            candidates.append(dispatch_query)
        for query in candidates:
            hit = await self._tmdb_client.search_tv(query, year_hint=work.year)
            if hit:
                return hit
        return None

    def _build_movie_work(
        self,
        members: list[AggregatedTitleMatch],
        results_by_match: dict[str, list[AggregatedSubtitleResult]],
        work_id: str,
    ) -> AggregatedWork:
        primary = max(members, key=lambda m: (m.match_score, m.subtitles_count))
        providers, provider_labels = _collect_providers(members)
        total_subtitles = sum(m.subtitles_count for m in members)
        top_downloads = _top_download_count(members, results_by_match)
        imdb_id = next((m.imdb_id for m in members if m.imdb_id), None)
        tmdb_id = next((m.tmdb_id for m in members if m.tmdb_id), None)
        match_score = max(m.match_score for m in members)

        chips: list[WorkChip] = []
        chips.extend(_provider_chips(providers))
        if imdb_id:
            chips.append(WorkChip(kind="imdb", label="IMDb ✓", tone="verified"))
        if top_downloads:
            chips.append(WorkChip(kind="downloads", label=_humanize_downloads(top_downloads)))

        return AggregatedWork(
            id=work_id,
            title=primary.title,
            media_type="movie",
            year=primary.year,
            year_end=None,
            imdb_id=imdb_id,
            tmdb_id=tmdb_id,
            providers=providers,
            provider_labels=provider_labels,
            seasons=[],
            total_episodes=0,
            total_subtitles=total_subtitles,
            match_score=match_score,
            primary_match_id=primary.id,
            info_chips=chips,
        )

    def _build_series_work(
        self,
        members: list[AggregatedTitleMatch],
        results_by_match: dict[str, list[AggregatedSubtitleResult]],
        work_id: str,
    ) -> AggregatedWork:
        series_candidates = [m for m in members if m.media_type in {"series", "tvshow"}]
        episode_candidates = [m for m in members if m.media_type == "episode"]
        other_candidates = [m for m in members if m not in series_candidates and m not in episode_candidates]

        title_source = series_candidates or episode_candidates or other_candidates
        head = max(title_source, key=lambda m: (m.match_score, m.subtitles_count))
        display_title = head.parent_title if head.media_type == "episode" and head.parent_title else head.title

        providers, provider_labels = _collect_providers(members)
        imdb_id = next((m.imdb_id for m in series_candidates if m.imdb_id), None)
        tmdb_id = next((m.tmdb_id for m in series_candidates if m.tmdb_id), None)

        years = [m.year for m in members if m.year]
        year_lo = min(years) if years else None
        year_hi = max(years) if years else None

        primary_match: AggregatedTitleMatch | None = None
        if series_candidates:
            primary_match = max(series_candidates, key=lambda m: (m.match_score, m.subtitles_count))
        elif not episode_candidates and other_candidates:
            primary_match = max(other_candidates, key=lambda m: (m.match_score, m.subtitles_count))

        seasons_map: dict[int, AggregatedSeason] = {}
        episode_keys: set[tuple[int, int]] = set()
        for match in episode_candidates:
            season_no = match.season or 0
            episode_no = match.episode or 0
            season = seasons_map.get(season_no)
            if season is None:
                season = AggregatedSeason(season_number=season_no, episodes=[], subtitles_count=0)
                seasons_map[season_no] = season
            ep_title = match.title if match.title and match.title != match.parent_title else ""
            season.episodes.append(
                AggregatedEpisode(
                    season=match.season,
                    episode=match.episode,
                    title=ep_title,
                    match_id=match.id,
                    year=match.year,
                    subtitles_count=match.subtitles_count,
                    providers=match.providers,
                )
            )
            season.subtitles_count += match.subtitles_count
            if match.season is not None and match.episode is not None:
                episode_keys.add((match.season, match.episode))

        for season in seasons_map.values():
            season.episodes.sort(key=lambda ep: (ep.episode or 0, ep.match_id))

        seasons = [seasons_map[num] for num in sorted(seasons_map.keys())]
        total_subtitles = sum(m.subtitles_count for m in members)
        top_downloads = _top_download_count(members, results_by_match)
        match_score = max(m.match_score for m in members)

        chips: list[WorkChip] = []
        chips.extend(_provider_chips(providers))
        if imdb_id:
            chips.append(WorkChip(kind="imdb", label="IMDb ✓", tone="verified"))
        if episode_keys:
            chips.append(WorkChip(kind="episodes", label=f"{len(episode_keys)} eps"))
        if top_downloads:
            chips.append(WorkChip(kind="downloads", label=_humanize_downloads(top_downloads)))

        return AggregatedWork(
            id=work_id,
            title=display_title,
            media_type="series",
            year=year_lo,
            year_end=year_hi,
            imdb_id=imdb_id,
            tmdb_id=tmdb_id,
            providers=providers,
            provider_labels=provider_labels,
            seasons=seasons,
            total_episodes=len(episode_keys),
            total_subtitles=total_subtitles,
            match_score=match_score,
            primary_match_id=primary_match.id if primary_match else None,
            info_chips=chips,
        )


def _fold_series_works(
    primary: AggregatedWork,
    partners: list[AggregatedWork],
) -> AggregatedWork:
    """Combine a primary series work with TMDb-linked partner works."""
    if not partners:
        return primary

    all_works = [primary, *partners]

    provider_set: set[str] = set()
    label_set: set[str] = set()
    for work in all_works:
        provider_set.update(work.providers)
        label_set.update(work.provider_labels)
    providers = tuple(sorted(provider_set, key=lambda code: (-PROVIDER_RANK.get(code, -1), code)))
    provider_labels = tuple(sorted(label_set))

    seasons_map: dict[int, AggregatedSeason] = {}
    seen_episode_ids: set[str] = set()
    episode_keys: set[tuple[int, int]] = set()
    for work in all_works:
        for season in work.seasons:
            merged = seasons_map.setdefault(
                season.season_number,
                AggregatedSeason(
                    season_number=season.season_number, episodes=[], subtitles_count=0
                ),
            )
            merged.subtitles_count += season.subtitles_count
            for episode in season.episodes:
                if episode.match_id in seen_episode_ids:
                    continue
                seen_episode_ids.add(episode.match_id)
                merged.episodes.append(episode)
                if episode.season is not None and episode.episode is not None:
                    episode_keys.add((episode.season, episode.episode))

    for season in seasons_map.values():
        season.episodes.sort(key=lambda ep: (ep.episode or 0, ep.match_id))
    seasons = [seasons_map[num] for num in sorted(seasons_map.keys())]

    total_subtitles = sum(w.total_subtitles for w in all_works)
    total_episodes = len(episode_keys) or sum(w.total_episodes for w in all_works)
    match_score = max(w.match_score for w in all_works)

    years = [w.year for w in all_works if w.year]
    year_lo = min(years) if years else primary.year
    year_hi = max([w.year_end or w.year for w in all_works if w.year_end or w.year], default=primary.year_end)

    imdb_id = primary.imdb_id or next((w.imdb_id for w in partners if w.imdb_id), None)
    tmdb_id = primary.tmdb_id or next((w.tmdb_id for w in partners if w.tmdb_id), None)

    # Prefer a partner title that is not Latin-only if the primary is CJK, or vice versa.
    # Heuristic: TMDb `name` already covers localization; partner titles can be shown as aliases.
    title = primary.title

    # Union info chips; re-emit provider chips from the merged provider set.
    remaining_chip_keys: set[tuple[str, str]] = set()
    chips: list[WorkChip] = []
    chips.extend(_provider_chips(providers))
    for key in (("provider", chip.label) for chip in chips):
        remaining_chip_keys.add(key)
    if imdb_id:
        chip = WorkChip(kind="imdb", label="IMDb ✓", tone="verified")
        if (chip.kind, chip.label) not in remaining_chip_keys:
            chips.append(chip)
            remaining_chip_keys.add((chip.kind, chip.label))
    if episode_keys:
        chip = WorkChip(kind="episodes", label=f"{len(episode_keys)} eps")
        chips.append(chip)
    # Carry over any non-duplicated tone-rich chip (e.g. downloads) from members.
    for work in all_works:
        for chip in work.info_chips:
            if chip.kind in {"provider", "imdb", "episodes"}:
                continue
            if (chip.kind, chip.label) in remaining_chip_keys:
                continue
            chips.append(chip)
            remaining_chip_keys.add((chip.kind, chip.label))

    primary_match_id = primary.primary_match_id or next(
        (w.primary_match_id for w in partners if w.primary_match_id), None
    )

    return replace(
        primary,
        title=title,
        year=year_lo,
        year_end=year_hi,
        imdb_id=imdb_id,
        tmdb_id=tmdb_id,
        providers=providers,
        provider_labels=provider_labels,
        seasons=seasons,
        total_episodes=total_episodes,
        total_subtitles=total_subtitles,
        match_score=match_score,
        primary_match_id=primary_match_id,
        info_chips=chips,
        poster_url=primary.poster_url or next((w.poster_url for w in partners if w.poster_url), None),
    )


def _normalize_match_for_work(match: AggregatedTitleMatch) -> AggregatedTitleMatch:
    """Detect hidden season markers ('II', 'S4', '第2期') and reclassify.

    Many providers report each season of a series as a standalone `movie`
    (SubDL tags 'Overlord II' as movie; ASSRT tags 'OVERLORD S4' as movie).
    Without this promotion the work-level grouping splits one series into
    many scattered cards.
    """
    if match.media_type == "episode":
        return match
    base_title, season_hint = extract_season_suffix(match.title)
    if season_hint is None:
        return match
    parent_title = match.parent_title or base_title
    return replace(
        match,
        media_type="episode",
        season=match.season or season_hint,
        episode=match.episode,
        parent_title=parent_title,
    )


def _collect_providers(
    members: Iterable[AggregatedTitleMatch],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    provider_set: set[str] = set()
    label_set: set[str] = set()
    for match in members:
        provider_set.update(match.providers)
        label_set.update(match.provider_labels)
    providers = tuple(sorted(provider_set, key=lambda code: (-PROVIDER_RANK.get(code, -1), code)))
    labels = tuple(sorted(label_set))
    return providers, labels


def _episode_coverage_summary(works: list[AggregatedWork], limit: int = 5) -> list[dict[str, object]]:
    summary: list[dict[str, object]] = []
    for work in works:
        if work.media_type != "series" or not work.seasons:
            continue
        exact_episodes = 0
        skeleton_episodes = 0
        season_packs = 0
        for season in work.seasons:
            for episode in season.episodes:
                if episode.episode is None:
                    season_packs += 1
                elif episode.match_id.startswith("skeleton:"):
                    skeleton_episodes += 1
                else:
                    exact_episodes += 1
        summary.append(
            {
                "work_id": work.id,
                "title": work.title,
                "exact_episodes": exact_episodes,
                "skeleton_episodes": skeleton_episodes,
                "season_packs": season_packs,
            }
        )
        if len(summary) >= limit:
            break
    return summary


def _top_download_count(
    members: Iterable[AggregatedTitleMatch],
    results_by_match: dict[str, list[AggregatedSubtitleResult]],
) -> int:
    best = 0
    for match in members:
        for result in results_by_match.get(match.id, ()):
            if result.download_count > best:
                best = result.download_count
    return best


def _provider_chips(providers: tuple[str, ...]) -> list[WorkChip]:
    chips: list[WorkChip] = []
    for code in providers:
        label = PROVIDER_CHIP_LABELS.get(code, code)
        chips.append(WorkChip(kind="provider", label=label, tone="accent"))
    return chips


def _humanize_downloads(count: int) -> str:
    if count >= 1_000_000:
        value = count / 1_000_000
        return f"{value:.1f}M DL".replace(".0M", "M")
    if count >= 1_000:
        value = count / 1_000
        return f"{value:.1f}k DL".replace(".0k", "k")
    return f"{count} DL"


def _rewrite_query_alias(query: str) -> str:
    return QUERY_ALIASES.get(canonical_title(query), query)


def _is_generic_tmdb_query(query: str) -> bool:
    query_tokens = canonical_title(query).split()
    if len(query_tokens) != 1:
        return False
    token = query_tokens[0]
    return token.isascii() and token.isalnum() and len(token) <= 4


def _work_year_rank(work: AggregatedWork, query_year: int | None) -> int:
    if query_year is None:
        return 0
    if work.year == query_year:
        return WORK_YEAR_EXACT_MOVIE if work.media_type == "movie" else WORK_YEAR_EXACT_START
    if work.year and work.year_end and work.year <= query_year <= work.year_end:
        return WORK_YEAR_IN_RANGE
    if work.year:
        diff = abs(work.year - query_year)
        if diff <= YEAR_NEAR_RANGE:
            return WORK_YEAR_NEAR_BASE - diff
    return 0
