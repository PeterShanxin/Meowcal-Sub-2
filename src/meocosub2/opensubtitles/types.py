"""Types for the OpenSubtitles client."""

from dataclasses import dataclass


@dataclass
class SubtitleFile:
    file_id: int
    file_name: str


@dataclass
class FeatureCandidate:
    id: int
    title: str
    year: int | None
    imdb_id: str | None
    tmdb_id: str | None
    media_type: str
    season: int | None = None
    episode: int | None = None
    parent_title: str | None = None
    parent_imdb_id: str | None = None
    parent_tmdb_id: str | None = None
    subtitles_count: int = 0
    aka_titles: tuple[str, ...] = ()
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
class SearchResult:
    id: str
    title: str
    year: int | None
    imdb_id: str | None
    media_type: str
    season: int | None
    episode: int | None
    language: str
    download_count: int
    file_id: int
    file_name: str
    parent_title: str | None = None
    parent_imdb_id: str | None = None
    parent_feature_id: int | None = None
    tmdb_id: str | None = None
    parent_tmdb_id: str | None = None
    feature_id: int | None = None
    movie_name: str | None = None
    match_score: float = 0.0

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
class SearchCatalog:
    results: list[SearchResult]
    matches: list[FeatureCandidate]
