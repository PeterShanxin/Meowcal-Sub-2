from meocosub2.audio_observation import AudioObservation
from meocosub2.playing_confidence import PlayingConfidence
from meocosub2.timeline import PlaybackState


def read(probe, at, *, motion=False, still=False, text="Hello", audio=None):
    probe.observe(motion, still, audio, at)
    return probe.observe_text(text, at)


def test_repeated_ocr_does_not_hide_silent_image_motion():
    probe = PlayingConfidence()
    for at in (0, 0.4, 0.8, 1.2, 1.6):
        assert read(probe, at, motion=True) is PlaybackState.ADVANCING


def test_brief_motion_loss_is_uncertain_then_sustained_freeze_stops():
    probe = PlayingConfidence()
    read(probe, 0, motion=True)
    read(probe, 0.4, motion=True)
    states = [read(probe, at, still=True) for at in (0.8, 1.2, 1.6, 2.0)]
    assert PlaybackState.INVALIDATED not in states
    assert PlaybackState.STOPPED not in states
    assert states[-1] is PlaybackState.UNCERTAIN
    assert read(probe, 3.0, still=True) is PlaybackState.STOPPED
    assert probe.state_since == 0.8
    assert read(probe, 3.2, motion=True) is PlaybackState.ADVANCING


def test_text_change_requires_confirmation_and_is_separate_support():
    probe = PlayingConfidence()
    read(probe, 0, still=True, text="First sentence")
    read(probe, 0.4, still=True, text="First sentence")
    baseline = probe.confidence
    assert read(probe, 0.8, still=True, text="Second sentence") is PlaybackState.UNCERTAIN
    assert read(probe, 1.2, still=True, text="Second sentence") is PlaybackState.UNCERTAIN
    assert probe.confidence > baseline


def test_native_sound_supports_static_dialogue_but_silence_alone_does_not_stop():
    probe = PlayingConfidence()
    audio = AudioObservation(11, True, 0.02)
    assert read(probe, 0, still=True, audio=audio) is PlaybackState.ADVANCING
    assert read(probe, 0.4, still=True, audio=audio) is PlaybackState.ADVANCING
    states = [
        read(probe, at, still=True, audio=AudioObservation(11, True, 0))
        for at in (0.8, 1.2, 1.6, 2.0)
    ]
    assert PlaybackState.STOPPED not in states
    assert states[-1] is PlaybackState.UNCERTAIN


def test_background_sound_never_certifies_static_browser_or_renews_lost_motion():
    probe = PlayingConfidence()
    ambient = AudioObservation(0, True, 0.2, attributed=False)
    for at in (0, 0.4, 0.8):
        assert read(probe, at, still=True, audio=ambient) is PlaybackState.UNCERTAIN
    assert read(probe, 1.2, motion=True, audio=ambient) is PlaybackState.ADVANCING
    states = [read(probe, at, still=True, audio=ambient) for at in (1.6, 2.0, 2.4, 2.8)]
    assert PlaybackState.INVALIDATED not in states
    assert states[-1] is PlaybackState.UNCERTAIN


def test_blank_text_never_creates_text_progression():
    probe = PlayingConfidence()
    for at in (0, 0.4, 0.8):
        assert read(probe, at, still=True, text="") is PlaybackState.UNCERTAIN


def test_changing_overlay_and_unrelated_sound_do_not_certify_browser_playback():
    probe = PlayingConfidence()
    ambient = AudioObservation(0, True, 0.2, attributed=False)
    for index, text in enumerate(("First", "First", "Second", "Second", "Third", "Third")):
        assert (
            read(probe, index * 0.4, still=True, text=text, audio=ambient)
            is PlaybackState.UNCERTAIN
        )


def test_capture_outage_resets_retained_evidence():
    probe = PlayingConfidence()
    assert read(probe, 0, motion=True) is PlaybackState.ADVANCING
    assert read(probe, 6, still=True) is PlaybackState.UNCERTAIN
    assert read(probe, 5, still=True) is PlaybackState.UNCERTAIN
