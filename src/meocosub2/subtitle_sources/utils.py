"""Shared utilities for subtitle source providers."""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from pathlib import Path
from typing import Iterable

from rapidfuzz import fuzz

from meocosub2.languages import is_chinese_family, normalize_source_language

SUBTITLE_EXTENSIONS = (".srt", ".ass", ".ssa", ".vtt")
EPISODE_PATTERN = re.compile(r"\bS(?P<season>\d{1,2})E(?P<episode>\d{1,3})\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\b(?P<year>19\d{2}|20\d{2}|21\d{2})\b")
SEPARATOR_PATTERN = re.compile(r"[|]+")

SUBDL_LANGUAGE_MAP = {
    "english": "en",
    "japanese": "ja",
    "korean": "ko",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "russian": "ru",
    "thai": "th",
    "indonesian": "id",
    "vietnamese": "vi",
    "arabic": "ar",
    "italian": "it",
    "brazillian portuguese": "pt-br",
    "brazilian portuguese": "pt-br",
    "farsi persian": "fa",
    "chinese bg code": "zht",
    "chinese gb code": "zh",
    "big 5": "zht",
    "big 5 code": "zht",
    "big5": "zht",
    "big5 code": "zht",
    "gb": "zh",
    "gb code": "zh",
    "traditional chinese": "zht",
    "simplified chinese": "zh",
}

ASSRT_LANG_MAP = {
    "langeng": "en",
    "langjpn": "ja",
    "langkor": "ko",
    "langspa": "es",
    "langfre": "fr",
    "langger": "de",
    "langchs": "zh",
    "langcht": "zht",
    "langbig5": "zht",
}

PROVIDER_RANK = {"subdl": 0, "assrt": 1, "opensubtitles": 2}


def canonical_title(text: str | None) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    cleaned = ascii_text.casefold().replace("/", " ").replace("_", " ")
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def title_similarity(query: str, candidates: Iterable[str]) -> float:
    normalized_query = canonical_title(query)
    if not normalized_query:
        return 0.0
    best = 0.0
    for item in candidates:
        candidate = canonical_title(item)
        if not candidate:
            continue
        best = max(best, float(fuzz.token_sort_ratio(normalized_query, candidate)))
    return best


def extract_episode_info(*values: str | None) -> tuple[int | None, int | None]:
    for value in values:
        if not value:
            continue
        match = EPISODE_PATTERN.search(value)
        if match:
            return int(match.group("season")), int(match.group("episode"))
    return None, None


def extract_year(*values: str | None) -> int | None:
    for value in values:
        if not value:
            continue
        match = YEAR_PATTERN.search(value)
        if match:
            return int(match.group("year"))
    return None


def best_title_guess(query: str, *values: str | None) -> str:
    segments: list[str] = []
    for value in values:
        if not value:
            continue
        parts = [part.strip() for part in SEPARATOR_PATTERN.split(value.replace("\\/", "/")) if part.strip()]
        for part in parts:
            segments.extend(segment.strip() for segment in part.split("/") if segment.strip())
    if not segments:
        return query
    ranked = sorted(segments, key=lambda item: (title_similarity(query, [item]), len(item)), reverse=True)
    return ranked[0]


def match_group_key(
    title: str,
    media_type: str,
    year: int | None,
    season: int | None,
    episode: int | None,
    parent_title: str | None = None,
) -> tuple[str, str, int, int, int]:
    key_title = parent_title if media_type == "episode" and parent_title else title
    return (canonical_title(key_title), media_type, year or 0, season or 0, episode or 0)


def language_priority(language: str, requested_languages: set[str]) -> int:
    normalized = normalize_source_language(language)
    if normalized in requested_languages:
        return 0
    if is_chinese_family(normalized) and any(is_chinese_family(code) for code in requested_languages):
        return 1
    return 2


def _normalize_subdl_language_key(value: str) -> tuple[str, str]:
    normalized = re.sub(r"[_-]+", " ", value.strip().casefold())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized, normalized.replace(" ", "")


def map_subdl_language(value: str) -> str:
    normalized, compact = _normalize_subdl_language_key(value)
    if normalized in SUBDL_LANGUAGE_MAP:
        return SUBDL_LANGUAGE_MAP[normalized]
    # SubDL sometimes emits bare encoding buckets like "big_5_code" / "gb_code".
    if compact in {"big5", "big5code"}:
        return "zht"
    if compact in {"gb", "gbcode"}:
        return "zh"
    if "chinese" in normalized and ("traditional" in normalized or compact.endswith("bgcode") or "big5" in compact):
        return "zht"
    if "chinese" in normalized:
        return "zh"
    return normalize_source_language(value)


def map_assrt_language(desc: str | None, langlist: dict[str, object] | None = None) -> str:
    keys = {key.casefold() for key in (langlist or {})}
    for key, code in ASSRT_LANG_MAP.items():
        if key in keys:
            return code
    text = (desc or "").strip()
    if "繁" in text or "big5" in text.casefold():
        return "zht"
    if "简" in text or "簡" in text:
        return "zh"
    if "英" in text:
        return "en"
    if "日" in text:
        return "ja"
    if "韩" in text or "韓" in text:
        return "ko"
    if "法" in text:
        return "fr"
    if "德" in text:
        return "de"
    if "西" in text:
        return "es"
    return "zh"


def choose_subtitle_path(paths: Iterable[Path]) -> Path:
    candidates = [path for path in paths if path.suffix.casefold() in SUBTITLE_EXTENSIONS]
    if not candidates:
        raise ValueError("Downloaded archive does not contain a supported subtitle file.")
    candidates.sort(key=lambda item: (SUBTITLE_EXTENSIONS.index(item.suffix.casefold()), len(item.name)))
    return candidates[0]


def extract_zip_bytes(content: bytes, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        extracted: list[Path] = []
        for member in archive.infolist():
            if member.is_dir():
                continue
            target = destination / Path(member.filename).name
            target.write_bytes(archive.read(member))
            extracted.append(target)
    return choose_subtitle_path(extracted)
