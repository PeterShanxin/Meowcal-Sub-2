"""Reading one subtitle file as the dialogue and its translation at once.

A large share of Chinese subtitle files are bilingual: every cue carries the
Chinese line and its English translation as two rows. Such a file is a source
subtitle and a target subtitle in one, and the translation it holds is the best
obtainable - it shares the cue rather than being matched to one by time overlap,
so it is aligned by construction, broken at the same sentence boundaries, and
written by whoever wrote the Chinese burned into the picture.

Measured on one episode's file: 444 of its 450 cues were bilingual, and the
English produced by pairing a separate target file against it differed on 25% to
64% of the episode depending on which file was picked.
"""

from __future__ import annotations

import logging
from typing import NamedTuple

from meocosub2.models import SubtitleLine
from meocosub2.textnorm import is_cjk_char

logger = logging.getLogger(__name__)

# The share of a file's cues that must carry both scripts before it is read as
# bilingual. Well short of all of them: a real file leaves songs, signs and the
# occasional line untranslated, and the measured one carried both scripts on
# 98.7% of its cues. Set low enough to accept a file that is plainly bilingual,
# high enough that a monolingual file with a few stray Latin credits is not.
BILINGUAL_CUE_SHARE = 0.5


class BilingualReport(NamedTuple):
    """What splitting a file's cues by script found."""

    total_cues: int
    split_cues: int

    @property
    def is_bilingual(self) -> bool:
        return bool(self.total_cues) and self.split_cues >= self.total_cues * BILINGUAL_CUE_SHARE


def _rows_by_script(text: str) -> tuple[list[str], list[str]] | None:
    """The cue's rows split into the CJK-written ones and the rest.

    None when the rows do not divide - a cue in one script, wrapped or not, and
    a cue with nothing to divide.
    """
    rows = [row for row in text.splitlines() if row.strip()]
    if len(rows) < 2:
        return None
    cjk = [row for row in rows if any(is_cjk_char(ch) for ch in row)]
    latin = [row for row in rows if not any(is_cjk_char(ch) for ch in row)]
    if not cjk or not latin:
        return None
    return cjk, latin


def split_bilingual(
    lines: list[SubtitleLine], source_language: str, target_language: str
) -> BilingualReport:
    """Fill each cue's `translated` from the other script already inside it.

    Written onto the lines the way `assign_target_translations` writes a paired
    file's, so everything downstream draws a split cue with no further wiring.

    Only tells apart scripts, not languages: the two rows have to be written
    differently for there to be anything to divide, so a pair of languages that
    share a script is left alone. Which row is the dialogue is decided by which
    script the source language is written in, not by which row comes first,
    because files disagree about the order.
    """
    source_is_cjk = _language_is_cjk(source_language)
    if source_is_cjk == _language_is_cjk(target_language):
        return BilingualReport(len(lines), 0)

    split = 0
    for line in lines:
        divided = _rows_by_script(line.text)
        if divided is None:
            continue
        cjk_rows, latin_rows = divided
        own, other = (cjk_rows, latin_rows) if source_is_cjk else (latin_rows, cjk_rows)
        line.text = "\n".join(own)
        line.translated = "\n".join(other)
        split += 1

    report = BilingualReport(len(lines), split)
    if report.is_bilingual:
        logger.debug(
            "Subtitle file carries its own translation on %d of %d cues",
            report.split_cues,
            report.total_cues,
        )
    return report


# Languages whose subtitles are written in the scripts `is_cjk_char` covers.
# Compared as a prefix so that "zh-hans" and "zh" answer alike.
CJK_LANGUAGES = ("zh", "ja", "ko", "yue", "cmn")


def _language_is_cjk(language: str) -> bool:
    code = language.lower().replace("_", "-").split("-")[0]
    return code.startswith(CJK_LANGUAGES)
