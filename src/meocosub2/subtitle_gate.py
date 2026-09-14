"""Deciding when an OCR read is a new subtitle worth acting on.

A subtitle sits on screen for two to four seconds and is captured many times.
Those reads are not identical - a glyph drops, a comma becomes a period, a row
renders half-drawn - so exact string equality treats each variation as fresh
dialogue and puts several renderings of one line on screen in a row.

Thresholds and rules are ported from Meowcal Sub v1, where they were calibrated
against real Windows OCR sessions rather than guessed.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from time import monotonic

from rapidfuzz.distance import Levenshtein

from meocosub2.textnorm import is_cjk_char

# Below this many significant characters, one differing character is a change of
# meaning rather than noise, so similarity is not consulted.
MIN_CHARS_FOR_SIMILARITY = 4
# How much a read has to grow before the extra text is worth acting on. Smaller
# growth was measured to be OCR resolving a stroke, not a second row arriving.
EXTENDED_MIN_NEW_CHARS = 4
# Consecutive reads of one subtitle scored 0.50-0.85 in v1's measured session;
# genuinely different dialogue never exceeded 0.25.
SAME_LINE_SIMILARITY = 0.45
# A two-row cue alternates between rows, so a read is compared against the last
# few lines rather than only the previous one.
REMEMBERED_LINES = 4
REMEMBER_WINDOW_S = 6.0
MIN_CHARS_TO_CARRY_MEANING = 2

_IMPOSSIBLE_INSIDE_A_WORD = set("€£¥•@#$%^&*_+=|\\/<>~§¤©®°±¶†‡˜Ł;")
_NEVER_OPENS_A_WORD = set("@€•_~§¤©®±¶†‡Ł|")


class LineChange(Enum):
    UNSTABLE = "unstable"
    REPEAT = "repeat"
    EXTENDED = "extended"
    NEW = "new"


def normalize(text: str) -> str:
    """Reduce a read to the characters that carry meaning."""
    return "".join(ch.lower() for ch in text if ch.isalnum())


def similarity(left: str, right: str) -> float:
    longest = max(len(left), len(right))
    if longest == 0:
        return 1.0
    return 1.0 - (Levenshtein.distance(left, right) / longest)


def _contains(haystack: str, needle: str) -> bool:
    return bool(needle) and len(needle) < len(haystack) and needle in haystack


def _is_garbled(token: str) -> bool:
    if any(is_cjk_char(ch) for ch in token):
        return False
    for index, ch in enumerate(token):
        if (
            ch in _IMPOSSIBLE_INSIDE_A_WORD
            and index > 0
            and any(previous.isalpha() for previous in token[:index])
            and any(following.isalpha() for following in token[index + 1 :])
        ):
            return True
    return (
        len(token) > 1 and token[0] in _NEVER_OPENS_A_WORD and any(ch.isalpha() for ch in token[1:])
    )


def _carries_content(token: str) -> bool:
    return (
        not _is_garbled(token)
        and sum(1 for ch in token if ch.isalnum()) >= MIN_CHARS_TO_CARRY_MEANING
    )


def is_entirely_noise(text: str) -> bool:
    tokens = text.split()
    return bool(tokens) and not any(_carries_content(token) for token in tokens)


def _wears_a_garbled_prefix(previous: str, current: str) -> bool:
    """A read that is the previous line with OCR debris prepended, not a new row."""
    if not current.endswith(previous):
        return False
    return is_entirely_noise(current[: len(current) - len(previous)])


def classify(previous: str, current: str) -> LineChange:
    """How the current read relates to the last line that was acted on."""
    previous_norm = normalize(previous)
    current_norm = normalize(current)

    if not previous_norm:
        return LineChange.NEW
    if previous_norm == current_norm:
        return LineChange.REPEAT

    # A read that lost characters is OCR dropping them, not dialogue getting
    # shorter - but only when most of the line survives, or short replies get
    # swallowed by any longer line that happens to spell them.
    if _contains(previous_norm, current_norm) and len(current_norm) * 2 >= len(previous_norm):
        return LineChange.REPEAT

    if _contains(current_norm, previous_norm):
        grew_enough = len(current_norm) - len(previous_norm) >= EXTENDED_MIN_NEW_CHARS
        if grew_enough and not _wears_a_garbled_prefix(previous, current):
            return LineChange.EXTENDED
        return LineChange.REPEAT

    if (
        max(len(previous_norm), len(current_norm)) >= MIN_CHARS_FOR_SIMILARITY
        and similarity(previous_norm, current_norm) >= SAME_LINE_SIMILARITY
    ):
        return LineChange.REPEAT

    return LineChange.NEW


@dataclass
class _Remembered:
    text: str
    seen_at: float


class SubtitleGate:
    """Which OCR reads are new subtitles, judged against the last few lines.

    The full containment comparison is only made against the line most recently
    acted on; older entries have to actually resemble the read, because
    normalising strips punctuation and a short reply is contained in plenty of
    unrelated dialogue.
    """

    def __init__(self, *, require_stable_read: bool = False) -> None:
        self._entries: deque[_Remembered] = deque()
        self._require_stable_read = require_stable_read
        self._previous_read = ""

    def classify(self, text: str, now: float | None = None) -> LineChange:
        if self._require_stable_read:
            previous, self._previous_read = self._previous_read, normalize(text)
            # A fade can produce plausible words that fuzzy deduplication then
            # keeps for the entire cue. Confirm the read before remembering it.
            if not self._previous_read or self._previous_read != previous:
                return LineChange.UNSTABLE
        now = monotonic() if now is None else now
        self._forget_stale(now)
        if not self._entries:
            return LineChange.NEW

        newest = len(self._entries) - 1
        strongest = LineChange.NEW
        for position, entry in enumerate(self._entries):
            if position == newest:
                verdict = classify(entry.text, text)
            elif similarity(normalize(entry.text), normalize(text)) >= SAME_LINE_SIMILARITY:
                verdict = LineChange.REPEAT
            else:
                verdict = LineChange.NEW
            if verdict is LineChange.REPEAT:
                # Seeing the cue again means it is still on screen, so the window
                # measures time since it was last seen rather than last acted on.
                entry.seen_at = now
                return LineChange.REPEAT
            if verdict is LineChange.EXTENDED:
                strongest = LineChange.EXTENDED
        return strongest

    def remember(self, text: str, now: float | None = None) -> None:
        now = monotonic() if now is None else now
        self._forget_stale(now)
        if self._require_stable_read:
            # Direct translation must return to an earlier cue after a seek;
            # only the last accepted cue can suppress a confirmed read.
            self._entries.clear()
        self._entries.append(_Remembered(text, now))
        while len(self._entries) > REMEMBERED_LINES:
            self._entries.popleft()

    def clear(self) -> None:
        self._entries.clear()
        self.interrupt_read()

    def interrupt_read(self) -> None:
        """An empty capture breaks agreement between consecutive reads."""
        self._previous_read = ""

    def _forget_stale(self, now: float) -> None:
        fresh = [entry for entry in self._entries if now - entry.seen_at <= REMEMBER_WINDOW_S]
        self._entries = deque(fresh)
