"""Shared text normalization helpers for OCR and subtitle matching."""

from __future__ import annotations

import re
from functools import lru_cache

try:  # pragma: no cover - exercised indirectly in tests/runtime
    from opencc import OpenCC
except Exception:  # pragma: no cover - defensive fallback
    OpenCC = None


def is_cjk_char(ch: str) -> bool:
    return bool(
        ("\u4e00" <= ch <= "\u9fff")
        or ("\u3400" <= ch <= "\u4dbf")
        or ("\u3040" <= ch <= "\u309f")
        or ("\u30a0" <= ch <= "\u30ff")
        or ("\uac00" <= ch <= "\ud7af")
        or ("\uf900" <= ch <= "\ufaff")
        or ("\U00020000" <= ch <= "\U0002ebef")
        or ("\U00030000" <= ch <= "\U000323af")
    )


def is_hangul_char(ch: str) -> bool:
    return "\uac00" <= ch <= "\ud7af"


def is_cjk_compactable_char(ch: str) -> bool:
    return is_cjk_char(ch) and not is_hangul_char(ch)


def is_cjk_punctuation(ch: str) -> bool:
    return ch in {
        "，",
        "。",
        "！",
        "？",
        "：",
        "；",
        "、",
        "（",
        "）",
        "「",
        "」",
        "《",
        "》",
        "“",
        "”",
        "‘",
        "’",
        "…",
        "·",
    }


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_ocr_spaced_cjk(text: str) -> str:
    out: list[str] = []
    previous_emitted: str | None = None
    for index, ch in enumerate(text):
        if ch == " ":
            next_ch = text[index + 1] if index + 1 < len(text) else None
            if (
                previous_emitted is not None
                and next_ch is not None
                and _should_join_without_space(previous_emitted, next_ch)
            ):
                continue
        out.append(ch)
        previous_emitted = ch
    return "".join(out)


def _should_join_without_space(prev: str, next_ch: str) -> bool:
    prev_cjk_like = is_cjk_compactable_char(prev) or is_cjk_punctuation(prev)
    next_cjk_like = is_cjk_compactable_char(next_ch) or is_cjk_punctuation(next_ch)
    return prev_cjk_like and next_cjk_like


@lru_cache(maxsize=2)
def _opencc_converter(config: str):
    if OpenCC is None:
        return None
    return OpenCC(config)


def to_simplified(text: str) -> str:
    converter = _opencc_converter("t2s")
    if converter is None:
        return text
    try:
        return converter.convert(text)
    except Exception:  # pragma: no cover - defensive fallback
        return text


def clean_cjk_text(text: str) -> str:
    return normalize_ocr_spaced_cjk(collapse_whitespace(text))
