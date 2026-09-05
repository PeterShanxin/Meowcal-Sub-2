"""Fuzzy matching between OCR text and subtitle lines."""

from __future__ import annotations

import hashlib
import logging
import re
from bisect import bisect_left, bisect_right
from collections.abc import Iterable
from typing import Callable

from rapidfuzz import fuzz, process

from meocosub2.models import MatchResult, SubtitleLine
from meocosub2.textnorm import clean_cjk_text, is_cjk_compactable_char, to_simplified

logger = logging.getLogger(__name__)

# How far a read's length may sit either side of the line it is matched against.
# Measured over a real session: genuine reads ran between 0.73 and 1.33 times the
# length of the line they belonged to.
MIN_LENGTH_RATIO = 0.6
MAX_LENGTH_RATIO = 1.7


def _joined(parts: Iterable[str]) -> str:
    """Join the lines a read covered, without saying anything twice.

    Two source cues can be paired with one target line - the alignment goes by
    time overlap, and a target file that splits a sentence differently gives
    both halves the same partner. Joined verbatim, that line lands on the plate
    twice over.
    """
    kept: list[str] = []
    for part in parts:
        if part and (not kept or kept[-1] != part):
            kept.append(part)
    return " ".join(kept)


def _script_rows(text: str, cjk: bool) -> str:
    """The rows of a cue written in the script the read is in.

    A subtitle file can carry both languages in one cue - a row of dialogue with
    its translation underneath. A read is only ever one of them, so scoring it
    against both at once drags genuine matches down and, because the cue is then
    several times longer than the read, lets any long read score highly on a
    fragment of one. A cue written in a single script is left whole.
    """
    rows = [row for row in text.splitlines() if row.strip()]
    if len(rows) < 2:
        return text
    wanted = [row for row in rows if any(is_cjk_compactable_char(ch) for ch in row) == cjk]
    return "\n".join(wanted) if wanted and len(wanted) < len(rows) else text


class SubtitleMatcher:
    def __init__(
        self,
        subtitles: list[SubtitleLine],
        fuzzy_threshold: int = 65,
        window_forward: int = 30,
        window_backward: int = 5,
        target_language: str = "",
    ) -> None:
        self.subtitles = subtitles
        self._starts = [line.start_ms for line in subtitles]
        self.fuzzy_threshold = fuzzy_threshold
        self.window_forward = window_forward
        self.window_backward = window_backward
        self._last_match_position: int | None = None
        self._last_frame_hash: str | None = None
        self._contains_cjk = any(any(is_cjk_compactable_char(ch) for ch in line.text) for line in subtitles)
        self._use_simplified = self._contains_cjk and target_language != "zht"
        self._normalized = [
            self._normalize_for_match(_script_rows(line.text, True)) for line in subtitles
        ]
        self._normalized_latin = [
            self._normalize_for_match(_script_rows(line.text, False)) for line in subtitles
        ]
        # Normalising CJK closes the spaces between characters, so a pair of
        # lines has to be joined the same way the lines themselves were.
        self._join = "" if self._contains_cjk else " "

    @staticmethod
    def normalize_text(text: str) -> str:
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\{[^}]+\}", " ", text)
        text = re.sub(r"\[[^\]]+\]", " ", text)
        text = re.sub(r"[^\w\s]", " ", text.lower())
        return re.sub(r"\s+", " ", text).strip()

    def _normalize_for_match(self, text: str) -> str:
        normalized = self.normalize_text(text)
        if self._contains_cjk or any(is_cjk_compactable_char(ch) for ch in normalized):
            cleaned = clean_cjk_text(normalized)
            return to_simplified(cleaned) if self._use_simplified else cleaned
        return normalized

    def _hash_text(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_too_short(normalized_ocr: str) -> bool:
        # Single CJK chars are word-meaningful (e.g. "好"); ASCII <3 chars is usually noise.
        ocr_is_cjk = any(is_cjk_compactable_char(ch) for ch in normalized_ocr)
        min_length = 1 if ocr_is_cjk else 3
        return len(normalized_ocr) < min_length

    def is_repeated_frame(self, ocr_text: str) -> bool:
        normalized_ocr = self._normalize_for_match(ocr_text)
        if self._is_too_short(normalized_ocr):
            return False
        return self._hash_text(normalized_ocr) == self._last_frame_hash

    def reset(self) -> None:
        self._last_match_position = None
        self._last_frame_hash = None

    def _search_indices(self, window_ms: tuple[int, int] | None = None) -> range:
        """The lines worth scoring this read against.

        A window in milliseconds comes from the playback clock and is the better
        one: line density varies wildly within an episode, so a fixed count of
        lines covers a different amount of video at every point in it.
        """
        if window_ms is not None:
            low, high = window_ms
            start = bisect_left(self._starts, low)
            stop = bisect_right(self._starts, high)
            if start < stop:
                return range(start, stop)
        if self._last_match_position is None:
            initial_cap = self.window_forward + self.window_backward
            return range(0, min(len(self.subtitles), initial_cap))
        start = max(0, self._last_match_position - self.window_backward)
        stop = min(len(self.subtitles), self._last_match_position + self.window_forward + 1)
        return range(start, stop)

    def _best_of(
        self,
        normalized_ocr: str,
        choices: dict[int, str],
        scorer: Callable[[str, str], float],
    ) -> tuple[int, float] | None:
        if not choices:
            return None
        match = process.extractOne(
            normalized_ocr,
            self._plausible_lengths(normalized_ocr, choices),
            scorer=scorer,
            score_cutoff=self.fuzzy_threshold,
        )
        if match is None:
            return None
        _, score, index = match
        return index, float(score)

    def _plausible_lengths(self, normalized_ocr: str, choices: dict[int, str]) -> dict[int, str]:
        """The candidates this read could be, judged only on how long they are.

        A read of a subtitle is about as long as the subtitle. The scorers used
        here reward a good match on part of a much longer line, which is how a
        stray read of a terminal or a chat window scored in the eighties against
        real dialogue; a line the read could not plausibly be is not scored.
        """
        length = len(normalized_ocr)
        shortest = length / MAX_LENGTH_RATIO
        longest = length / MIN_LENGTH_RATIO
        return {
            index: text
            for index, text in choices.items()
            if shortest <= len(text) <= longest
        }

    def _extract_best(
        self,
        normalized_ocr: str,
        indices: range,
        scorer: Callable[[str, str], float],
        table: list[str],
    ) -> tuple[int, int, float] | None:
        """The best line, or pair of lines, in `indices` - as (index, span, score)."""
        singles = {index: table[index] for index in indices if table[index]}
        best_single = self._best_of(normalized_ocr, singles, scorer)

        pairs = {
            index: self._join.join((table[index], table[index + 1]))
            for index in indices
            if index + 1 < len(table) and table[index] and table[index + 1]
        }
        best_pair = self._best_of(normalized_ocr, pairs, scorer)

        if best_pair is None:
            return (best_single[0], 1, best_single[1]) if best_single is not None else None
        if best_single is None:
            return best_pair[0], 2, best_pair[1]

        # Both cleared the threshold, and the scorers used to get there cannot
        # separate them: a set comparison calls a line that is a subset of the
        # read a perfect hit, so "the line" and "the line plus the next one"
        # both score 100. Which one the read actually is, is a question of
        # length, so the tie is broken by a comparison that counts it.
        single_fit = fuzz.ratio(normalized_ocr, singles[best_single[0]])
        pair_fit = fuzz.ratio(normalized_ocr, pairs[best_pair[0]])
        if pair_fit > single_fit:
            return best_pair[0], 2, best_pair[1]
        return best_single[0], 1, best_single[1]

    def match(self, ocr_text: str, window_ms: tuple[int, int] | None = None) -> MatchResult | None:
        normalized_ocr = self._normalize_for_match(ocr_text)
        if self._is_too_short(normalized_ocr):
            logger.debug("MATCH skip: normalized too short (%d chars) for %r", len(normalized_ocr), ocr_text[:40])
            return None

        current_hash = self._hash_text(normalized_ocr)
        if current_hash == self._last_frame_hash:
            return None
        self._last_frame_hash = current_hash

        # token_set_ratio degenerates on space-stripped CJK (single token); WRatio handles OCR char drops better.
        ocr_is_cjk = any(is_cjk_compactable_char(ch) for ch in normalized_ocr)
        scorer = fuzz.WRatio if ocr_is_cjk else fuzz.token_set_ratio
        table = self._normalized if ocr_is_cjk else self._normalized_latin

        window = self._search_indices(window_ms)
        best = self._extract_best(normalized_ocr, window, scorer, table)
        in_window = best is not None
        if best is None:
            best = self._extract_best(
                normalized_ocr, range(len(self.subtitles)), scorer, table
            )
        if best is None:
            logger.debug("MATCH miss: threshold=%d ocr=%r", self.fuzzy_threshold, normalized_ocr[:60])
            return None

        position, span, score = best
        self._last_match_position = position
        covered = self.subtitles[position : position + span]
        line = covered[0]
        logger.debug(
            "MATCH hit: idx=%d span=%d score=%.1f window=%s src=%r ocr=%r",
            position, span, score, in_window, line.text[:40], normalized_ocr[:40],
        )
        return MatchResult(
            line_index=line.index,
            score=score,
            source_text=_joined(part.text for part in covered),
            target_text=_joined((part.translated or part.text) for part in covered),
            start_ms=line.start_ms,
            span=span,
            translated=all(bool(part.translated) for part in covered),
        )
