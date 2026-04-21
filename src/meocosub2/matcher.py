"""Fuzzy matching between OCR text and subtitle lines."""

from __future__ import annotations

import hashlib
import logging
import re

from rapidfuzz import fuzz, process

from meocosub2.models import MatchResult, SubtitleLine
from meocosub2.textnorm import clean_cjk_text, is_cjk_compactable_char, to_simplified

logger = logging.getLogger(__name__)


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
        self.fuzzy_threshold = fuzzy_threshold
        self.window_forward = window_forward
        self.window_backward = window_backward
        self._last_match_position: int | None = None
        self._last_frame_hash: str | None = None
        self._contains_cjk = any(any(is_cjk_compactable_char(ch) for ch in line.text) for line in subtitles)
        self._use_simplified = self._contains_cjk and target_language != "zht"
        self._normalized = [self._normalize_for_match(line.text) for line in subtitles]

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

    def _search_indices(self) -> range:
        if self._last_match_position is None:
            return range(0, min(len(self.subtitles), 50))
        start = max(0, self._last_match_position - self.window_backward)
        stop = min(len(self.subtitles), self._last_match_position + self.window_forward + 1)
        return range(start, stop)

    def _extract_best(self, normalized_ocr: str, indices: range) -> tuple[int, float] | None:
        choices = {index: self._normalized[index] for index in indices if self._normalized[index]}
        if not choices:
            return None
        match = process.extractOne(
            normalized_ocr,
            choices,
            scorer=fuzz.token_set_ratio,
            score_cutoff=self.fuzzy_threshold,
        )
        if match is None:
            return None
        _, score, index = match
        return index, float(score)

    def match(self, ocr_text: str) -> MatchResult | None:
        normalized_ocr = self._normalize_for_match(ocr_text)
        if len(normalized_ocr) < 3:
            logger.debug("MATCH skip: normalized too short (%d chars) for %r", len(normalized_ocr), ocr_text[:40])
            return None

        current_hash = self._hash_text(normalized_ocr)
        if current_hash == self._last_frame_hash:
            return None
        self._last_frame_hash = current_hash

        window = self._search_indices()
        best = self._extract_best(normalized_ocr, window)
        in_window = best is not None
        if best is None:
            best = self._extract_best(normalized_ocr, range(len(self.subtitles)))
        if best is None:
            logger.debug("MATCH miss: threshold=%d ocr=%r", self.fuzzy_threshold, normalized_ocr[:60])
            return None

        position, score = best
        self._last_match_position = position
        line = self.subtitles[position]
        logger.debug(
            "MATCH hit: idx=%d score=%.1f window=%s src=%r ocr=%r",
            position, score, in_window, line.text[:40], normalized_ocr[:40],
        )
        return MatchResult(
            line_index=line.index,
            score=score,
            source_text=line.text,
            target_text=line.translated or line.text,
        )
