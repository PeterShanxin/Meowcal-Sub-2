from PIL import Image, ImageChops

from meocosub2.audio_observation import AudioObservation, AudioSession, player_audio
from meocosub2.playback_observation import PlaybackObserver
from meocosub2.timeline import PlaybackState

REGION = (0, 0, 640, 240)


def video_frame():
    pixels = bytes(64 + ((x // 7 + y // 7) % 2) * 48 for y in range(240) for x in range(640))
    return Image.frombytes("L", (640, 240), pixels)


def test_only_selected_process_streams_supply_audio_evidence():
    sessions = [AudioSession(11, 0, 0), AudioSession(12, 1, 0.9)]
    assert player_audio(11, sessions) == AudioObservation(11, False, 0)
    assert player_audio(13, sessions) is None
    assert player_audio(0, sessions) is None


def test_muted_or_silent_running_stream_is_not_a_stop():
    assert player_audio(11, [AudioSession(11, 1, 0)]) == AudioObservation(11, True, 0)
    assert player_audio(11, [AudioSession(11, 1, None)]) == AudioObservation(11, True, None)


def test_expired_or_multi_process_sessions_remain_unknown():
    assert player_audio(11, [AudioSession(11, 2, 0)]) is None
    assert player_audio(11, [AudioSession(11, 1, 0.9, single_process=False)]) is None


def test_any_running_selected_stream_prevents_a_false_stop():
    assert player_audio(11, [AudioSession(11, 0, 0), AudioSession(11, 1, 0.4)]) == AudioObservation(
        11, True, 0.4
    )


def test_static_video_with_associated_running_audio_advances():
    observer = PlaybackObserver()
    frame = video_frame()
    for now in range(4):
        assert (
            observer.observe(frame, REGION, now, AudioObservation(11, True, 0.5), 11)
            is PlaybackState.ADVANCING
        )


def test_stream_stopping_is_ambiguous_and_never_supplies_pause_duration():
    observer = PlaybackObserver()
    frame = video_frame()
    observer.observe(frame, REGION, 0, AudioObservation(11, True, 0.5), 11)
    assert (
        observer.observe(frame, REGION, 0.25, AudioObservation(11, False, 0), 11)
        is PlaybackState.ADVANCING
    )
    assert (
        observer.observe(frame, REGION, 1, AudioObservation(11, False, 0), 11)
        is PlaybackState.UNCERTAIN
    )
    assert (
        observer.observe(frame, REGION, 1.25, AudioObservation(11, True, 0.5), 11)
        is PlaybackState.ADVANCING
    )


def test_absent_or_unattributed_audio_never_turns_stillness_into_stop():
    frame = video_frame()
    for audio in (
        None,
        AudioObservation(12, False, 0),
        AudioObservation(11, False, 0),
        AudioObservation(11, True, 0),
        AudioObservation(11, True, None),
        AudioObservation(11, True, 0.0005),
        AudioObservation(11, True, 0.001),
    ):
        observer = PlaybackObserver()
        for now in range(4):
            assert observer.observe(frame, REGION, now, audio, 11) is PlaybackState.UNCERTAIN


def test_unrelated_audio_cannot_keep_a_paused_player_advancing():
    observer = PlaybackObserver()
    frame = video_frame()
    observer.observe(frame, REGION, 0, AudioObservation(11, True, 0.5), 11)
    for now in (1, 1.25, 1.5):
        assert (
            observer.observe(frame, REGION, now, AudioObservation(12, True, 1), 11)
            is PlaybackState.UNCERTAIN
        )


def test_source_process_change_invalidates_the_position():
    observer = PlaybackObserver()
    frame = video_frame()
    observer.observe(frame, REGION, 0, AudioObservation(11, True, 0.5), 11)
    assert (
        observer.observe(frame, REGION, 1, AudioObservation(12, True, 0.5), 12)
        is PlaybackState.INVALIDATED
    )


def test_silent_motion_overrides_an_inactive_audio_stream():
    observer = PlaybackObserver()
    frame = video_frame()
    observer.observe(frame, REGION, 0, AudioObservation(11, True, 0.5), 11)
    observer.observe(
        ImageChops.offset(frame, 5, 0), REGION, 0.25, AudioObservation(11, False, 0), 11
    )
    assert (
        observer.observe(
            ImageChops.offset(frame, 10, 0), REGION, 0.5, AudioObservation(11, False, 0), 11
        )
        is PlaybackState.ADVANCING
    )
