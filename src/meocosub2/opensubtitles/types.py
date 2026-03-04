"""Types for the OpenSubtitles client."""

from dataclasses import dataclass


@dataclass
class SubtitleFile:
    file_id: int
    file_name: str


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

    def display_label(self) -> str:
        if self.media_type == "episode" and self.season and self.episode:
            return f"{self.title} S{self.season:02d}E{self.episode:02d} ({self.year}) [{self.language}]"
        return f"{self.title} ({self.year}) [{self.language}]"
