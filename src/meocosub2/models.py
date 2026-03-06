"""Shared data models for Meowcal-Sub-2."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SubtitleLine:
    index: int
    start_ms: int
    end_ms: int
    text: str
    translated: str = ""


@dataclass
class SubtitlePair:
    source_lines: list[SubtitleLine]
    target_lines: list[SubtitleLine] = field(default_factory=list)


@dataclass
class MatchResult:
    line_index: int
    score: float
    source_text: str
    target_text: str


@dataclass
class SearchRequest:
    title: str
    source_language: str
    target_language: str


@dataclass
class AppProgress:
    stage: str = ""
    message: str = ""
    current: int = 0
    total: int = 0


@dataclass
class PreparedSession:
    session_id: str
    title: str
    source_language: str
    target_language: str
    source_file_id: int
    source_file_name: str
    source_path: str
    source_line_count: int
    target_file_id: int | None = None
    target_file_name: str | None = None
    target_path: str | None = None
    target_line_count: int = 0
    translated_line_count: int = 0
    used_translation: bool = False


@dataclass
class AppStateSnapshot:
    status: Literal["idle", "searching", "preparing", "running", "stopping", "error"] = "idle"
    title: str = ""
    source_language: str = "en"
    target_language: str = "zh"
    search_results: list[dict[str, object]] = field(default_factory=list)
    selected_source_file_id: int | None = None
    selected_target_file_id: int | None = None
    prepared_session: PreparedSession | None = None
    progress: AppProgress = field(default_factory=AppProgress)
    last_subtitle: str = ""
    error_message: str = ""
    overlay_url: str = ""


@dataclass
class AppWebSocketEvent:
    type: Literal["state", "progress", "subtitle", "style", "error"]
    payload: dict[str, object]
