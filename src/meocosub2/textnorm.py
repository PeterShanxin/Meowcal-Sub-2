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


# Marks Windows resolves out of a letterbox edge or a border. Sentence
# punctuation is deliberately absent: a trailing ？ or 。 is the subtitle.
_NOISE_MARKS = set("“”„‟‘’‚‛«»")


def _is_stray_mark(token: str) -> bool:
    return len(token) == 1 and (
        token.isdigit() or token in _NOISE_MARKS or (token.isascii() and not token.isalnum())
    )


def trim_edge_noise(text: str) -> str:
    """Drop stray characters stranded at either end of a CJK line.

    Both conditions have to hold: the characters stand alone, and the dialogue
    they are stranded against is CJK. That is what separates the bare "0" Windows
    resolves beside Chinese dialogue from the 7 in "Chapter 7".
    """
    tokens = text.split()
    if not tokens:
        return text.strip()

    leading = 0
    while leading < len(tokens) and _is_stray_mark(tokens[leading]):
        leading += 1
    trailing = 0
    while trailing < len(tokens) - leading and _is_stray_mark(tokens[-1 - trailing]):
        trailing += 1
    if leading + trailing >= len(tokens):
        return " ".join(tokens)

    start = leading if is_cjk_compactable_char(tokens[leading][0]) else 0
    end = len(tokens) - trailing
    if not is_cjk_compactable_char(tokens[end - 1][0]):
        end = len(tokens)
    return " ".join(tokens[start : max(end, start)])


def clean_cjk_text(text: str) -> str:
    return normalize_ocr_spaced_cjk(trim_edge_noise(collapse_whitespace(text)))
