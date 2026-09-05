"""Shared utilities for subtitle source providers."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections.abc import Iterable
from pathlib import Path

from rapidfuzz import fuzz

from meocosub2.languages import is_chinese_family, normalize_source_language
from meocosub2.titleutil import canonical_title

SUBTITLE_EXTENSIONS = (".srt", ".ass", ".ssa", ".vtt")
EPISODE_PATTERN = re.compile(r"\bS(?P<season>\d{1,2})E(?P<episode>\d{1,3})\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\b(?P<year>19\d{2}|20\d{2}|21\d{2})\b")
SEPARATOR_PATTERN = re.compile(r"[|]+")
QUERY_PAREN_YEAR_PATTERN = re.compile(
    r"^(?P<title>.+?)\s*\((?P<year>19\d{2}|20\d{2}|21\d{2})\)\s*$"
)
QUERY_TRAILING_YEAR_PATTERN = re.compile(r"^(?P<title>.+?)\s+(?P<year>19\d{2}|20\d{2}|21\d{2})\s*$")

_ROMAN_SEASON_MAP = {
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
    "VI": 6,
    "VII": 7,
    "VIII": 8,
    "IX": 9,
    "X": 10,
}
# Ordered: most specific first to avoid "Overlord II" being caught by season-digit.
_SEASON_SUFFIX_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(?P<base>.+?)\s+Season\s+(?P<num>\d{1,2})\s*$", re.IGNORECASE), "num"),
    (re.compile(r"^(?P<base>.+?)\s+S(?P<num>\d{1,2})\s*$", re.IGNORECASE), "num"),
    (re.compile(r"^(?P<base>.+?)\s+第(?P<num>\d+)(?:期|季)\s*$"), "num"),
    (re.compile(r"^(?P<base>.+?)\s+(?P<num>\d+)(?:期|季)\s*$"), "num"),
    (re.compile(r"^(?P<base>.+?)\s+(?P<rom>II|III|IV|V|VI|VII|VIII|IX|X)\s*$"), "rom"),
)


def extract_season_suffix(title: str | None) -> tuple[str, int | None]:
    """Detect trailing season markers like 'II', 'S2', 'Season 2', '第2期'.

    Returns (base_title, season_number). Season None means no marker found.
    Used to merge provider cards that label each season as a separate movie.
    """
    if not title:
        return title or "", None
    text = title.strip()
    for pattern, kind in _SEASON_SUFFIX_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        base = match.group("base").strip(" -_:·")
        if not base:
            continue
        if kind == "num":
            try:
                return base, int(match.group("num"))
            except ValueError:
                return base, None
        rom = match.group("rom").upper()
        return base, _ROMAN_SEASON_MAP.get(rom)
    return text, None


def split_query_year(query: str) -> tuple[str, int | None]:
    """Extract a trailing 4-digit year from a user query. Returns (clean_title, year_or_none)."""
    if not query:
        return "", None
    text = query.strip()
    for pattern in (QUERY_PAREN_YEAR_PATTERN, QUERY_TRAILING_YEAR_PATTERN):
        match = pattern.match(text)
        if match:
            title = re.sub(r"\s+", " ", match.group("title")).strip(" -_:/")
            year = int(match.group("year"))
            return title, year
    return text, None


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
        parts = [
            part.strip()
            for part in SEPARATOR_PATTERN.split(value.replace("\\/", "/"))
            if part.strip()
        ]
        for part in parts:
            segments.extend(segment.strip() for segment in part.split("/") if segment.strip())
    if not segments:
        return query
    ranked = sorted(
        segments, key=lambda item: (title_similarity(query, [item]), len(item)), reverse=True
    )
    return ranked[0]


def media_type_category(media_type: str | None) -> str:
    """Collapse raw media types into the high-level work category."""
    if media_type == "movie":
        return "movie"
    if media_type in {"series", "tvshow", "episode"}:
        return "series"
    return "movie"


def work_key(
    *,
    title: str,
    media_type: str,
    year: int | None,
    parent_title: str | None,
    imdb_id: str | None,
) -> tuple[str, str]:
    """Identifier used to bucket provider matches into a single 'work'.

    Movies stay separate (year/IMDb-aware). All seasons and episodes of a
    series fold into one key via parent title or series-level IMDb ID.
    """
    category = media_type_category(media_type)
    if category == "series":
        # Series collapse purely by canonical parent title so imdb-bearing
        # series matches merge with their episode-level siblings (which rarely
        # carry the series IMDb id).
        series_title = parent_title or title
        return ("series", f"title:{canonical_title(series_title)}")
    if media_type == "movie" and imdb_id:
        return ("movie", f"imdb:{imdb_id}")
    return ("movie", f"title:{canonical_title(title)}|{year or 0}")


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.blake2s("\x1f".join(parts).encode("utf-8"), digest_size=6).hexdigest()
    return f"{prefix}-{digest}"


def work_id_for_key(key: tuple[str, str]) -> str:
    """A work's identity, independent of how many providers have answered.

    Search results are merged again every time a provider lands, so an id taken
    from a work's position in that merge names a different show each time the
    list grows underneath the reader.
    """
    return _stable_id("work", *key)


def result_id_for(provider: str, provider_result_id: str, language: str) -> str:
    """A subtitle file's identity, on the same terms as :func:`work_id_for_key`.

    The studio remembers the picked file by this id, so a positional one meant a
    later merge could point an unchanged selection at a different download.
    """
    return _stable_id("result", provider, provider_result_id, language)


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
    if is_chinese_family(normalized) and any(
        is_chinese_family(code) for code in requested_languages
    ):
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
    if "chinese" in normalized and (
        "traditional" in normalized or compact.endswith("bgcode") or "big5" in compact
    ):
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
    candidates.sort(
        key=lambda item: (SUBTITLE_EXTENSIONS.index(item.suffix.casefold()), len(item.name))
    )
    return candidates[0]


def extract_zip_bytes(content: bytes, destination: Path) -> Path:
    from meocosub2.subtitle_sources.cache_paths import contained_path, safe_segment

    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        extracted: list[Path] = []
        for index, member in enumerate(archive.infolist()):
            if member.is_dir():
                continue
            name = safe_segment(member.filename, f"subtitle-{index}.srt")
            target = contained_path(destination, name)
            target.write_bytes(archive.read(member))
            extracted.append(target)
    return choose_subtitle_path(extracted)


#: Markers that only appear in a release name, never in an episode title.
RELEASE_MARKER_PATTERN = re.compile(
    r"(?:\b(?:480|540|720|1080|1440|2160)[pi]\b"
    r"|\b(?:bluray|blu-ray|brrip|bdrip|web-?dl|web-?rip|hdtv|dvdrip|hdrip|remux)\b"
    r"|\b(?:x26[45]|h\.?26[45]|hevc|xvid|divx|aac|ac3|dts|ddp?5\.1)\b"
    r"|\.(?:srt|ass|ssa|vtt|sub|idx)$)",
    re.IGNORECASE,
)


def looks_like_release_name(title: str) -> bool:
    """Whether a provider handed back a file name where an episode title belongs.

    Some providers use the release name as the match title. Rendered as an episode
    title it is unreadable, and the episode code beside it already says more.
    """
    return bool(RELEASE_MARKER_PATTERN.search(title.strip()))
