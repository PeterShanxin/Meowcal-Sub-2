"""Fuzzy matching between OCR text and subtitle lines."""

from __future__ import annotations

import hashlib
import re

from rapidfuzz import fuzz, process

from meocosub2.models import MatchResult, SubtitleLine


class SubtitleMatcher:
    def __init__(
        self,
        subtitles: list[SubtitleLine],
        fuzzy_threshold: int = 65,
        window_forward: int = 30,
        window_backward: int = 5,
    ) -> None:
        self.subtitles = subtitles
        self.fuzzy_threshold = fuzzy_threshold
        self.window_forward = window_forward
        self.window_backward = window_backward
        self._last_match_position: int | None = None
        self._last_frame_hash: str | None = None
        self._normalized = [self.normalize_text(line.text) for line in subtitles]

    @staticmethod
    def normalize_text(text: str) -> str:
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\{[^}]+\}", " ", text)
        text = re.sub(r"\[[^\]]+\]", " ", text)
        text = re.sub(r"[^\w\s]", " ", text.lower())
        return re.sub(r"\s+", " ", text).strip()

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
        normalized_ocr = self.normalize_text(ocr_text)
        if len(normalized_ocr) < 3:
            return None

        current_hash = self._hash_text(normalized_ocr)
        if current_hash == self._last_frame_hash:
            return None
        self._last_frame_hash = current_hash

        best = self._extract_best(normalized_ocr, self._search_indices())
        if best is None:
            best = self._extract_best(normalized_ocr, range(len(self.subtitles)))
        if best is None:
            return None

        position, score = best
        self._last_match_position = position
        line = self.subtitles[position]
        return MatchResult(
            line_index=line.index,
            score=score,
            source_text=line.text,
            target_text=line.translated or line.text,
        )
