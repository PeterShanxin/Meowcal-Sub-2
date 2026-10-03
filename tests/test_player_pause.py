"""Observed player pauses preserve the existing human-target clock."""

import pytest
from PIL import Image, ImageChops

from meocosub2.audio_observation import AudioObservation
from meocosub2.config import AppConfig
from meocosub2.models import SourceSubtitleCandidate, SubtitleLine, SubtitlePair
from meocosub2.playback_capture import PlaybackCapture
from meocosub2.playback_observation import PlaybackObserver
from meocosub2.sync import CandidateSession
from meocosub2.timeline import PlaybackState, PlaybackTimeline

REGION = (0, 0, 640, 240)


def frame(offset=0):
    pixels = bytes(64 + ((x // 7 + y // 7) % 2) * 48 for y in range(240) for x in range(640))
    return ImageChops.offset(Image.frombytes("L", (640, 240), pixels), offset, 0)


async def no_engine():
    raise AssertionError("a paused human target must not open translation")


@pytest.mark.parametrize("target_start,expected", [(600000, "Human target"), (601000, "")])
async def test_frozen_player_holds_target_or_blank_and_resumes_at_observed_transition(
    monkeypatch, target_start, expected
):
    import meocosub2.sync as sync
    import meocosub2.timeline as timeline

    now = 0.0
    monkeypatch.setattr(timeline, "monotonic", lambda: now)
    monkeypatch.setattr(sync, "DISPLAY_LEAD_MS", 0)
    source = [SubtitleLine(0, 600000, 610000, "The source dialogue before the pause")]
    target = [SubtitleLine(0, target_start, 602000, "Human target")]
    session = CandidateSession(
        [SourceSubtitleCandidate("a", "a.srt", "test", "en", "a", SubtitlePair(source, target))],
        AppConfig(sync_bias_ms=0),
        no_engine,
    )
    await session.match(source[0].text)
    observer = PlaybackObserver()
    capture = PlaybackCapture(observer)

    def observe(at, offset=10):
        nonlocal now
        now = at
        state = observer.observe(frame(offset), REGION, now)
        state = capture.observe_text(source[0].text, now, state)
        session.observe_playback(state, now, capture.state_since)
        return state

    for now, offset in ((0, 0), (0.25, 5), (0.5, 10)):
        state = observer.observe(frame(offset), REGION, now)
        session.observe_playback(state, now)
    # The first unchanged sample is at .75; two-second confirmation is at 2.75.
    for now in (0.75, 1, 1.25, 1.5, 1.75, 2, 2.25, 2.5):
        assert observe(now) is not PlaybackState.STOPPED
    state = observe(2.75)
    assert state is PlaybackState.STOPPED
    for at in (4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 29.75):
        assert observe(at) is PlaybackState.STOPPED
        assert session.clock_ms() == 600750
        assert session.line_now().text == expected
    # Resume needs two distributed changes, but credits the first at 30.0.
    assert observe(30, 15) is PlaybackState.STOPPED
    assert observe(30.25, 20) is PlaybackState.ADVANCING
    assert session.clock_ms() == 601000
    assert session.line_now().text == "Human target"
    assert observe(30.5, 25) is PlaybackState.ADVANCING
    assert session.clock_ms() == 601250


def test_stop_and_resume_confirmation_do_not_accumulate_clock_drift():
    timeline = PlaybackTimeline()
    assert timeline.accepts(600000, 0, 100, now=0)
    observer = PlaybackObserver()
    at = 0.0
    offset = 0
    for _ in range(5):
        for delta in (0, 0.25, 0.5):
            offset += 5
            state = observer.observe(frame(offset), REGION, at + delta)
            timeline.observe_playback(state, at + delta, observer.state_since)
        for delta in (0.75, 1, 1.25, 1.5, 1.75, 2, 2.25, 2.5, 2.75, 3, 4):
            state = observer.observe(frame(offset), REGION, at + delta)
            if delta == 2.75:
                assert state is PlaybackState.STOPPED
            timeline.observe_playback(state, at + delta, observer.state_since)
        at += 4.25
    assert timeline.position_ms(at - 0.25) == 603750


def stopped_observer():
    observer = PlaybackObserver()
    for at in (0, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.25):
        state = observer.observe(frame(), REGION, at, source_id=11)
    assert state is PlaybackState.STOPPED
    return observer


def test_unrelated_sound_or_changing_text_cannot_resume_a_confirmed_pause():
    observer = stopped_observer()
    background = AudioObservation(0, True, 0.8, attributed=False)
    for at, text in ((2.5, "Before"), (2.75, "Before"), (3, "After"), (3.25, "After")):
        assert observer.observe(frame(), REGION, at, background, 11) is PlaybackState.STOPPED
        assert observer.observe_text(text, at) is PlaybackState.STOPPED
        assert observer.state_since == 0.25


def test_attributed_sound_resumes_and_its_end_starts_a_new_freeze_interval():
    observer = stopped_observer()
    audible = AudioObservation(11, True, 0.2)
    for at in (2.5, 3, 4, 5, 6, 7, 8, 9, 10):
        assert observer.observe(frame(), REGION, at, audible, 11) is PlaybackState.ADVANCING
    for at in (10.25, 10.5, 11, 11.5, 12):
        assert observer.observe(frame(), REGION, at, None, 11) is not PlaybackState.STOPPED
    assert observer.observe(frame(), REGION, 12.25, None, 11) is PlaybackState.STOPPED
    assert observer.state_since == 10.25


@pytest.mark.parametrize("loss", ["black", "size", "region", "player", "outage"])
def test_capture_or_source_loss_invalidates_a_confirmed_pause(loss):
    observer = stopped_observer()
    image, region, at, source = frame(), REGION, 2.5, 11
    if loss == "black":
        image = Image.new("L", (640, 240))
    elif loss == "size":
        image = image.crop((0, 0, 640, 80))
        region = (0, 0, 640, 80)
    elif loss == "region":
        region = (10, 0, 640, 240)
    elif loss == "player":
        source = 12
    elif loss == "outage":
        at = 10
    assert observer.observe(image, region, at, source_id=source) is PlaybackState.INVALIDATED
    assert observer.state_since is None
    assert observer.observe(frame(), REGION, at + 0.25, source_id=source) is PlaybackState.UNCERTAIN


def test_silent_motion_and_brief_stillness_never_latch_pause():
    observer = PlaybackObserver()
    silent = AudioObservation(11, True, 0)
    for index in range(24):
        state = observer.observe(frame(index * 5), REGION, index * 0.25, silent, 11)
        assert state is not PlaybackState.STOPPED
    for at in (6, 6.5, 7, 7.5, 7.99):
        assert observer.observe(frame(115), REGION, at, silent, 11) is not PlaybackState.STOPPED
    assert observer.observe(frame(120), REGION, 8, silent, 11) is not PlaybackState.STOPPED
    assert observer.observe(frame(125), REGION, 8.25, silent, 11) is PlaybackState.ADVANCING


def test_seek_while_paused_reanchors_and_keeps_the_new_position():
    timeline = PlaybackTimeline()
    assert timeline.accepts(600000, 0, 100, now=0)
    observer = stopped_observer()
    timeline.observe_playback(PlaybackState.STOPPED, 2.25, observer.state_since)
    timeline.saw_new_cue(3)
    assert not timeline.accepts(1200000, 400, 100, now=3)
    timeline.saw_new_cue(4)
    assert timeline.accepts(1201000, 401, 100, now=4)
    for at in (4.25, 5, 6, 7):
        state = observer.observe(frame(), REGION, at, source_id=11)
        timeline.observe_playback(state, at, observer.state_since)
        assert timeline.position_ms(at) == 1201000
    observer.observe(frame(5), REGION, 7.25, source_id=11)
    state = observer.observe(frame(10), REGION, 7.5, source_id=11)
    timeline.observe_playback(state, 7.5, observer.state_since)
    assert timeline.position_ms(7.5) == 1201250
