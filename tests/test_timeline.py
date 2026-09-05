from meocosub2.timeline import (
    ANCHOR_ABANDON_MISSES,
    ANCHOR_MAX_AGE_S,
    CUE_HOLD_S,
    PlaybackTimeline,
)


def anchored_at(start_ms: int, index: int = 10, now: float = 0.0) -> PlaybackTimeline:
    timeline = PlaybackTimeline()
    assert timeline.accepts(start_ms, index, score=100.0, now=now)
    return timeline


def test_an_unanchored_timeline_has_nothing_to_offer_the_matcher() -> None:
    timeline = PlaybackTimeline()
    assert timeline.window_ms(now=0.0) is None
    assert timeline.predicted_ms(now=0.0) is None
    assert not timeline.anchored


def test_the_first_match_is_believed_and_becomes_the_anchor() -> None:
    timeline = anchored_at(600_000)
    assert timeline.anchored
    assert timeline.predicted_ms(now=0.0) == 600_000


def test_the_prediction_advances_with_the_wall_clock() -> None:
    timeline = anchored_at(600_000)
    assert timeline.predicted_ms(now=4.0) == 604_000


def test_a_line_near_the_prediction_is_accepted() -> None:
    timeline = anchored_at(600_000)
    # Three seconds of playback later, the next subtitle starts where the clock
    # says the video is.
    assert timeline.accepts(603_000, 11, score=70.0, now=3.0)
    assert timeline.predicted_ms(now=3.0) == 603_000


def test_a_far_off_line_with_an_ordinary_score_is_rejected() -> None:
    timeline = anchored_at(600_000)
    # "Yes." appears sixty times in an episode; text alone cannot say which one
    # is on screen, and this one is ten minutes from where the video is.
    assert not timeline.accepts(1_200_000, 400, score=70.0, now=3.0)
    assert timeline.predicted_ms(now=3.0) == 603_000


def test_a_seek_is_followed_once_a_second_read_agrees_with_it() -> None:
    timeline = anchored_at(600_000)
    assert not timeline.accepts(1_200_000, 400, score=95.0, now=3.0)
    assert timeline.accepts(1_202_500, 402, score=95.0, now=6.0)
    assert timeline.predicted_ms(now=6.0) == 1_202_500


def test_two_high_scores_in_different_places_do_not_move_the_clock() -> None:
    timeline = anchored_at(600_000)
    assert not timeline.accepts(1_200_000, 400, score=95.0, now=3.0)
    assert not timeline.accepts(300_000, 90, score=95.0, now=6.0)
    assert timeline.predicted_ms(now=6.0) == 606_000


def test_a_paused_video_does_not_run_the_clock_on() -> None:
    timeline = anchored_at(600_000)
    # The same subtitle sits on screen for half a minute, which no subtitle does
    # while the video is playing.
    for elapsed in range(1, 31):
        timeline.saw_same_cue(now=float(elapsed))
    assert timeline.predicted_ms(now=30.0) == 600_000 + int(CUE_HOLD_S * 1000)


def test_a_cue_of_ordinary_length_is_not_mistaken_for_a_pause() -> None:
    timeline = anchored_at(600_000)
    timeline.saw_same_cue(now=3.0)
    assert timeline.predicted_ms(now=3.0) == 603_000


def test_an_anchor_nothing_agrees_with_is_eventually_abandoned() -> None:
    timeline = anchored_at(600_000)
    for attempt in range(ANCHOR_ABANDON_MISSES):
        assert not timeline.accepts(1_200_000, 400, score=70.0, now=1.0 + attempt)
    assert not timeline.anchored
    # With no anchor left the session can find the video again from scratch.
    assert timeline.accepts(1_200_000, 400, score=70.0, now=10.0)


def test_an_anchor_no_match_has_confirmed_for_a_long_time_expires() -> None:
    timeline = anchored_at(600_000)
    late = ANCHOR_MAX_AGE_S + 1
    assert timeline.accepts(60_000, 20, score=70.0, now=late)
    assert timeline.predicted_ms(now=late) == 60_000


def test_the_window_brackets_the_prediction() -> None:
    timeline = anchored_at(600_000)
    low, high = timeline.window_ms(now=0.0)
    assert low < 600_000 < high
    # Playback runs forward, so a run of missed reads leaves the next hit ahead.
    assert high - 600_000 > 600_000 - low


def test_drift_records_how_far_the_prediction_was_out() -> None:
    timeline = anchored_at(600_000)
    timeline.accepts(604_000, 11, score=70.0, now=3.0)
    assert timeline.status(now=3.0).drift_ms == 1_000
