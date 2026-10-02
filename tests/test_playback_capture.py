import asyncio
import threading
from unittest.mock import MagicMock

import pytest
from PIL import Image

import meocosub2.playback_capture as capture
from meocosub2.audio_observation import AudioObservation, AudioSession
from meocosub2.player_window import PlayerWindow
from meocosub2.timeline import PlaybackState


@pytest.mark.asyncio
async def test_one_player_capture_supplies_motion_and_the_unchanged_ocr_rectangle(monkeypatch):
    player = PlayerWindow(11, (-640, 0, 640, 480))
    region = (-600, 400, 400, 60)
    monkeypatch.setattr(capture, "find_player_window", lambda _: player)
    monkeypatch.setattr(capture, "read_audio_sessions", lambda: [AudioSession(11, 1, 0)])
    image = Image.new("RGB", (640, 480), "blue")
    grab = MagicMock(return_value=image)
    observer = MagicMock()
    observer.observe.return_value = PlaybackState.ADVANCING
    frame, state = await capture.PlaybackCapture(observer).capture(grab, region, 0)
    grab.assert_called_once_with(player.region)
    assert frame.size == (400, 60) and frame.getpixel((0, 0)) == (0, 0, 255)
    assert state is PlaybackState.ADVANCING
    assert observer.observe.call_args.args == (
        image,
        player.region,
        0,
        AudioObservation(11, True, 0),
        11,
    )


@pytest.mark.asyncio
async def test_unattributed_capture_keeps_the_selected_rectangle_and_does_not_read_audio(
    monkeypatch,
):
    monkeypatch.setattr(capture, "find_player_window", lambda _: None)
    reader = MagicMock(side_effect=AssertionError("must not read system audio"))
    monkeypatch.setattr(capture, "read_audio_sessions", reader)
    image = Image.new("RGB", (400, 60))
    grab, observer = MagicMock(return_value=image), MagicMock()
    region = (0, 0, 400, 60)
    frame, _ = await capture.PlaybackCapture(observer).capture(grab, region, 0)
    assert frame is image
    grab.assert_called_once_with(region)
    assert observer.observe.call_args.args[3:] == (None, None)
    reader.assert_not_called()


@pytest.mark.asyncio
async def test_audio_cache_is_bounded_and_cannot_follow_an_old_player(monkeypatch):
    now = 0.0
    player = PlayerWindow(11, (0, 0, 640, 480))
    monkeypatch.setattr(capture, "monotonic", lambda: now)
    monkeypatch.setattr(capture, "find_player_window", lambda _: player)
    reader = MagicMock(return_value=[AudioSession(11, 1, 0.5)])
    monkeypatch.setattr(capture, "read_audio_sessions", reader)
    observer = MagicMock()
    probe = capture.PlaybackCapture(observer)

    def grab(_):
        return Image.new("RGB", (640, 480))

    await probe.capture(grab, player.region, now)
    now = 0.1
    await probe.capture(grab, player.region, now)
    assert reader.call_count == 1
    player = PlayerWindow(12, player.region)
    await probe.capture(grab, player.region, now)
    assert reader.call_count == 2
    assert observer.observe.call_args.args[3:] == (None, 12)
    now = 0.6
    reader.return_value = None
    await probe.capture(grab, player.region, now)
    assert observer.observe.call_args.args[3] is None


@pytest.mark.asyncio
async def test_audio_timeout_is_unknown_and_does_not_accumulate_reader_workers(monkeypatch):
    release, finished = threading.Event(), threading.Event()
    count = 0
    now = 0.0

    def read():
        nonlocal count
        count += 1
        release.wait(timeout=1)
        finished.set()
        return []

    player = PlayerWindow(11, (0, 0, 640, 480))
    monkeypatch.setattr(capture, "AUDIO_TIMEOUT_S", 0.01)
    monkeypatch.setattr(capture, "monotonic", lambda: now)
    monkeypatch.setattr(capture, "find_player_window", lambda _: player)
    monkeypatch.setattr(capture, "read_audio_sessions", read)
    observer = MagicMock()
    probe = capture.PlaybackCapture(observer)
    try:
        for now in (0.0, 0.6, 1.2):
            await probe.capture(lambda _: Image.new("RGB", (640, 480)), player.region, now)
            assert observer.observe.call_args.args[3] is None
        assert count == 1
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 1)


@pytest.mark.asyncio
async def test_failed_capture_resets_observation_and_reports_capture_failure(monkeypatch):
    monkeypatch.setattr(capture, "find_player_window", lambda _: None)
    observer = MagicMock()
    probe = capture.PlaybackCapture(observer)
    grab = MagicMock(side_effect=OSError("display lost"))
    with pytest.raises(capture.PlaybackCaptureError):
        await probe.capture(grab, (0, 0, 640, 480), 0)
    observer.reset.assert_called_once()
