"""Shared data models for MeoCoSub2."""

from dataclasses import dataclass, field


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
