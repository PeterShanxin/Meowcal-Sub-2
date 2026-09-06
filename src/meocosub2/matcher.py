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
from meocosub2.textnorm import (
    clean_cjk_text,
    collapse_whitespace,
    is_cjk_char,
    is_cjk_compactable_char,
    normalize_ocr_spaced_cjk,
    to_simplified,
)

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
# How many overlapping cues the plate shows at once. Two speakers talking over
# each other is the case worth covering; past that the plate is a wall of text.
PLATE_LINES = 2
# How far two cues have to overlap before they count as being said together.
# Files routinely end one cue on the millisecond the next begins, and treating
# that as an overlap would put every consecutive pair of lines on the plate.
SIMULTANEOUS_MS = 300
# Cues that genuinely run at once reach the plate as separate rows, the way they
# were on the screen they came from. The overlay's own stylesheet is what renders
# it, and `_flatten_wrapping` is what keeps a single cue from claiming a row it
# does not need.
ROW_BREAK = "\n"
# A row opening with a dash is the subtitle convention for a change of speaker,
# which is a row the plate has to keep. Covers the hyphen and the dashes files
# reach for in its place.
SPEAKER_ROW = re.compile(r"^\s*[-‐-―]\s*\S")

TEXT = "text"
SEMANTIC = "semantic"
BOTH = "both"


class _Candidate(NamedTuple):
    """A line the text scorer picked, before it is turned into an answer."""

    position: int
    span: int
    score: float


def _collapse(text: str) -> str:
    """`normalize_ocr_spaced_cjk` is general despite its name: it decides whether
    the join needs a space, which between two CJK characters it does not."""
    return normalize_ocr_spaced_cjk(collapse_whitespace(text))


def _flatten_wrapping(text: str) -> str:
    """A cue as it should be shown, with the file's own typesetting undone.

    Subtitle files routinely wrap a single sentence across two rows to suit a
    narrower plate than this one. Kept, that wrap reaches the overlay as a row
    break and reads as a second speaker, turning a line of dialogue into a block.

    A cue whose every row opens with a dash is not wrapped: it is the file
    marking two people talking over each other, and those rows are what was on
    the screen the cue came from. Measured over the subtitle files this repo has
    cached, they run from 3% to 92% of a file's multi-row cues, so reading them
    as wrapping would put both speakers on one row.
    """
    rows = [row for row in text.split(ROW_BREAK) if row.strip()]
    if len(rows) > 1 and all(SPEAKER_ROW.match(row) for row in rows):
        return ROW_BREAK.join(_collapse(row) for row in rows)
    return _collapse(text)


def _joined(parts: Iterable[str], separator: str = " ") -> str:
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
    return separator.join(kept)


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
    # Which script a row is written in, and whether its whitespace may be
    # compacted, are separate questions. `is_cjk_compactable_char` answers the
    # second - it leaves out Hangul because Korean needs its spaces - and asking
    # it the first classified both rows of a Korean cue alike, so they were never
    # told apart and every read was scored against the pair.
    wanted = [row for row in rows if any(is_cjk_char(ch) for ch in row) == cjk]
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
        # The latest end time among this line and every line before it, so
        # a backward scan for cues still on screen knows where to stop.
        self._latest_end_by: list[int] = []
        latest = 0
        for line in subtitles:
            latest = max(latest, line.end_ms + FOLLOW_GRACE_MS)
            self._latest_end_by.append(latest)
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

    def _nearby(self, last: int, position_ms: int) -> Iterable[int]:
        """The cues at or before `last` that could still be on screen.

        Cue ends are not ordered with their starts, so the scan cannot stop at
        the first finished cue - a sign outlasts the dialogue under it. What it
        can stop at is the point where no earlier cue ends late enough to
        matter, which `_latest_end_by` answers in one comparison.
        """
        for index in range(last, -1, -1):
            if self._latest_end_by[index] < position_ms:
                return
            yield index

    def _showing_at(self, last: int, position_ms: int) -> list[SubtitleLine]:
        """The lines genuinely on screen together at this point, oldest first.

        Two speakers in one exchange overlap in time, and a file can give two
        cues the same start. Taking only the last of them drops the other from
        the plate, which the viewer reads as a line that failed to translate.

        Sharing a boundary is not sharing the screen. Most files cut one cue
        where the next begins, so "still running" alone would pair up every
        consecutive line in the episode and turn one line of dialogue into two.
        An earlier cue joins the plate only if it is still running
        `SIMULTANEOUS_MS` after the newer one started.
        """
        showing: list[SubtitleLine] = []
        newest: SubtitleLine | None = None
        for index in self._nearby(last, position_ms):
            line = self.subtitles[index]
            if line.end_ms < position_ms:
                continue
            if newest is None:
                newest, showing = line, [line]
                continue
            if len(showing) == PLATE_LINES:
                break
            if line.end_ms - newest.start_ms >= SIMULTANEOUS_MS:
                showing.append(line)
        showing.reverse()
        return showing

    def _holding_at(self, last: int, position_ms: int) -> SubtitleLine | None:
        """The cue to keep on the plate when none is still running.

        The file's cue can end a beat before the burned-in one does, so the most
        recently finished line holds through the grace rather than leaving the
        plate blank between every pair of cues.
        """
        held = [
            self.subtitles[index]
            for index in self._nearby(last, position_ms)
            if self.subtitles[index].end_ms + FOLLOW_GRACE_MS >= position_ms
        ]
        return max(held, key=lambda line: line.end_ms) if held else None

    def line_at(self, position_ms: int) -> MatchResult | None:
        """What the file has on screen at this point in the video.

        For reads that match nothing. The burned-in subtitles are usually a
        different translation from the file, so most reads share no words with
        it - but they share a position, and the file's own lines at that
        position are what the viewer should be reading.
        """
        last = bisect_right(self._starts, position_ms) - 1
        if last < 0:
            return None
        showing = self._showing_at(last, position_ms)
        if not showing:
            held = self._holding_at(last, position_ms)
            if held is None:
                return None
            showing = [held]
        # One of a pair having no translation is not a reason to withhold the
        # other: the plate would go blank for a line the file could answer.
        showing = [line for line in showing if line.translated] or showing
        first, final = showing[0], showing[-1]
        return MatchResult(
            line_index=first.index,
            score=0.0,
            source_text=_joined((_flatten_wrapping(line.text) for line in showing), ROW_BREAK),
            target_text=_joined(
                (_flatten_wrapping(line.translated or line.text) for line in showing), ROW_BREAK
            ),
            start_ms=first.start_ms,
            span=final.index - first.index + 1,
            translated=all(bool(line.translated) for line in showing),
        )

    def position_at(self, position_ms: int) -> int:
        """How far into the file the video has reached, as a position in `subtitles`.

        Unlike `line_at` this answers between cues too, where no line is
        running. Filling ahead needs somewhere to start from more than it needs
        a line to draw, and the cue that most recently began is that place.
        """
        return max(0, bisect_right(self._starts, position_ms) - 1)

    def next_change_ms(self, position_ms: int) -> int | None:
        """When what `line_at` returns changes, or None if it never does again.

        Deliberately built on the same boundary rule as `line_at`: the renderer
        sleeps until this moment and then asks `line_at` what to draw, so a
        disagreement between the two is either a wasted wake-up or, worse, a
        line the renderer sleeps straight through.
        """
        last = bisect_right(self._starts, position_ms) - 1
        following = self._starts[last + 1] if last + 1 < len(self._starts) else None
        if last < 0:
            return following
        showing = self._showing_at(last, position_ms)
        if len(showing) > 1:
            # With two cues on the plate, the first to run out changes it. A
            # single cue running out does not: the grace holds it there.
            changes = min(line.end_ms for line in showing) + 1
        else:
            # Whichever line `line_at` would settle on, running or held, is the
            # one whose grace decides when the plate next changes.
            settled = showing[0] if showing else self._holding_at(last, position_ms)
            if settled is None:
                return following
            changes = settled.end_ms + FOLLOW_GRACE_MS + 1
        return changes if following is None else min(changes, following)

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
        # Two separate questions, and one predicate cannot answer both. Which
        # half of a bilingual cue this read belongs to is about script, so it
        # counts Hangul; which scorer suits it is about spacing, and Korean
        # keeps its spaces, so token_set_ratio serves it as it does English.
        # token_set_ratio degenerates on space-stripped CJK (single token); WRatio handles OCR char drops better.
        ocr_written_in_cjk = any(is_cjk_char(ch) for ch in normalized_ocr)
        ocr_runs_together = any(is_cjk_compactable_char(ch) for ch in normalized_ocr)
        scorer = fuzz.WRatio if ocr_runs_together else fuzz.token_set_ratio
        table = self._normalized if ocr_written_in_cjk else self._normalized_latin

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
            source_text=_joined(_flatten_wrapping(part.text) for part in covered),
            target_text=_joined(
                _flatten_wrapping(part.translated or part.text) for part in covered
            ),
            start_ms=line.start_ms,
            span=candidate.span,
            translated=all(bool(part.translated) for part in covered),
            confidence=confidence,
        )
