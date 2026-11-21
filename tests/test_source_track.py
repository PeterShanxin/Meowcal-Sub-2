import asyncio
from unittest.mock import AsyncMock

import pytest

from meocosub2.models import SubtitleLine, SubtitlePair
from meocosub2.source_track import SourceTrackTranslation
from meocosub2.sync import CandidateSession
from meocosub2.timeline import PlaybackState
from tests.test_sync import config, make_candidate, never_translates


def source(count):
    return [SubtitleLine(i, i * 1000, i * 1000 + 800, f"cue {i}") for i in range(count)]


async def updated():
    return None


async def test_full_source_uses_neighbor_answers_and_keeps_its_own_cue_times():
    lines = source(130)
    lines[1].start_ms = 700
    track = SourceTrackTranslation(lines)
    translate = AsyncMock(side_effect=lambda text, pairs: f"answer {text}")
    outcome = await track.fill(translate, lambda: False, updated, lambda: 0, lambda: True)

    assert outcome.completed and outcome.filled == 130
    assert translate.await_args_list[1].args == ("cue 1", [("cue 0", "answer cue 0")])
    target = track.presentation
    assert target is not None and target.offset_ms == 0
    assert [(row.index, row.start_ms, row.end_ms) for row in target.target_lines] == [
        (row.index, row.start_ms, row.end_ms) for row in lines
    ]
    assert target.resolve_at(700).text == "answer cue 0\nanswer cue 1"
    assert [cue.kind for cue in target.resolve_at(700).cues] == ["model", "model"]
    assert target.resolve_at(1800).text == ""
    assert [row.text for row in lines] == [f"cue {i}" for i in range(130)]


async def test_a_missing_answer_keeps_live_mode_until_that_cue_succeeds():
    pair = SubtitlePair(source(3))
    gen = pair.source_translation
    assert gen is not None
    translate = AsyncMock(side_effect=["A", "", "C"])
    outcome = await gen.fill(translate, lambda: False, updated, lambda: None, lambda: True)
    assert not outcome.completed and gen.presentation is None
    assert [row.translated for row in pair.source_lines] == ["A", "", "C"]
    live = AsyncMock(return_value="B")
    assert await gen.translate_cue(1, live) == "B"
    live.assert_awaited_once()
    assert gen.presentation.resolve_at(1100).text == "B"


async def test_prefill_cancel_then_seek_resumes_from_new_position():
    track = SourceTrackTranslation(source(5))
    started = asyncio.Event()

    async def slow(text, pairs):
        if text == "cue 0":
            return "zero"
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(track.fill(slow, lambda: False, updated, lambda: 0, lambda: True))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [row.translated for row in track.lines] == ["zero", "", "", "", ""]
    position = 3

    async def translate(text, pairs):
        nonlocal position
        position = 1
        return text.upper()

    translate = AsyncMock(side_effect=translate)
    await track.fill(translate, lambda: False, updated, lambda: position, lambda: True)
    assert [call.args[0] for call in translate.await_args_list] == [
        "cue 3",
        "cue 1",
        "cue 2",
        "cue 4",
    ]


async def test_live_read_joins_background_work_and_a_cancelled_waiter_does_not_cancel_the_file():
    track = SourceTrackTranslation(source(2))
    entered, finish = asyncio.Event(), asyncio.Event()

    async def slow(text, pairs):
        entered.set()
        await finish.wait()
        return "answer"

    owner = asyncio.create_task(track.translate_cue(1, slow))
    await asyncio.wait_for(entered.wait(), 1)
    unused = AsyncMock()
    previous = asyncio.create_task(track.translate_cue(1, unused))
    current = asyncio.create_task(track.translate_cue(1, unused))
    await asyncio.sleep(0)
    previous.cancel()
    with pytest.raises(asyncio.CancelledError):
        await previous
    finish.set()
    assert await owner == await current == "answer"
    unused.assert_not_awaited()


@pytest.mark.parametrize(("position", "expected"), [(1800, ""), (1100, "translated cue 1")])
async def test_handoff_uses_current_clock_including_paused_silence(monkeypatch, position, expected):
    candidate = make_candidate("file", source(3))
    session = CandidateSession([candidate], config(), never_translates())
    gen = candidate.pair.source_translation
    assert gen is not None
    now = 0.0
    monkeypatch.setattr("meocosub2.timeline.monotonic", lambda: now)
    monkeypatch.setattr("meocosub2.sync.DISPLAY_LEAD_MS", 0)
    await session.match(candidate.pair.source_lines[0].text)
    session.observe_playback(PlaybackState.ADVANCING, now)
    now = position / 1000 + 2
    session.observe_playback(PlaybackState.STOPPED, now, position / 1000)
    assert session.clock_ms() == position
    await gen.fill(
        AsyncMock(side_effect=lambda text, pairs: "translated " + text),
        lambda: False,
        updated,
        lambda: 1,
        lambda: True,
    )
    assert session.independent_target
    assert session.line_now().text == expected
    assert session.line_now().detail["presentationClockMs"] == position
    restarted = CandidateSession([candidate], config(), never_translates())
    assert restarted.line_now(position).text == expected


async def test_engine_error_leaves_remaining_dialogue_available_to_live_translation():
    gen = SourceTrackTranslation(source(2))
    outcome = await gen.fill(
        AsyncMock(side_effect=RuntimeError("offline")),
        lambda: False,
        updated,
        lambda: None,
        lambda: True,
    )
    assert outcome.engine_failed and gen.presentation is None
    assert await gen.translate_cue(1, AsyncMock(return_value="recovered")) == "recovered"
    assert gen.presentation is None
