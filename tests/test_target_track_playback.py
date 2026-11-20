import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, MagicMock

import pytest

import meocosub2.sync as sync
import meocosub2.timeline as timeline
from meocosub2.config import AppConfig
from meocosub2.models import SourceSubtitleCandidate, SubtitleLine, SubtitlePair
from meocosub2.sync import CandidateSession, DirectTranslationSession, run_session_loop
from meocosub2.timeline import PlaybackState


def session_for(path, rows):
    source = [
        SubtitleLine(i, start, end, raw) for i, (start, end, raw, _) in enumerate(rows) if raw
    ]
    target = [SubtitleLine(i, start, end, text) for i, (start, end, _, text) in enumerate(rows)]
    lookup = {raw: text for _, _, raw, text in rows if raw}
    translator = AsyncMock()
    translator.translate.side_effect = lookup.__getitem__
    open_translator = AsyncMock(return_value=translator)
    config = AppConfig(capture_interval_ms=0, sync_bias_ms=0)
    if path == 2:
        return DirectTranslationSession(target, config, open_translator), config
    pair = SubtitlePair(source, target)
    candidate = SourceSubtitleCandidate("test", "test.srt", "fixture", "en", "", pair)
    return CandidateSession([candidate], config, open_translator), config


@pytest.mark.parametrize("path", [1, 2])
async def test_both_file_paths_follow_the_same_pause_overlap_and_backward_seek(monkeypatch, path):
    rows = [
        (5000, 6500, "Close the windows.", "关上窗户。"),
        (7000, 8000, "Call the driver.", "打电话给司机。"),
        (30000, 31500, "Leave the station.", "离开车站。"),
        (32000, 34000, "Turn left.", "向左转。"),
        (33000, 34500, "", "北门"),
        (38000, 39000, "", "出口"),
    ]
    session, _ = session_for(path, rows)
    now = 10.0
    monkeypatch.setattr(timeline, "monotonic", lambda: now)
    monkeypatch.setattr(sync, "DISPLAY_LEAD_MS", 0)

    async def read(row):
        session.observe_playback(PlaybackState.ADVANCING, now)
        session.saw_new_cue(now)
        if path == 1:
            await session.match(rows[row][2])
        else:
            session.target.submit(rows[row][2], session.translate_read, asyncio.Event())
            await session.target.worker

    await read(2)
    if path == 2:
        assert not session.anchored
    now += 2
    await read(3)
    assert session.anchored
    assert session.seconds_to_next_line() == 1.0
    now += 1.1
    session.observe_playback(PlaybackState.ADVANCING, now)
    frame = session.line_now()
    assert [cue["index"] for cue in frame.detail["presentationCues"]] == [3, 4]
    assert frame.detail["mappingOffsetMs"] == 0
    now += 2
    session.observe_playback(PlaybackState.STOPPED, now)
    assert session.line_now().text == ""
    for _ in range(6):
        now += 1
        session.observe_playback(PlaybackState.STOPPED, now)
        assert session.line_now().text == ""
    session.observe_playback(PlaybackState.ADVANCING, now)
    now += 3
    session.observe_playback(PlaybackState.ADVANCING, now)
    assert session.line_now().text == "出口"
    now += 1
    await read(0)
    assert not session.anchored
    now += 2
    await read(1)
    assert session.line_now().text == "打电话给司机。"
    now += 1
    session.observe_playback(PlaybackState.INVALIDATED, now)
    assert session.line_now() is None


@pytest.mark.parametrize("path", [1, 2])
async def test_live_strip_shows_a_target_only_line_without_another_read(monkeypatch, path):
    rows = [
        (0, 250, "Late train.", "火车晚点了。"),
        (300, 600, "Mind the platform.", "请注意站台。"),
        (750, 900, "", "出口"),
    ]
    session, config = session_for(path, rows)
    config.capture_interval_ms = 100
    monkeypatch.setattr(sync, "DISPLAY_LEAD_MS", 0)
    first = asyncio.Event()
    done = asyncio.Event()
    calls = 0

    async def read(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls <= 2:
            return rows[0][2]
        if calls <= 4:
            await first.wait()
            return rows[1][2]
        await asyncio.Event().wait()

    strip = []

    async def show(text, kind):
        strip.append((text, kind))
        if text == rows[0][3]:
            first.set()
        if text == rows[2][3]:
            done.set()

    capture = MagicMock()
    capture.capture = AsyncMock(return_value=(object(), PlaybackState.ADVANCING))
    capture.observe_text.side_effect = lambda text, at, state: state
    capture.state_since = None
    monkeypatch.setattr(sync, "PlaybackCapture", lambda _: capture)
    monkeypatch.setattr(sync, "ocr_image", read)
    monkeypatch.setattr(sync, "capture_region", lambda _: MagicMock())
    task = asyncio.create_task(run_session_loop(session, config, show))
    try:
        try:
            await asyncio.wait_for(done.wait(), 3)
        except TimeoutError:
            pytest.fail(f"Only {strip!r} after {calls} captures")
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    assert ("出口", "matched") in strip
    assert ("请注意站台。", "matched") in strip


async def test_old_answer_cannot_restore_timing_after_capture_loss():
    rows = [(0, 1000, "Old source.", "旧的画面。")]
    session, _ = session_for(2, rows)
    target = session.target
    session.saw_new_cue(10)
    started, resume = asyncio.Event(), asyncio.Event()

    async def delayed(_):
        started.set()
        await resume.wait()
        return rows[0][3]

    target.submit("Old source.", delayed, asyncio.Event())
    await started.wait()
    session.observe_playback(PlaybackState.INVALIDATED, 11)
    resume.set()
    await target.worker
    assert not session.anchored
    assert target.live_text == ""


def test_repeated_wording_cannot_confirm_a_scene(monkeypatch):
    now = 10.0
    monkeypatch.setattr(timeline, "monotonic", lambda: now)
    rows = [
        (1000, 2000, "Hello there.", "你好呀。"),
        (4000, 5000, "Thank you.", "非常感谢。"),
        (20000, 21000, "Many thanks.", "非常 感谢。"),
    ]
    session, _ = session_for(2, rows)
    target = session.target
    for row in (0, 1, 2, 1):
        target.new_cue(now)
        assert target.answer(rows[row][3], now, True) in {rows[row][3], "非常感谢。", "非常 感谢。"}
        assert not session.anchored
        now += 3


async def test_short_captions_keep_showing_live_answers_until_a_current_read_can_place_time():
    rows = [
        (i * 2000, i * 2000 + 1500, raw, text)
        for i, (raw, text) in enumerate(
            [
                ("First line.", "火车晚点了。"),
                ("Second line.", "从北门出去。"),
                ("Third line.", "向左转弯。"),
                ("Fourth line.", "请留在这里。"),
                ("Fifth line.", "明天会下雨。"),
            ]
        )
    ]
    session, _ = session_for(2, rows)
    target = session.target
    results = [asyncio.Event() for _ in rows]
    started = [asyncio.Event() for _ in rows]
    shown = []

    class Wake:
        def set(self):
            shown.append(target.live_text)

    async def slow(text):
        row = next(i for i, data in enumerate(rows) if data[2] == text)
        started[row].set()
        await results[row].wait()
        return rows[row][3]

    def capture(i):
        session.saw_new_cue(i * 2.0)
        target.submit(rows[i][2], slow, Wake())

    capture(0)
    await started[0].wait()
    capture(1)
    capture(2)
    results[0].set()
    await started[2].wait()
    capture(3)
    capture(4)
    results[2].set()
    await started[4].wait()
    results[4].set()
    await target.worker
    assert shown == [rows[0][3], rows[2][3], rows[4][3]]
    assert not session.anchored


async def test_same_caption_can_be_translated_again_after_capture_fails(monkeypatch):
    from meocosub2.playback_capture import PlaybackCaptureError

    rows = [(3000, 4800, "The door is open.", "门开着。")]
    session, config = session_for(2, rows)
    opened = asyncio.Event()
    twice = asyncio.Event()
    seen = []

    async def translate(text):
        seen.append(text)
        (opened if len(seen) == 1 else twice).set()
        return rows[0][3]

    frames = 0

    async def next_frame(grab, region, at):
        nonlocal frames
        frames += 1
        if frames == 3:
            await opened.wait()
            raise PlaybackCaptureError("test capture unavailable")
        if frames == 6:
            await twice.wait()
            raise asyncio.CancelledError
        return object(), PlaybackState.ADVANCING

    capture = MagicMock()
    capture.state_since = None
    capture.capture = next_frame
    capture.observe_text.side_effect = lambda text, at, state: state
    monkeypatch.setattr(sync, "PlaybackCapture", lambda _: capture)
    monkeypatch.setattr(sync, "ocr_image", AsyncMock(return_value=rows[0][2]))
    monkeypatch.setattr(session, "translate_read", translate)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(run_session_loop(session, config, AsyncMock()), 3)
    assert seen == [rows[0][2], rows[0][2]]


@pytest.mark.parametrize("stable_after_resume", [False, True])
def test_a_delayed_match_keeps_the_pause_since_the_caption_first_appeared(
    monkeypatch, stable_after_resume
):
    now = 10.0
    monkeypatch.setattr(timeline, "monotonic", lambda: now)
    rows = [
        (1000, 2400, "Train is late.", "火车晚点。"),
        (3000, 7000, "Close the window.", "关上\n窗户。"),
        (8000, 9000, "", "出口"),
    ]
    session, _ = session_for(2, rows)
    target = session.target
    target.new_cue(now)
    target.answer("火车晚点。", now, True)
    if not stable_after_resume:
        target.new_cue(12.0)
    now = 13.0
    session.observe_playback(PlaybackState.STOPPED, now)
    now = 16.0
    session.observe_playback(PlaybackState.ADVANCING, now)
    if stable_after_resume:
        target.new_cue(12.0)
    now = 17.0
    target.answer("关上窗户。", 12.0, True)
    assert target.timeline.position_ms() == 5000
    assert session.line_now().text == "关上窗户。"
    now = 18.0
    session.observe_playback(PlaybackState.ADVANCING, now)
    assert target.timeline.position_ms() == 6000
