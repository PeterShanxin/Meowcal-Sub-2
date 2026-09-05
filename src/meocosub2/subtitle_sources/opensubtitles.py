"""OpenSubtitles provider wrapper."""

from __future__ import annotations

from pathlib import Path

from meocosub2.config import AppConfig
from meocosub2.opensubtitles.client import OpenSubtitlesClient
from meocosub2.subtitle_sources.types import (
    ProviderCapabilities,
    ProviderSearchCatalog,
    ProviderSubtitleMatch,
    ProviderSubtitleResult,
)


class OpenSubtitlesProvider:
    provider_code = "opensubtitles"
    provider_label = "OpenSubtitles"
    capabilities = ProviderCapabilities(search=True, download=True, requires_auth=True)

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    @property
    def enabled(self) -> bool:
        return self.config.opensubtitles_enabled

    async def search_catalog(self, query: str, languages: str) -> ProviderSearchCatalog:
        if not self.config.opensubtitles_enabled:
            return ProviderSearchCatalog(matches=[], results=[], warnings=["OpenSubtitles is disabled."])
        if not self.config.opensubtitles_api_key:
            return ProviderSearchCatalog(matches=[], results=[], warnings=["OpenSubtitles API key is not configured."])

        async with OpenSubtitlesClient(
            api_key=self.config.opensubtitles_api_key,
            enable_org_fallback=self.config.opensubtitles_enable_org_fallback,
        ) as client:
            catalog = await client.search_catalog(query, languages=languages)

        matches = [
            ProviderSubtitleMatch(
                id=f"os-match-{item.id}",
                provider=self.provider_code,
                provider_label=self.provider_label,
                title=item.title,
                year=item.year,
                imdb_id=item.parent_imdb_id or item.imdb_id,
                tmdb_id=item.parent_tmdb_id or item.tmdb_id,
                media_type=item.media_type,
                season=item.season,
                episode=item.episode,
                parent_title=item.parent_title,
                subtitles_count=item.subtitles_count,
                match_score=item.match_score,
            )
            for item in catalog.matches
        ]
        results = [
            ProviderSubtitleResult(
                id=f"os-result-{item.file_id}",
                match_id=f"os-match-{item.parent_feature_id or item.feature_id or item.id}",
                provider=self.provider_code,
                provider_label=self.provider_label,
                title=item.title,
                year=item.year,
                imdb_id=item.parent_imdb_id or item.imdb_id,
                tmdb_id=item.parent_tmdb_id or item.tmdb_id,
                media_type=item.media_type,
                season=item.season,
                episode=item.episode,
                parent_title=item.parent_title,
                language=item.language,
                download_count=item.download_count,
                file_name=item.file_name,
                match_score=item.match_score,
                download_ref=str(item.file_id),
                raw={
                    "file_id": item.file_id,
                    "feature_id": item.feature_id,
                    "parent_feature_id": item.parent_feature_id,
                    "episode_imdb_id": item.imdb_id,
                    "episode_tmdb_id": item.tmdb_id,
                },
            )
            for item in catalog.results
        ]
        return ProviderSearchCatalog(matches=matches, results=results)

    async def download(self, result: ProviderSubtitleResult) -> Path:
        file_id = int(result.raw.get("file_id") or result.download_ref or "0")
        async with OpenSubtitlesClient(api_key=self.config.opensubtitles_api_key) as client:
            return await client.download(file_id, result.file_name)
