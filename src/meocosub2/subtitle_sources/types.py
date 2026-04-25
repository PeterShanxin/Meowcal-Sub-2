"""Provider-neutral subtitle source models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ProviderCapabilities:
    search: bool = True
    download: bool = True
    requires_auth: bool = False


@dataclass
class ProviderSubtitleMatch:
    id: str
    provider: str
    provider_label: str
    title: str
    year: int | None
    imdb_id: str | None
    tmdb_id: str | None
    media_type: str
    season: int | None = None
    episode: int | None = None
    parent_title: str | None = None
    subtitles_count: int = 0
    match_score: float = 0.0

    def display_label(self) -> str:
        year_suffix = f" ({self.year})" if self.year else ""
        if self.media_type == "episode" and self.season and self.episode:
            if self.parent_title and self.title:
                return f"{self.parent_title} S{self.season:02d}E{self.episode:02d} - {self.title}{year_suffix}"
            series_title = self.parent_title or self.title
            return f"{series_title} S{self.season:02d}E{self.episode:02d}{year_suffix}"
        return f"{self.title}{year_suffix}"


@dataclass
class ProviderSubtitleResult:
    id: str
    match_id: str
    provider: str
    provider_label: str
    title: str
    year: int | None
    imdb_id: str | None
    media_type: str
    language: str
    download_count: int
    file_name: str
    season: int | None = None
    episode: int | None = None
    parent_title: str | None = None
    tmdb_id: str | None = None
    match_score: float = 0.0
    download_ref: str | None = None
    raw: dict[str, object] = field(default_factory=dict, repr=False)

    def display_label(self) -> str:
        year_suffix = f" ({self.year})" if self.year else ""
        if self.media_type == "episode" and self.season and self.episode:
            if self.parent_title and self.title:
                return (
                    f"{self.parent_title} "
                    f"S{self.season:02d}E{self.episode:02d} - {self.title}{year_suffix} [{self.language}]"
                )
            series_title = self.parent_title or self.title
            return f"{series_title} S{self.season:02d}E{self.episode:02d}{year_suffix} [{self.language}]"
        return f"{self.title}{year_suffix} [{self.language}]"


@dataclass
class ProviderSearchCatalog:
    matches: list[ProviderSubtitleMatch]
    results: list[ProviderSubtitleResult]
    warnings: list[str] = field(default_factory=list)


@dataclass
class AggregatedTitleMatch:
    id: str
    title: str
    year: int | None
    imdb_id: str | None
    tmdb_id: str | None
    media_type: str
    season: int | None = None
    episode: int | None = None
    parent_title: str | None = None
    subtitles_count: int = 0
    match_score: float = 0.0
    provider_count: int = 0
    providers: tuple[str, ...] = ()
    provider_labels: tuple[str, ...] = ()

    def display_label(self) -> str:
        year_suffix = f" ({self.year})" if self.year else ""
        if self.media_type == "episode" and self.season and self.episode:
            if self.parent_title and self.title:
                return f"{self.parent_title} S{self.season:02d}E{self.episode:02d} - {self.title}{year_suffix}"
            series_title = self.parent_title or self.title
            return f"{series_title} S{self.season:02d}E{self.episode:02d}{year_suffix}"
        return f"{self.title}{year_suffix}"


@dataclass
class AggregatedSubtitleResult:
    result_id: str
    match_id: str
    provider: str
    provider_label: str
    title: str
    year: int | None
    imdb_id: str | None
    media_type: str
    language: str
    download_count: int
    file_name: str
    season: int | None = None
    episode: int | None = None
    parent_title: str | None = None
    tmdb_id: str | None = None
    match_score: float = 0.0
    provider_rank: int = 99
    provider_result: ProviderSubtitleResult = field(repr=False, compare=False, default=None)  # type: ignore[assignment]

    def display_label(self) -> str:
        return self.provider_result.display_label()


@dataclass(frozen=True)
class WorkChip:
    """A single info chip shown on a work card."""

    kind: str  # "provider" | "imdb" | "episodes" | "downloads"
    label: str
    tone: str = "neutral"  # "neutral" | "accent" | "verified"


@dataclass
class AggregatedEpisode:
    season: int | None
    episode: int | None
    title: str
    match_id: str
    year: int | None = None
    subtitles_count: int = 0
    providers: tuple[str, ...] = ()


@dataclass
class AggregatedSeason:
    season_number: int
    episodes: list[AggregatedEpisode] = field(default_factory=list)
    subtitles_count: int = 0


@dataclass
class AggregatedWork:
    id: str
    title: str
    media_type: str  # "movie" | "series"
    year: int | None
    year_end: int | None
    imdb_id: str | None
    tmdb_id: str | None
    providers: tuple[str, ...]
    provider_labels: tuple[str, ...]
    seasons: list[AggregatedSeason] = field(default_factory=list)
    total_episodes: int = 0
    total_subtitles: int = 0
    match_score: float = 0.0
    primary_match_id: str | None = None
    info_chips: list[WorkChip] = field(default_factory=list)

    @property
    def expandable(self) -> bool:
        return bool(self.seasons)

    def display_year(self) -> str:
        if self.year and self.year_end and self.year_end != self.year:
            return f"{self.year}–{self.year_end}"
        return str(self.year) if self.year else ""


@dataclass
class AggregatedSearchCatalog:
    matches: list[AggregatedTitleMatch]
    results: list[AggregatedSubtitleResult]
    works: list[AggregatedWork] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def find_result(self, result_id: str | None) -> AggregatedSubtitleResult | None:
        if not result_id:
            return None
        for item in self.results:
            if item.result_id == result_id:
                return item
        return None

    def find_match(self, match_id: str | None) -> AggregatedTitleMatch | None:
        if not match_id:
            return None
        for item in self.matches:
            if item.id == match_id:
                return item
        return None


class SubtitleSourceProvider(Protocol):
    provider_code: str
    provider_label: str
    capabilities: ProviderCapabilities

    async def search_catalog(self, query: str, languages: str) -> ProviderSearchCatalog:
        ...

    async def download(self, result: ProviderSubtitleResult) -> Path:
        ...
