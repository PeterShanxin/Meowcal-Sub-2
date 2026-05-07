"""Title canonicalization shared by OpenSubtitles and subtitle_sources providers."""

from __future__ import annotations

import html
import re
import unicodedata


def canonical_title(text: str | None) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", html.unescape(text))
    without_combining = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    cleaned = without_combining.casefold().replace("&", " and ")
    cleaned = re.sub(r"[\"'`]", " ", cleaned)
    cleaned = re.sub(r"[\W_]+", " ", cleaned, flags=re.UNICODE)
    return re.sub(r"\s+", " ", cleaned).strip()
