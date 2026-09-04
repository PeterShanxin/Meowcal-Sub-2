"""Containment rules for provider-supplied names used as cache paths.

Subtitle providers control both the file names inside their archives and the ids
those archives are cached under. Neither may decide where this app writes, so
every provider-supplied path component is reduced to a safe single segment and
the resolved destination is checked against its directory before any write.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path, PureWindowsPath

from meocosub2.errors import SubtitleSourceError
from meocosub2.subtitle_sources.utils import SUBTITLE_EXTENSIONS

MAX_SEGMENT_CHARS = 120
_SEPARATORS = re.compile(r"[\\/]+")
_UNSAFE = re.compile(r"[\x00-\x1f<>:\"|?*]")
# Windows refuses these as file names whatever the extension.
_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{digit}" for digit in "123456789"),
    *(f"lpt{digit}" for digit in "123456789"),
}


def safe_segment(name: str, fallback: str) -> str:
    """Reduce a provider-supplied name to one path segment that cannot escape."""
    candidate = unicodedata.normalize("NFC", str(name or ""))
    # Split on both separator styles: a POSIX host must not accept "..\\x" as a name.
    candidate = _SEPARATORS.split(candidate)[-1]
    candidate = PureWindowsPath(candidate).name
    candidate = _UNSAFE.sub("", candidate).strip().strip(".")
    if not candidate or candidate.split(".")[0].casefold() in _RESERVED:
        candidate = fallback
    return candidate[:MAX_SEGMENT_CHARS]


def subtitle_file_name(name: str, fallback_stem: str) -> str:
    """A safe file name that a subtitle parser will recognise."""
    segment = safe_segment(name, f"{fallback_stem}.srt")
    if Path(segment).suffix.casefold() not in SUBTITLE_EXTENSIONS:
        segment = f"{Path(segment).stem or fallback_stem}.srt"
    return segment


def contained_path(directory: Path, *segments: str) -> Path:
    """Join safe segments onto `directory`, refusing anything that escapes it."""
    resolved_root = directory.resolve()
    candidate = directory.joinpath(*segments).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise SubtitleSourceError("A subtitle provider supplied an unsafe file name.")
    return candidate
