"""Synchronize OCR to source subtitles and render the chosen presentation track.

A source match places PlaybackTimeline. An independent target file then owns
its cue transitions; source-carried and model translations answer uncovered
source cues. Without an anchor, live OCR translation supplies the plate.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from time import monotonic

from meocosub2.capture import capture_region, ocr_image
from meocosub2.config import AppConfig
from meocosub2.engine import EngineInstallError, EngineStartError
from meocosub2.gapfill import fill_gaps
from meocosub2.matcher import BOTH, SubtitleMatcher
from meocosub2.models import MatchResult, SourceSubtitleCandidate, SubtitleLine
from meocosub2.presentation import PresentationTrack
from meocosub2.semantic import SemanticError, SemanticIndex
from meocosub2.subtitle_gate import LineChange, SubtitleGate
from meocosub2.timeline import PlaybackTimeline
from meocosub2.translator import TranslationClient, is_untranslatable, open_translation_client

logger = logging.getLogger(__name__)

# A candidate has to win by this much before the session commits to it, or by
# agreeing with itself across this many reads.
AUTO_LOCK_SCORE = 92.0
AUTO_CONFIRM_HITS = 2
AUTO_UNLOCK_MISSES = 3
# Consecutive empty reads before the overlay clears. One blank frame is a cue
# transition; several in a row mean nothing is on screen.
CLEAR_AFTER_EMPTY_READS = 3
# How long to wait before looking again at which candidate is being followed.
# Locking onto one is what a whole run of reads decides, so this costs nothing
# to check slowly.
FOLLOW_POLL_S = 1.0
# How far ahead of the clock the plate is drawn, negative to hold it back.
# The clock does not need help arriving early: it anchors at the moment a cue
# was first seen rather than the moment it was recognised, which already takes
# the capture and OCR delay out of it. Measured against a real player twice,
# each run about half a second ahead of the dialogue, so the plate waits.
DISPLAY_LEAD_MS = -650
# The longest the renderer sleeps in one go. Every cue boundary is still woken
# for exactly, and a nudge still wakes it at once; this only bounds how stale
# the viewer's own offset can be, because changing it moves every boundary the
# renderer has already worked out and nothing tells it so. Redrawing the line
# already on the plate broadcasts nothing, so the extra wakes cost a comparison.
RETIME_CHECK_S = 0.2
TRANSLATION_CACHE_SIZE = 64
CONTEXT_LINES = 3

MATCHED = "matched"
TRANSLATED = "translated"

Broadcast = Callable[[str, str], Awaitable[None]]
DebugBroadcast = Callable[[dict[str, object]], Awaitable[None]]
RegionSource = Callable[[], tuple[int, ...]]
BiasSource = Callable[[], int]
TranslatorFactory = Callable[[], Awaitable["LiveTranslator"]]
# Supplied by whoever starts the session rather than reached for here, so a
# session can be run - and tested - without an embedding engine behind it.
SemanticFactory = Callable[[], Awaitable[SemanticIndex]]


@dataclass
class Resolution:
    """What a read came to.

    Either a line ready for the plate, or the text to translate for it - the
    clean subtitle line when one matched, the raw read when none did.
    """

    text: str = ""
    translate: str = ""
    matched: bool = False
    # The last file line this answer covers. A read can match a cue the file
    # splits across two lines; the clock only ever answers with one.
    covers_through: int | None = None
    detail: dict[str, object] = field(default_factory=dict)

    @property
    def source(self) -> str:
        return MATCHED if self.matched else TRANSLATED


class LiveTranslator:
    """Caches translations and carries recent lines as context, like v1's session cache."""

    def __init__(
        self, client: TranslationClient, source_language: str, target_language: str
    ) -> None:
        self._client = client
        self._source_language = source_language
        self._target_language = target_language
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._context: deque[str] = deque(maxlen=CONTEXT_LINES)

    async def translate_from_file(self, text: str, pairs: list[tuple[str, str]]) -> str:
        """Translate a line of the subtitle file, in the voice the file already uses.

        Deliberately outside the cache and the rolling context: both describe
        what has been on screen, and a cue being answered ahead of time has not.
        The pairs carry their own echo context, so none is passed here.
        """
        return await self._client.translate(
            text,
            self._source_language,
            self._target_language,
            pairs=pairs,
        )

    async def translate(self, text: str) -> str:
        key = SubtitleMatcher.normalize_text(text)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        translated = await self._client.translate(
            text, self._source_language, self._target_language, list(self._context)
        )
        if translated:
            self._cache[key] = translated
            while len(self._cache) > TRANSLATION_CACHE_SIZE:
                self._cache.popitem(last=False)
            self._context.append(translated)
        return translated


class CandidateSession:
    """Matches OCR against source candidates and resolves their presentation tracks.

    With one candidate this is a straight match. With several it locks onto the
    one that agrees with the screen and unlocks when it stops agreeing, so a
    wrong release or a mismatched cut does not pin the session to bad timings.
    """

    mode = "candidates"

    def __init__(
        self,
        candidates: list[SourceSubtitleCandidate],
        config: AppConfig,
        translator: TranslatorFactory,
        semantic: SemanticFactory | None = None,
        bias_source: BiasSource | None = None,
    ) -> None:
        self._matchers = {
            candidate.result_id: SubtitleMatcher(
                candidate.pair.source_lines,
                config.fuzzy_threshold,
                config.match_window_size,
                config.match_window_backward,
                target_language=config.target_language,
            )
            for candidate in candidates
        }
        self._presentations = {
            candidate.result_id: candidate.pair.presentation for candidate in candidates
        }
        self.has_target_file = any(
            candidate.pair.target_lines
            or any(line.translated for line in candidate.pair.source_lines)
            for candidate in candidates
        )
        self._open_translator = translator
        self._open_index = semantic
        # Read rather than captured: the viewer retimes the plate from the dock
        # while the session runs, the same way they reselect the capture region.
        self._bias_ms = bias_source or (lambda: config.sync_bias_ms)
        self._timeline = PlaybackTimeline()
        self._locked: str | None = next(iter(self._matchers)) if len(self._matchers) == 1 else None
        self._pending: str = ""
        self._pending_hits = 0
        self._misses = 0
        self._semantic: SemanticIndex | None = None
        self._semantic_build: asyncio.Task[None] | None = None

    @property
    def presentation(self) -> PresentationTrack | None:
        return self._presentations.get(self._locked) if self._locked is not None else None

    @property
    def independent_target(self) -> bool:
        track = self.presentation
        return track is not None and bool(track.target_lines)

    @property
    def followed_lines(self) -> list[SubtitleLine]:
        """The source lines of the candidate being followed, empty until one is."""
        if self._locked is None:
            return []
        return self._matchers[self._locked].subtitles

    async def translate_from_file(self, text: str, pairs: list[tuple[str, str]]) -> str:
        translator = await self._open_translator()
        return await translator.translate_from_file(text, pairs)

    def close(self) -> None:
        if self._semantic_build is not None:
            self._semantic_build.cancel()

    def _open_semantic(self) -> None:
        """Start encoding the locked candidate, if that has not been tried yet.

        In the background: starting the engine and encoding a whole file takes
        seconds, and the capture loop cannot stop for them. Until it finishes,
        reads are matched on text alone, which is what a session did before this
        model existed. It is attempted once - a machine without the model, or
        without the engine, is not going to acquire either mid-session.
        """
        if self._open_index is None or self._locked is None or self._semantic_build is not None:
            return
        lines = [line.text for line in self._matchers[self._locked].subtitles]
        self._semantic_build = asyncio.create_task(self._build_semantic(self._open_index, lines))

    async def _build_semantic(self, open_index: SemanticFactory, lines: list[str]) -> None:
        try:
            index = await open_index()
            await index.build(lines)
        except asyncio.CancelledError:
            raise
        except (EngineInstallError, EngineStartError, SemanticError) as error:
            # Matching by meaning improves a session; it is not required for
            # one. Without it, reads are matched on text alone.
            logger.warning("Matching by meaning is unavailable this session: %s", error)
            return
        self._semantic = index

    def saw_new_cue(self, at: float | None = None) -> None:
        self._timeline.saw_new_cue(at)

    def saw_same_cue(self, at: float | None = None) -> None:
        self._timeline.saw_same_cue(at)

    def status(self) -> dict[str, object]:
        timeline = self._timeline.status()
        return {
            "predictedMs": timeline.predicted_ms,
            "driftMs": timeline.drift_ms,
            "anchored": timeline.anchored,
            "lockedCandidateId": self._locked,
        }

    async def match(self, ocr_text: str, follow: bool = True) -> Resolution | None:
        self._open_semantic()
        winner, result = await self._match(ocr_text)
        if winner is None or result is None:
            return self.line_now() if follow else None
        detail: dict[str, object] = {
            "matchIdx": result.line_index,
            "matchScore": round(result.score, 1),
            "matchSpan": result.span,
            "matchSrc": result.source_text[:60],
            "matchBy": result.confidence,
            "candidateId": winner,
            "confirmed": True,
            **self.status(),
        }
        if self.independent_target:
            resolution = self.line_now()
            if resolution is not None:
                resolution.detail.update(detail)
            return resolution
        covers_through = result.line_index + result.span - 1
        if result.translated:
            return Resolution(
                text=result.target_text,
                matched=True,
                covers_through=covers_through,
                detail=detail,
            )
        # The file carries this line but nothing paired with it. Translating the
        # subtitle's own words beats translating the read: same sentence, none
        # of the OCR damage.
        return Resolution(
            translate=result.source_text,
            matched=True,
            covers_through=covers_through,
            detail=detail,
        )

    @property
    def anchored(self) -> bool:
        return self._locked is not None and self._timeline.anchored

    def clock_ms(self, now: float | None = None) -> int | None:
        """Where the plate reads from, which is a little behind the video.

        Every caller that draws or schedules goes through here, so the line that
        is shown and the moment it is scheduled to change cannot disagree.

        The measured lag and the viewer's own offset add up: both answer the same
        question, and the viewer is correcting what the measurement did not cover
        for their player.
        """
        position = self._timeline.position_ms(now)
        if position is None:
            return None
        anchor = self._timeline.anchor_ms
        # The lag holds the plate back as playback advances; it must never read
        # behind the line the clock was just anchored to, which is on screen by
        # definition. Without the floor, a match would blank the plate it filled.
        lagged = position + DISPLAY_LEAD_MS
        if anchor is not None:
            lagged = max(lagged, anchor)
        # The viewer's offset applies after the floor rather than inside it. The
        # floor exists to protect a match from the measured lag; folding an
        # offset into it would let the floor swallow one asking for a later
        # plate, which is the direction a viewer reaches for when the plate runs
        # ahead of their player.
        return lagged + self._bias_ms()

    @property
    def followed_position(self) -> int | None:
        """How far into the followed file the video has reached, None until placed."""
        position = self.clock_ms()
        if self._locked is None or position is None:
            return None
        return self._matchers[self._locked].position_at(position)

    def seconds_to_next_line(self) -> float | None:
        """How long until the file's line changes; None when nothing is placed."""
        position = self.clock_ms()
        if self._locked is None or position is None:
            return None
        track = self.presentation
        change = (
            track.next_change_ms(position)
            if track is not None and track.target_lines
            else self._matchers[self._locked].next_change_ms(position)
        )
        return None if change is None else max(0.0, (change - position) / 1000)

    def line_now(self) -> Resolution | None:
        """Resolve the current source clock through the chosen presentation owner.

        Independent target intervals also answer with explicit silence. Sessions
        using only source-aligned translations retain their source cue behavior.
        """
        position = self.clock_ms()
        if self._locked is None or position is None:
            return None
        track = self.presentation
        if track is not None and track.target_lines:
            frame = track.resolve_at(position)
            return Resolution(
                text=frame.text,
                matched=True,
                detail={
                    "presentationCues": [asdict(cue) for cue in frame.cues],
                    "presentationClockMs": position + track.offset_ms,
                    "mappingOffsetMs": track.offset_ms,
                    "candidateId": self._locked,
                    "confirmed": False,
                    **self.status(),
                },
            )
        result = self._matchers[self._locked].line_at(position)
        if result is None:
            return Resolution(text="", matched=True, detail=dict(self.status()))
        if not result.translated:
            # The file carries this line with nothing paired to it, so the model
            # is filling the plate. Blanking it here would undo that.
            return None
        return Resolution(
            text=result.target_text,
            matched=True,
            covers_through=result.line_index + result.span - 1,
            detail={
                "matchIdx": result.line_index,
                "matchSrc": result.source_text[:60],
                "candidateId": self._locked,
                "confirmed": False,
                **self.status(),
            },
        )

    async def translate(self, text: str) -> str:
        translator = await self._open_translator()
        return await translator.translate(text)

    async def _match(self, ocr_text: str) -> tuple[str | None, MatchResult | None]:
        window = self._timeline.window_ms()
        if self._locked is not None:
            result = await self._matchers[self._locked].match_best(ocr_text, window, self._semantic)
            if result is not None and self._timeline.accepts(
                result.start_ms,
                result.line_index,
                result.score,
                confident=result.confidence == BOTH,
            ):
                self._misses = 0
                return self._locked, result
            self._misses += 1
            if len(self._matchers) == 1 or self._misses < AUTO_UNLOCK_MISSES:
                return None, None
            logger.debug(
                "Unlocking subtitle candidate %s after %d misses", self._locked, self._misses
            )
            self._locked = None
            self._misses = 0

        # Candidates are separated on text alone: the semantic index is built
        # for the one that wins, so there is none to consult until it has.
        best_id, best = "", None
        for result_id, matcher in self._matchers.items():
            result = matcher.match(ocr_text, window)
            if result is not None and (best is None or result.score > best.score):
                best_id, best = result_id, result
        if best is None:
            return None, None

        if best.score >= AUTO_LOCK_SCORE:
            self._lock(best_id)
        elif best_id == self._pending:
            self._pending_hits += 1
            if self._pending_hits >= AUTO_CONFIRM_HITS:
                self._lock(best_id)
        else:
            self._pending, self._pending_hits = best_id, 1
        if self._locked != best_id:
            # Only a locked candidate is trusted enough to put text on screen.
            return None, None
        if not self._timeline.accepts(best.start_ms, best.line_index, best.score):
            return None, None
        return best_id, best

    def _lock(self, result_id: str) -> None:
        logger.debug("Locked subtitle candidate %s", result_id)
        # An index built for the candidate being left behind holds vectors for a
        # different subtitle file, and its row numbers mean different lines
        # there. Kept, it would let the new candidate anchor on an unrelated
        # line; dropped, the next read starts building an index for this one.
        self.close()
        self._semantic = None
        self._semantic_build = None
        self._locked = result_id
        self._pending, self._pending_hits, self._misses = "", 0, 0


class DirectTranslationSession:
    """Translates what OCR reads, with no source subtitle file to match against."""

    mode = "translation"
    independent_target = False

    def __init__(
        self,
        target_lines: list[SubtitleLine],
        config: AppConfig,
        translator: TranslatorFactory,
    ) -> None:
        self._open_translator = translator
        self._matcher = (
            SubtitleMatcher(
                target_lines,
                config.fuzzy_threshold,
                config.match_window_size,
                config.match_window_backward,
                target_language=config.target_language,
            )
            if target_lines
            else None
        )

    def saw_new_cue(self, at: float | None = None) -> None:
        return None

    def saw_same_cue(self, at: float | None = None) -> None:
        return None

    def status(self) -> dict[str, object]:
        return {}

    @property
    def anchored(self) -> bool:
        return False

    def line_now(self) -> Resolution | None:
        return None

    def seconds_to_next_line(self) -> float | None:
        return None

    def close(self) -> None:
        return None

    async def match(self, ocr_text: str, follow: bool = True) -> Resolution | None:
        # Nothing to match against until the read has been translated, so every
        # read takes the slow path.
        return None

    async def translate(self, text: str) -> str:
        translator = await self._open_translator()
        translation = await translator.translate(text)
        if not translation or self._matcher is None:
            return translation
        match = self._matcher.match(translation)
        return match.target_text if match is not None else translation


Session = CandidateSession | DirectTranslationSession


@dataclass
class _Screen:
    """What the plate is showing, and which read put it there."""

    seq: int = 0
    text: str = ""
    matched: bool = False
    # Whether the read itself matched, rather than the clock placing the line.
    # A followed line is right about as often as the anchor is, so reads of the
    # same cue keep trying to match until one of them confirms it.
    confirmed: bool = False
    # The last file line a confirmed match covered. A read can match a cue the
    # file splits across two lines, and the clock only ever answers with one of
    # them, so the clock waits until it has moved past the whole match.
    covers_through: int | None = None


async def open_live_translator(config: AppConfig) -> tuple[TranslationClient, LiveTranslator]:
    client = await open_translation_client(config)
    return client, LiveTranslator(client, config.source_language, config.target_language)


async def run_session_loop(
    session: Session,
    config: AppConfig,
    broadcast: Broadcast,
    debug_broadcast: DebugBroadcast | None = None,
    region_source: RegionSource | None = None,
) -> None:
    # Read the region every frame: the live dock can reselect it without stopping.
    read_region = region_source or (lambda: tuple(config.capture_region))
    interval_s = config.capture_interval_ms / 1000
    gate = SubtitleGate()
    screen = _Screen()
    pending: asyncio.Task[None] | None = None
    empty_reads = 0
    iteration = 0

    async def show(text: str, source: str) -> bool:
        if text == screen.text and source == (MATCHED if screen.matched else TRANSLATED):
            return False
        screen.text = text
        screen.matched = source == MATCHED
        await broadcast(text, source)
        return True

    async def publish(text: str, source: str, seq: int) -> None:
        if seq != screen.seq or not text:
            return
        # A matched line is the better answer for this read; a translation that
        # arrives after it is stale by the time it lands.
        if source == TRANSLATED and screen.matched:
            return
        await show(text, source)

    async def render_from_the_clock() -> None:
        """Play the file forward, once a match has said where the video is.

        A read places the video; it is not what draws it. OCR misses lines - a
        frame caught mid-fade, white text over a white background - and drawing
        only what a read returned left those lines blank and every other line a
        beat late.

        Each line is drawn at the timestamp the file gives it rather than on a
        poll, because fast dialogue changes cue faster than any poll worth
        running would notice. `nudge` covers the other half: a read can move the
        anchor at any time, which moves every boundary after it.
        """
        while True:
            waiting = session.seconds_to_next_line()
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    nudge.wait(),
                    timeout=RETIME_CHECK_S if waiting is None else min(waiting, RETIME_CHECK_S),
                )
            nudge.clear()
            if not session.anchored:
                continue
            line = session.line_now()
            if line is None:
                continue
            covered, reached = screen.covers_through, line.covers_through
            if covered is not None and (reached is None or reached <= covered):
                # A read matched this cue outright, which is the better answer
                # for it - and a match can cover a pair of file lines where the
                # clock names only one. The clock takes over past the match, and
                # a gap inside it is the two files breaking their cues
                # differently rather than silence.
                continue
            if await show(line.text, MATCHED):
                # A clock transition lets similar OCR reads confirm the source
                # again: REPEAT alone cannot prove the same dialogue is still up.
                # The sequence also invalidates translations still in flight.
                screen.seq += 1
                screen.confirmed = False
                screen.covers_through = None

    async def translate_into(resolution: Resolution, seq: int) -> None:
        try:
            translated = await session.translate(resolution.translate)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Translating %r failed", resolution.translate[:60])
            return
        await publish(translated, resolution.source, seq)

    def start_translation(resolution: Resolution, seq: int) -> asyncio.Task[None]:
        return asyncio.create_task(translate_into(resolution, seq))

    async def handle(ocr_text: str, fresh: bool) -> dict[str, object]:
        nonlocal pending
        # A read of a cue already on screen may only improve on it by matching
        # outright. Letting the clock answer again would swap the line mid-cue,
        # as soon as the prediction crossed into the next one.
        resolution = await session.match(ocr_text, follow=fresh)
        if resolution is None:
            if not fresh:
                # A read of a cue already on screen only gets a second chance at
                # matching; it is not worth a second trip to the model.
                return {}
            resolution = Resolution(translate=ocr_text)
        if session.independent_target and session.anchored:
            if pending is not None:
                pending.cancel()
                pending = None
            if resolution.detail.get("confirmed"):
                screen.confirmed = True
            # Matching and scheduled rendering resolve the same target intervals,
            # including silence. Source spans cannot hold a target cue on screen.
            screen.covers_through = None
            await show(resolution.text, MATCHED)
            return resolution.detail
        if resolution.text:
            if pending is not None:
                pending.cancel()
                pending = None
            if resolution.detail.get("confirmed"):
                screen.confirmed = True
                screen.covers_through = resolution.covers_through
            await publish(resolution.text, resolution.source, screen.seq)
            return resolution.detail
        if session.anchored and not resolution.matched:
            # The clock is drawing the plate and the file has no line here, so
            # the video is between cues however it looked to OCR. A translation
            # would only be wiped by the next redraw.
            return resolution.detail
        if not fresh and pending is not None and not pending.done():
            return resolution.detail
        if pending is not None:
            pending.cancel()
        pending = start_translation(resolution, screen.seq)
        return resolution.detail

    async def fill_what_the_file_left_unpaired() -> None:
        """Answer the cues the target file has nothing over, ahead of the clock.

        Live reads come first: the viewer is waiting on those and the engine
        answers one request at a time, so a fill only starts when no read is in
        flight. It cannot stand aside for a read that arrives while it is
        already asking, which costs that read the one completion it waits behind.

        Only a session that has a target file has gaps to fill. Without one every
        cue is unanswered, and filling them ahead would spend the single-slot
        engine on the file's opening while the viewer waits on the read in front
        of them - which is the whole of what a live-translation session does.

        A session with several candidates can let one go and lock another, so the
        file being followed is watched rather than taken once: each new one is
        filled in its turn. What is remembered is which files were answered all
        the way through, not which was answered last - a file the session left
        partway and later comes back to still has the rest of its gaps.

        Gaps are answered from wherever the video has reached, wrapping to the
        ones behind it afterwards. A viewer who starts partway into an episode,
        or seeks, would otherwise have the engine spend its pass on cues that
        have already gone by.
        """
        if not isinstance(session, CandidateSession) or not session.has_target_file:
            return
        answered: set[int] = set()
        while True:
            following = session.followed_lines
            track = session.presentation
            if following and track is not None and id(following) not in answered:
                outcome = await fill_gaps(
                    lambda: session.followed_lines,
                    session.translate_from_file,
                    lambda: pending is not None and not pending.done(),
                    redraw,
                    lambda: session.followed_position,
                    answer=track.answer,
                )
                if outcome.completed:
                    answered.add(id(following))
                if outcome.engine_failed:
                    # It will not answer the next file's gaps either, and asking
                    # is what the viewer's own reads are queueing behind.
                    return
                # The lock can have moved while that ran, which is what ended it.
                continue
            await asyncio.sleep(FOLLOW_POLL_S)

    nudge = asyncio.Event()

    async def redraw() -> None:
        nudge.set()

    renderer = asyncio.create_task(render_from_the_clock())
    filler = asyncio.create_task(fill_what_the_file_left_unpaired())
    try:
        while True:
            iteration += 1
            started = monotonic()
            ocr_text = ""
            change: LineChange | None = None
            detail: dict[str, object] = {}
            try:
                image = await asyncio.to_thread(capture_region, read_region())
                ocr_text = await ocr_image(image, config.ocr_language)

                if is_untranslatable(ocr_text):
                    empty_reads += 1
                    # While the clock is running it decides what is on screen.
                    # A read comes back empty often enough - a frame caught
                    # mid-fade, pale text over a pale background - that letting
                    # it blank the plate loses lines that are plainly there.
                    if (
                        empty_reads >= CLEAR_AFTER_EMPTY_READS
                        and screen.text
                        and not session.anchored
                    ):
                        gate.clear()
                        screen.seq += 1
                        screen.text = ""
                        screen.matched = False
                        screen.confirmed = False
                        screen.covers_through = None
                        await broadcast("", MATCHED)
                else:
                    empty_reads = 0
                    change = gate.classify(ocr_text)
                    if change is LineChange.REPEAT:
                        session.saw_same_cue(started)
                        # The same subtitle is read many times over the seconds it
                        # is up, and a read that was too damaged to match can come
                        # back clean. Only worth trying while nothing has matched.
                        if not screen.confirmed:
                            detail = await handle(ocr_text, fresh=False)
                    else:
                        gate.remember(ocr_text)
                        screen.seq += 1
                        if not (session.independent_target and session.anchored):
                            screen.matched = False
                        screen.confirmed = False
                        screen.covers_through = None
                        # Timed from before the capture, not from after the
                        # OCR: the recognising is what puts a read behind the
                        # picture, and the clock should not inherit it.
                        session.saw_new_cue(started)
                        detail = await handle(ocr_text, fresh=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Capture loop #%d failed (ocr=%r)", iteration, ocr_text[:60])

            nudge.set()

            if debug_broadcast is not None:
                await debug_broadcast(
                    {
                        "iteration": iteration,
                        "ocrText": ocr_text[:120],
                        "change": change.value if change else "empty",
                        "displayed": screen.text[:60],
                        "source": MATCHED if screen.matched else TRANSLATED,
                        "elapsedMs": int((monotonic() - started) * 1000),
                        **detail,
                    }
                )
            await asyncio.sleep(max(0.0, interval_s - (monotonic() - started)))
    finally:
        renderer.cancel()
        filler.cancel()
        session.close()
        if pending is not None:
            pending.cancel()
