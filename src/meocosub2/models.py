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
class SourceSubtitleCandidate:
    result_id: str
    file_name: str
    provider: str
    language: str
    path: str
    pair: SubtitlePair


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
    correlation_id: str | None = None


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
    resolved_source_language: str
    source_language_mode: Literal["exact", "family_fallback"]
    session_mode: Literal["subtitle_pair", "ocr_fallback", "auto_candidates"] = "subtitle_pair"
    target_match_mode: Literal[
        "subtitle_file",
        "local_translation",
        "target_subtitle_match",
        "direct_translation",
        "auto_subtitle_file",
        "auto_live_translation",
    ] = "subtitle_file"
    feature_id: str | None = None
    source_file_id: str | None = None
    source_file_name: str | None = None
    source_summary: str | None = None
    source_provider: str | None = None
    source_path: str | None = None
    source_line_count: int = 0
    target_file_id: str | None = None
    target_file_name: str | None = None
    target_provider: str | None = None
    target_path: str | None = None
    target_line_count: int = 0
    translated_line_count: int = 0
    used_translation: bool = False
    source_candidate_count: int = 0
    target_candidate_count: int = 0


@dataclass
class AppStateSnapshot:
    status: Literal["idle", "searching", "preparing", "running", "stopping", "error"] = "idle"
    title: str = ""
    source_language: str = "en"
    target_language: str = "zh"
    search_results: list[dict[str, object]] = field(default_factory=list)
    search_matches: list[dict[str, object]] = field(default_factory=list)
    search_works: list[dict[str, object]] = field(default_factory=list)
    selected_feature_id: str | None = None
    selected_source_file_id: str | None = None
    selected_target_file_id: str | None = None
    prepared_session: PreparedSession | None = None
    progress: AppProgress = field(default_factory=AppProgress)
    last_subtitle: str = ""
    error_message: str = ""
    warning_message: str = ""


@dataclass
class AppWebSocketEvent:
    type: Literal["state", "progress", "subtitle", "style", "error"]
    payload: dict[str, object]


@dataclass
class PreparedRuntime:
    session_mode: Literal["subtitle_pair", "ocr_fallback", "auto_candidates"]
    pair: SubtitlePair | None = None
    target_lines: list[SubtitleLine] = field(default_factory=list)
    feature_id: str | None = None
    source_candidates: list[SourceSubtitleCandidate] = field(default_factory=list)
