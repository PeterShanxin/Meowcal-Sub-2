"""Observed player pauses preserve the existing human-target clock."""

import asyncio

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
    assert observe(30, 15) is PlaybackState.UNCERTAIN
    assert session.clock_ms() == 600750
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


def test_two_second_freeze_boundary_with_decimal_capture_timestamps():
    observer = PlaybackObserver()
    # Same observation times as the existing authored FFplay pause recording.
    # Subtracting 3.6 from 5.6 loses one floating-point ulp below two seconds.
    for at in (3.2, 3.6, 4.0, 4.4, 4.8, 5.2):
        assert observer.observe(frame(), REGION, at) is PlaybackState.UNCERTAIN
    assert observer.observe(frame(), REGION, 5.6) is PlaybackState.STOPPED
    assert observer.state_since == 3.6


def test_confirming_a_new_ocr_line_does_not_postpone_the_observed_image_freeze():
    observer = PlaybackObserver()
    for at, offset in ((0, 0), (0.25, 5), (0.5, 10)):
        observer.observe(frame(offset), REGION, at)
        observer.observe_text("Previous source line", at)
    for at in (0.75, 1, 1.25, 1.5, 1.75, 2, 2.25, 2.5):
        observer.observe(frame(10), REGION, at)
        assert (
            observer.observe_text("Newly recognized paused line", at) is not PlaybackState.STOPPED
        )
    observer.observe(frame(10), REGION, 2.75)
    assert observer.observe_text("Newly recognized paused line", 2.75) is PlaybackState.STOPPED
    assert observer.state_since == 0.75


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


@pytest.mark.parametrize("interval", [1.6, 4.0])
def test_sparse_freeze_samples_keep_the_anchor_until_confirmation(interval):
    timeline = PlaybackTimeline()
    observer = PlaybackObserver()
    for at, offset in ((0, 0), (0.25, 5), (0.5, 10)):
        state = observer.observe(frame(offset), REGION, at)
    assert state is PlaybackState.ADVANCING
    assert timeline.accepts(600000, 0, 100, now=0.5)
    timeline.observe_playback(state, 0.5, observer.state_since)
    for sample in range(1, 4):
        at = 0.5 + sample * interval
        state = observer.observe(frame(10), REGION, at)
        timeline.observe_playback(state, at, observer.state_since)
        # The independent renderer keeps reading between sparse OCR captures.
        for tick in range(int(interval * 4)):
            assert timeline.position_ms(at + tick * 0.25) is not None
    assert state is PlaybackState.STOPPED
    assert timeline.position_ms(at) == 600000 + int(interval * 1000)


def test_pending_freeze_lease_expires_when_capture_does_not_return():
    timeline = PlaybackTimeline()
    observer = PlaybackObserver()
    for at, offset in ((0, 0), (0.25, 5), (0.5, 10)):
        state = observer.observe(frame(offset), REGION, at)
    assert timeline.accepts(600000, 0, 100, now=0.5)
    timeline.observe_playback(state, 0.5, observer.state_since)
    state = observer.observe(frame(10), REGION, 4.5)
    assert state is PlaybackState.UNCERTAIN
    timeline.observe_playback(state, 4.5, observer.state_since)
    assert timeline.position_ms(9.5) is not None
    assert timeline.position_ms(9.501) is None
    state = observer.observe(frame(10), REGION, 9.75)
    timeline.observe_playback(state, 9.75, observer.state_since)
    assert timeline.position_ms(9.75) is None


def test_unreliable_frame_withdraws_the_pending_freeze_lease():
    timeline = PlaybackTimeline()
    observer = PlaybackObserver()
    for at, offset in ((0, 0), (0.25, 5), (0.5, 10)):
        state = observer.observe(frame(offset), REGION, at)
    assert timeline.accepts(600000, 0, 100, now=0.5)
    timeline.observe_playback(state, 0.5, observer.state_since)
    state = observer.observe(frame(10), REGION, 4.5)
    timeline.observe_playback(state, 4.5, observer.state_since)
    black = Image.new("L", (640, 240))
    state = observer.observe(black, REGION, 7.5)
    assert observer.state_since is None
    timeline.observe_playback(state, 7.5, observer.state_since)
    assert timeline.position_ms(7.75) is None


def test_muted_hard_cuts_cannot_leave_a_latched_stop_supported_forever():
    timeline = PlaybackTimeline()
    assert timeline.accepts(600000, 0, 100, now=0)
    observer = stopped_observer()
    timeline.observe_playback(PlaybackState.STOPPED, 2.25, observer.state_since)
    cut = ImageChops.invert(frame())
    states = []
    for index in range(16):
        at = 2.5 + index * 0.25
        state = observer.observe(cut if index % 2 == 0 else frame(), REGION, at, source_id=11)
        timeline.observe_playback(state, at, observer.state_since)
        states.append(state)
    assert PlaybackState.ADVANCING not in states
    assert PlaybackState.INVALIDATED in states
    assert timeline.position_ms(at) is None


def test_confirmed_stop_expires_when_no_more_capture_is_delivered():
    timeline = PlaybackTimeline()
    assert timeline.accepts(600000, 0, 100, now=0)
    observer = stopped_observer()
    timeline.observe_playback(PlaybackState.STOPPED, 2.25, observer.state_since)
    assert timeline.position_ms(7.25) == 600250
    assert timeline.position_ms(7.251) is None


@pytest.mark.parametrize("previous", [PlaybackState.UNCERTAIN, PlaybackState.STOPPED])
async def test_boundary_capture_delivery_preserves_pending_or_confirmed_stop(previous):
    timeline = PlaybackTimeline()
    assert timeline.accepts(600000, 0, 100, now=0)
    timeline.observe_playback(previous, 0, state_since=0, received_at=0.25)
    timeline.begin_capture(5.0)
    ready = asyncio.Event()

    async def deliver_frame():
        await ready.wait()
        timeline.observe_playback(PlaybackState.STOPPED, 5.0, state_since=0, received_at=5.5)

    delivery = asyncio.create_task(deliver_frame())
    try:
        await asyncio.sleep(0)
        assert not delivery.done()
        # Renderer runs after the old lease but before screenshot/audio delivery.
        assert timeline.position_ms(5.5) is not None
        ready.set()
        await asyncio.wait_for(delivery, 1)
        assert timeline.position_ms(5.5) == 600000
        assert timeline.position_ms(10.5) == 600000
        assert timeline.position_ms(10.501) is None
    finally:
        delivery.cancel()


@pytest.mark.parametrize("previous", [PlaybackState.UNCERTAIN, PlaybackState.STOPPED])
def test_inflight_capture_margin_is_bounded_when_delivery_never_finishes(previous):
    timeline = PlaybackTimeline()
    assert timeline.accepts(600000, 0, 100, now=0)
    timeline.observe_playback(previous, 0, state_since=0, received_at=0.25)
    timeline.begin_capture(5.0)
    assert timeline.position_ms(6.0) is not None
    assert timeline.position_ms(6.001) is None
    timeline.begin_capture(6.1)
    timeline.observe_playback(PlaybackState.STOPPED, 6.1, state_since=0, received_at=6.2)
    assert timeline.position_ms(6.2) is None


def test_late_capture_start_cannot_extend_an_already_expired_stop():
    timeline = PlaybackTimeline()
    assert timeline.accepts(600000, 0, 100, now=0)
    timeline.observe_playback(PlaybackState.STOPPED, 0, state_since=0)
    timeline.begin_capture(5.001)
    timeline.observe_playback(PlaybackState.STOPPED, 5.001, state_since=0, received_at=5.25)
    assert timeline.position_ms(5.25) is None


def test_ocr_reanchor_does_not_renew_old_capture_freshness():
    timeline = PlaybackTimeline()
    assert timeline.accepts(600000, 0, 100, now=0)
    timeline.observe_playback(PlaybackState.STOPPED, 0, state_since=0, received_at=0.25)
    assert timeline.accepts(600000, 0, 100, now=4, seen_at=0.25)
    assert timeline.position_ms(5.25) == 600000
    assert timeline.position_ms(5.251) is None
