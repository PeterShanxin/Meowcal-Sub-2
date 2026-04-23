"""Subtitle source aggregation and result ranking."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from meocosub2.config import AppConfig
from meocosub2.errors import SubtitleSourceError
from meocosub2.subtitle_sources.assrt import AssrtProvider
from meocosub2.subtitle_sources.opensubtitles import OpenSubtitlesProvider
from meocosub2.subtitle_sources.subdl import SubdlProvider
from meocosub2.subtitle_sources.types import (
    AggregatedSearchCatalog,
    AggregatedSubtitleResult,
    AggregatedTitleMatch,
    ProviderSearchCatalog,
    ProviderSubtitleMatch,
    ProviderSubtitleResult,
    SubtitleSourceProvider,
)
from meocosub2.subtitle_sources.utils import (
    EPISODE_PATTERN,
    PROVIDER_RANK,
    canonical_title,
    language_priority,
    match_group_key,
    split_query_year,
)


YEAR_EXACT_BONUS = 20.0
YEAR_NEAR_PENALTY = 4.0
YEAR_MISMATCH_PENALTY = 15.0
YEAR_NEAR_RANGE = 3
BARE_TITLE_SERIES_BONUS = 24.0
BARE_TITLE_EPISODE_PENALTY = 24.0
PARENT_SERIES_BONUS = 50.0
IMPLICIT_EPISODE_PENALTY = 80.0


class SubtitleSearchAggregator:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.providers: tuple[SubtitleSourceProvider, ...] = (
            SubdlProvider(config),
            AssrtProvider(config),
            OpenSubtitlesProvider(config),
        )

    async def search_catalog(self, query: str, languages: str) -> AggregatedSearchCatalog:
        clean_title, query_year = split_query_year(query)
        dispatch_query = clean_title or query
        responses = await asyncio.gather(
            *(provider.search_catalog(dispatch_query, languages) for provider in self.providers),
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

        aggregated = self._merge_catalogs(catalogs, languages, query_year, dispatch_query)
        aggregated.warnings.extend(warnings)
        if not aggregated.results and errors:
            raise SubtitleSourceError("; ".join(errors))
        aggregated.warnings.extend(errors)
        return aggregated

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
            match_id = provider_match_map.get(item.match_id)
            if match_id is None:
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
        empty_group_ids = set(groups) - referenced_group_ids
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
        return AggregatedSearchCatalog(matches=matches, results=aggregated_results)
