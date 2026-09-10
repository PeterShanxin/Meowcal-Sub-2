import asyncio
from contextlib import suppress
from unittest.mock import MagicMock

import pytest

from meocosub2.config import AppConfig
from meocosub2.models import SourceSubtitleCandidate, SubtitleLine, SubtitlePair
from meocosub2.sync import CandidateSession, run_session_loop


def cue(index, start, end, text, translated=""):
    return SubtitleLine(index, start, end, text, translated)


async def no_engine():
    raise AssertionError("human target coverage must not request translation")


def candidate(name, source, target):
    return SourceSubtitleCandidate(
        name, name + ".srt", "test", "en", name, SubtitlePair(source, target)
    )


def make_session(source, target, **kwargs):
    return CandidateSession(
        [candidate("a", source, target)], AppConfig(sync_bias_ms=0), no_engine, **kwargs
    )


@pytest.mark.parametrize(
    "position,expected,wait",
    [(500, "first target", 1.5), (2000, "second target", 2.0), (4500, "", None)],
)
def test_target_segmentation_and_scheduler_share_boundaries(monkeypatch, position, expected, wait):
    session = make_session(
        [cue(0, 0, 4000, "source sentence")],
        [cue(10, 0, 2000, "first target"), cue(20, 2000, 4000, "second target")],
    )
    monkeypatch.setattr(session, "clock_ms", lambda position=position: position)
    assert session.line_now().text == expected
    assert session.seconds_to_next_line() == wait
    assert session.followed_lines[0].translated == ""
    if expected:
        assert session.line_now().detail["presentationCues"][0]["index"] == (
            10 if position < 2000 else 20
        )


async def test_immediate_match_uses_current_target_time_including_silence(monkeypatch):
    source = [cue(0, 0, 4000, "A source sentence with two target cues")]
    target = [cue(0, 0, 1800, "first"), cue(1, 2200, 4000, "second")]
    for position, expected in [(2500, "second"), (2000, "")]:
        session = make_session(source, target)
        monkeypatch.setattr(session, "clock_ms", lambda position=position: position)
        matched = await session.match(source[0].text)
        assert matched.detail["confirmed"]
        assert matched.text == session.line_now().text == expected
        assert matched.covers_through is None
        assert matched.translate == ""


async def test_reanchor_and_bias_resolve_in_the_target_coordinate_system(monkeypatch):
    import meocosub2.sync as sync
    import meocosub2.timeline as timeline

    now = 10.0
    monkeypatch.setattr(timeline, "monotonic", lambda: now)
    monkeypatch.setattr(sync, "DISPLAY_LEAD_MS", 0)
    bias = 0
    source = [
        cue(0, 1000, 3000, "A quiet morning in the garden", "Opening target"),
        cue(1, 100000, 101000, "The landing lights are visible"),
        cue(2, 101000, 103000, "Astronauts landed safely", "Ending target"),
    ]
    target = [cue(0, 0, 2000, "Opening target"), cue(1, 100000, 102000, "Ending target")]
    session = make_session(source, target, bias_source=lambda: bias)
    assert (await session.match(source[0].text)).text == "Opening target"
    # Different cues one second apart corroborate the new playback offset.
    session.saw_new_cue(now)
    await session.match(source[1].text)
    now += 1
    session.saw_new_cue(now)
    assert (await session.match(source[2].text)).text == "Ending target"
    bias = -1001
    assert session.line_now().text == ""
    bias = 500
    assert session.line_now().text == "Ending target"


async def test_candidate_switch_uses_its_own_target_mapping(monkeypatch):
    import meocosub2.timeline as timeline

    monkeypatch.setattr(timeline, "monotonic", lambda: 10.0)
    target = [
        cue(i, 1000 + i * 3000, 3000 + i * 3000, text)
        for i, text in enumerate(["shared target", "another target", "final target"])
    ]
    first = candidate(
        "a",
        [
            cue(i, i * 3000, 2000 + i * 3000, f"first candidate source {i}", line.text)
            for i, line in enumerate(target)
        ],
        target,
    )
    second = candidate(
        "b",
        [
            cue(i, 20000 + i * 3000, 22000 + i * 3000, f"second candidate source {i}", line.text)
            for i, line in enumerate(target)
        ],
        target,
    )
    session = CandidateSession([first, second], AppConfig(sync_bias_ms=0), no_engine)
    session._lock("a")
    await session.match(first.pair.source_lines[0].text)
    assert session.line_now().detail["mappingOffsetMs"] == 1000
    session._lock("b")
    await session.match(second.pair.source_lines[0].text)
    assert session.line_now().detail["mappingOffsetMs"] == -19000
    assert session.line_now().text == "shared target"


async def test_two_source_reads_do_not_replace_one_target_plate(monkeypatch):
    import meocosub2.sync as sync

    source = [
        cue(0, 0, 1500, "Opening source sentence"),
        cue(1, 1500, 3000, "Ending source sentence"),
    ]
    session = make_session(source, [cue(10, 0, 3000, "one target cue")])
    reads = iter([line.text for line in source])
    shown = []

    async def ocr(*args):
        try:
            return next(reads)
        except StopIteration:
            raise asyncio.CancelledError from None

    async def broadcast(text, source):
        shown.append(text)

    monkeypatch.setattr(sync, "ocr_image", ocr)
    monkeypatch.setattr(sync, "capture_region", lambda region: MagicMock())
    with pytest.raises(asyncio.CancelledError):
        await run_session_loop(session, AppConfig(capture_interval_ms=0), broadcast)
    assert shown == ["one target cue"]


async def test_all_rapid_targets_play_while_ocr_stalls(monkeypatch):
    import meocosub2.sync as sync

    monkeypatch.setattr(sync, "DISPLAY_LEAD_MS", 0)
    session = make_session(
        [cue(0, 0, 1500, "A single long source sentence")],
        # Shorter than the 200 ms fallback poll, with room for Windows timer jitter.
        [cue(0, 0, 300, "first"), cue(1, 450, 600, "short"), cue(2, 750, 1000, "last")],
    )
    shown = []
    completed = asyncio.Event()
    first = True

    async def ocr(*args):
        nonlocal first
        if first:
            first = False
            return session.followed_lines[0].text
        await asyncio.Event().wait()

    async def broadcast(text, source):
        shown.append(text)
        if "last" in shown and text == "":
            completed.set()

    monkeypatch.setattr(sync, "ocr_image", ocr)
    monkeypatch.setattr(sync, "capture_region", lambda region: MagicMock())
    task = asyncio.create_task(
        run_session_loop(session, AppConfig(capture_interval_ms=0), broadcast)
    )
    try:
        await asyncio.wait_for(completed.wait(), 5)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    assert shown == ["first", "", "short", "", "last", ""]


@pytest.mark.parametrize("overlap", [1, 100, 500])
def test_source_overlap_cannot_add_a_target_cue(monkeypatch, overlap):
    source = [cue(0, 0, 2000 + overlap, "first source"), cue(1, 2000, 4000, "second source")]
    session = make_session(
        source, [cue(0, 0, 2000, "first target"), cue(1, 2000, 4000, "second target")]
    )
    monkeypatch.setattr(session, "clock_ms", lambda: 2000)
    assert session.line_now().text == "second target"
    assert len(session.line_now().detail["presentationCues"]) == 1


def test_speaker_rows_belong_to_one_target_cue(monkeypatch):
    session = make_session([cue(0, 0, 2000, "source")], [cue(7, 0, 2000, "- Hello\n- Goodbye")])
    monkeypatch.setattr(session, "clock_ms", lambda: 1000)
    frame = session.line_now()
    assert frame.text == "- Hello\n- Goodbye"
    assert len(frame.detail["presentationCues"]) == 1
    assert frame.detail["presentationCues"][0]["index"] == 7


async def test_clock_transition_allows_a_similar_ocr_cue_to_confirm_its_source(monkeypatch):
    import meocosub2.sync as sync
    from meocosub2.subtitle_gate import LineChange, SubtitleGate

    source = [cue(0, 0, 90, "The door is open"), cue(1, 120, 1000, "The gate is open")]
    gate = SubtitleGate()
    gate.remember(source[0].text)
    assert gate.classify(source[1].text) is LineChange.REPEAT
    session = make_session(
        source, [cue(0, 0, 90, "first target"), cue(1, 120, 1000, "next target")]
    )
    monkeypatch.setattr(sync, "DISPLAY_LEAD_MS", 0)
    next_plate = asyncio.Event()
    observations = []
    reads = 0

    async def ocr(*args):
        nonlocal reads
        reads += 1
        if reads == 1:
            return source[0].text
        if reads == 2:
            await next_plate.wait()
            return source[1].text
        raise asyncio.CancelledError

    async def broadcast(text, source):
        if text == "next target":
            next_plate.set()

    async def observe(data):
        observations.append(data)

    monkeypatch.setattr(sync, "ocr_image", ocr)
    monkeypatch.setattr(sync, "capture_region", lambda region: MagicMock())
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(
            run_session_loop(session, AppConfig(capture_interval_ms=0), broadcast, observe), 5
        )
    assert [r["matchIdx"] for r in observations if r.get("confirmed")] == [0, 1]


async def test_unchanged_reads_after_target_transition_keep_automatic_candidate(monkeypatch):
    import meocosub2.sync as sync
    import meocosub2.timeline as timeline

    now = 10.0
    monkeypatch.setattr(timeline, "monotonic", lambda: now)
    monkeypatch.setattr(sync, "DISPLAY_LEAD_MS", 0)
    source = [cue(0, 0, 3000, "A single long source sentence")]
    targets = [
        cue(i, i * 1000, (i + 1) * 1000, text)
        for i, text in enumerate(["first target", "second target", "third target"])
    ]
    session = CandidateSession(
        [
            candidate("a", source, targets),
            candidate("b", [cue(0, 0, 3000, "Completely unrelated dialogue")], targets),
        ],
        AppConfig(sync_bias_ms=0),
        no_engine,
    )
    assert (await session.match(source[0].text)).text == "first target"
    now = 11.1
    assert session.line_now().text == "second target"
    for _ in range(4):
        await session.match(source[0].text)
    assert session.status()["lockedCandidateId"] == "a"
    now = 12.1
    assert session.line_now().text == "third target"


async def test_distinct_failed_reads_still_unlock_automatic_candidate():
    source = [cue(0, 0, 3000, "A single long source sentence")]
    target = [cue(0, 0, 3000, "target")]
    session = CandidateSession(
        [
            candidate("a", source, target),
            candidate("b", [cue(0, 0, 3000, "Completely unrelated dialogue")], target),
        ],
        AppConfig(sync_bias_ms=0),
        no_engine,
    )
    await session.match(source[0].text)
    await session.match("zxqv zxqv zxqv")
    for _ in range(4):
        await session.match("zxqv zxqv zxqv")
    assert session.status()["lockedCandidateId"] == "a"
    await session.match("jkpw jkpw jkpw")
    await session.match("bfgm bfgm bfgm")
    assert session.status()["lockedCandidateId"] is None


async def test_automatic_session_plays_later_targets_under_stable_ocr(monkeypatch):
    import meocosub2.sync as sync

    monkeypatch.setattr(sync, "DISPLAY_LEAD_MS", 0)
    source = [cue(0, 0, 1500, "A single long source sentence")]
    targets = [
        cue(i, i * 500, (i + 1) * 500, text)
        for i, text in enumerate(["first target", "second target", "third target"])
    ]
    session = CandidateSession(
        [
            candidate("a", source, targets),
            candidate("b", [cue(0, 0, 1500, "Unrelated candidate dialogue")], targets),
        ],
        AppConfig(sync_bias_ms=0),
        no_engine,
    )
    shown = []
    completed = asyncio.Event()

    async def ocr(*args):
        return source[0].text

    async def broadcast(text, source):
        shown.append(text)
        if text == "third target":
            completed.set()

    monkeypatch.setattr(sync, "ocr_image", ocr)
    monkeypatch.setattr(sync, "capture_region", lambda region: MagicMock())
    task = asyncio.create_task(
        run_session_loop(session, AppConfig(capture_interval_ms=5), broadcast)
    )
    try:
        await asyncio.wait_for(completed.wait(), 5)
        assert session.status()["lockedCandidateId"] == "a"
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    assert shown == ["first target", "second target", "third target"]
