"""Finding the subtitle line a read of the screen belongs to.

Two signals answer that. Text similarity costs a millisecond and is decisive
when it is high, but the streaming site burns in one fansub translation while
the file carries another, so most reads share almost no characters with the line
they belong to. Meaning survives that rewording, at the cost of a round trip to
the embedding engine.

They are not weighed equally. Measured on a real episode, 56 of 64 reads scored
20-40 on text against a threshold of 65 - a band where first place and twentieth
are indistinguishable - so text only votes from above a floor.
"""

from __future__ import annotations

import hashlib
import logging
import re
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable
from typing import NamedTuple

from rapidfuzz import fuzz, process

from meocosub2.models import MatchResult, SubtitleLine
from meocosub2.semantic import SemanticIndex
from meocosub2.textnorm import clean_cjk_text, is_cjk_compactable_char, to_simplified

logger = logging.getLogger(__name__)

# How far a read's length may sit either side of the line it is matched against.
# Measured over a real session: genuine reads ran between 0.73 and 1.33 times the
# length of the line they belonged to.
MIN_LENGTH_RATIO = 0.6
MAX_LENGTH_RATIO = 1.7
# How far past a line's own end the clock may be and still be showing that line.
# Two translations of one scene rarely break their cues in the same places, so
# the file's line often ends a beat before the one burned into the picture does.
FOLLOW_GRACE_MS = 1_500
# A read this close to a line is evidence on its own. It is the bar the playback
# clock already trusts enough to move itself for.
STRONG_TEXT_SCORE = 88.0
# Genuine semantic matches scored 0.62-0.93 over a real session, and reads too
# damaged to be anything scored 0.47-0.55. The bar sits clear of the junk
# ceiling, which also turns away the weakest genuine matches - deliberately,
# because the clock draws almost every line either way, so what matters is that
# the lines it does accept are right.
SEMANTIC_ACCEPT = 0.66
# Two translations rarely break their cues in the same places, so the signals
# landing a line apart is agreement rather than a conflict.
AGREEING_LINES = 1

TEXT = "text"
SEMANTIC = "semantic"
BOTH = "both"


class _Candidate(NamedTuple):
    """A line the text scorer picked, before it is turned into an answer."""

    position: int
    span: int
    score: float


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
        self._contains_cjk = any(
            any(is_cjk_compactable_char(ch) for ch in line.text) for line in subtitles
        )
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
        return {index: text for index, text in choices.items() if shortest <= len(text) <= longest}

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

    def line_at(self, position_ms: int) -> MatchResult | None:
        """The line the file has on screen at this point in the video.

        For reads that match nothing. The burned-in subtitles are usually a
        different translation from the file, so most reads share no words with
        it - but they share a position, and the file's own line at that position
        is the one the viewer should be reading.
        """
        position = bisect_right(self._starts, position_ms) - 1
        if position < 0:
            return None
        line = self.subtitles[position]
        if position_ms > line.end_ms + FOLLOW_GRACE_MS:
            return None
        return MatchResult(
            line_index=line.index,
            score=0.0,
            source_text=line.text,
            target_text=line.translated or line.text,
            start_ms=line.start_ms,
            span=1,
            translated=bool(line.translated),
        )

    def next_change_ms(self, position_ms: int) -> int | None:
        """When the line `line_at` returns changes, or None if it never does again.

        Deliberately built on the same boundary rule as `line_at`: the renderer
        sleeps until this moment and then asks `line_at` what to draw, so a
        disagreement between the two is either a wasted wake-up or, worse, a
        line the renderer sleeps straight through.
        """
        position = bisect_right(self._starts, position_ms) - 1
        following = self._starts[position + 1] if position + 1 < len(self._starts) else None
        if position < 0:
            return following
        # `line_at` keeps showing a line while the clock is within the grace, so
        # the first position where it stops is one millisecond past the end of it.
        expires = self.subtitles[position].end_ms + FOLLOW_GRACE_MS + 1
        if expires <= position_ms:
            return following
        return expires if following is None else min(expires, following)

    def match(self, ocr_text: str, window_ms: tuple[int, int] | None = None) -> MatchResult | None:
        """The best line by text alone."""
        normalized_ocr = self._normalize_for_match(ocr_text)
        if not self._worth_matching(normalized_ocr):
            return None
        best = self._fuzzy(normalized_ocr, window_ms)
        return None if best is None else self._result(best, TEXT)

    async def match_best(
        self,
        ocr_text: str,
        window_ms: tuple[int, int] | None = None,
        semantic: SemanticIndex | None = None,
    ) -> MatchResult | None:
        """The best line by text and by meaning together.

        Text wins outright when it is near-exact, which also spares the round
        trip to the embedding engine on the reads that need it least. Below
        that, meaning ranks the candidates and text is a second opinion -
        confirming the line, or taking precedence over a different one.
        """
        normalized_ocr = self._normalize_for_match(ocr_text)
        if not self._worth_matching(normalized_ocr):
            return None

        fuzzy = self._fuzzy(normalized_ocr, window_ms)
        if fuzzy is not None and fuzzy.score >= STRONG_TEXT_SCORE:
            return self._result(fuzzy, TEXT)
        if semantic is None or not semantic.ready:
            return None if fuzzy is None else self._result(fuzzy, TEXT)

        # With a clock, only the lines it left in the window. Without one the
        # video could be anywhere in the file, so everything is a candidate.
        indices = (
            self._search_indices(window_ms) if window_ms is not None else range(len(self.subtitles))
        )
        hit = await semantic.best(ocr_text, indices)
        if hit is None or hit.score < SEMANTIC_ACCEPT:
            return None if fuzzy is None else self._result(fuzzy, TEXT)

        if fuzzy is not None:
            # A text answer at all means the read cleared `fuzzy_threshold`, so
            # it is real evidence rather than the 20-40 noise most reads score:
            # it confirms the same line, or takes precedence over a different one.
            agrees = abs(fuzzy.position - hit.index) <= AGREEING_LINES
            return self._result(fuzzy, BOTH if agrees else TEXT)

        self._last_match_position = hit.index
        logger.debug(
            "MATCH semantic: idx=%d score=%.2f src=%r ocr=%r",
            hit.index,
            hit.score,
            self.subtitles[hit.index].text[:40],
            normalized_ocr[:40],
        )
        return self._result(_Candidate(hit.index, 1, hit.score * 100), SEMANTIC)

    def _worth_matching(self, normalized_ocr: str) -> bool:
        """Whether this read says anything the last one did not."""
        if self._is_too_short(normalized_ocr):
            logger.debug(
                "MATCH skip: normalized too short (%d chars) for %r",
                len(normalized_ocr),
                normalized_ocr[:40],
            )
            return False
        current_hash = self._hash_text(normalized_ocr)
        if current_hash == self._last_frame_hash:
            return False
        self._last_frame_hash = current_hash
        return True

    def _fuzzy(self, normalized_ocr: str, window_ms: tuple[int, int] | None) -> _Candidate | None:
        # token_set_ratio degenerates on space-stripped CJK (single token); WRatio handles OCR char drops better.
        ocr_is_cjk = any(is_cjk_compactable_char(ch) for ch in normalized_ocr)
        scorer = fuzz.WRatio if ocr_is_cjk else fuzz.token_set_ratio
        table = self._normalized if ocr_is_cjk else self._normalized_latin

        window = self._search_indices(window_ms)
        best = self._extract_best(normalized_ocr, window, scorer, table)
        in_window = best is not None
        if best is None:
            best = self._extract_best(normalized_ocr, range(len(self.subtitles)), scorer, table)
        if best is None:
            logger.debug(
                "MATCH miss: threshold=%d ocr=%r", self.fuzzy_threshold, normalized_ocr[:60]
            )
            return None

        position, span, score = best
        self._last_match_position = position
        logger.debug(
            "MATCH hit: idx=%d span=%d score=%.1f window=%s src=%r ocr=%r",
            position,
            span,
            score,
            in_window,
            self.subtitles[position].text[:40],
            normalized_ocr[:40],
        )
        return _Candidate(position, span, score)

    def _result(self, candidate: _Candidate, confidence: str) -> MatchResult:
        covered = self.subtitles[candidate.position : candidate.position + candidate.span]
        line = covered[0]
        return MatchResult(
            line_index=line.index,
            score=candidate.score,
            source_text=_joined(part.text for part in covered),
            target_text=_joined((part.translated or part.text) for part in covered),
            start_ms=line.start_ms,
            span=candidate.span,
            translated=all(bool(part.translated) for part in covered),
            confidence=confidence,
        )
