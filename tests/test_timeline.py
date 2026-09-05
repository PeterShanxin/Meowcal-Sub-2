from meocosub2.timeline import (
    AGREEING_OFFSET_MS,
    ANCHOR_ABANDON_MISSES,
    ANCHOR_MAX_AGE_S,
    CUE_HOLD_S,
    PlaybackTimeline,
)


def anchored_at(start_ms: int, index: int = 10, now: float = 0.0) -> PlaybackTimeline:
    timeline = PlaybackTimeline()
    read(timeline, start_ms, index, score=100.0, now=now)
    assert timeline.anchored
    return timeline


def read(timeline: PlaybackTimeline, start_ms: int, index: int, score: float, now: float) -> bool:
    """A match, offered the way the capture loop offers one.

    The loop reports the cue before it reports what matched in it, and the clock
    anchors to when the cue appeared rather than to when it was recognised.
    """
    timeline.saw_new_cue(now=now)
    return timeline.accepts(start_ms, index, score, now=now)


def test_an_unanchored_timeline_has_nothing_to_offer_the_matcher() -> None:
    timeline = PlaybackTimeline()
    assert timeline.window_ms(now=0.0) is None
    assert timeline.predicted_ms(now=0.0) is None
    assert not timeline.anchored


def test_a_near_exact_first_match_anchors_on_its_own() -> None:
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
    assert read(timeline, 603_000, 11, score=70.0, now=3.0)
    assert timeline.predicted_ms(now=3.0) == 603_000


def test_a_far_off_line_with_an_ordinary_score_is_rejected() -> None:
    timeline = anchored_at(600_000)
    # "Yes." appears sixty times in an episode; text alone cannot say which one
    # is on screen, and this one is ten minutes from where the video is.
    assert not read(timeline, 1_200_000, 400, score=70.0, now=3.0)
    assert timeline.predicted_ms(now=3.0) == 603_000


def test_a_seek_is_followed_once_a_second_read_agrees_with_it() -> None:
    timeline = anchored_at(600_000)
    assert not read(timeline, 1_200_000, 400, score=95.0, now=3.0)
    assert read(timeline, 1_202_500, 402, score=95.0, now=6.0)
    assert timeline.predicted_ms(now=6.0) == 1_202_500


def test_two_high_scores_in_different_places_do_not_move_the_clock() -> None:
    timeline = anchored_at(600_000)
    assert not read(timeline, 1_200_000, 400, score=95.0, now=3.0)
    assert not read(timeline, 300_000, 90, score=95.0, now=6.0)
    assert timeline.predicted_ms(now=6.0) == 606_000


def test_a_paused_video_walks_the_clock_back_to_where_it_was_paused() -> None:
    """Not just stopped: returned to the line the viewer is looking at.

    The clock runs on for a few seconds before a hold is long enough to read as
    a pause, and those seconds put two or three lines on the plate that the
    viewer never reached.
    """
    timeline = anchored_at(600_000)
    # The same subtitle sits on screen for half a minute, which no subtitle does
    # while the video is playing.
    for elapsed in range(1, 31):
        timeline.saw_same_cue(now=float(elapsed))
    assert timeline.predicted_ms(now=30.0) == 600_000


def test_the_walk_back_is_given_up_as_soon_as_the_video_moves_again() -> None:
    """Otherwise a pause would leave the clock behind for the rest of the episode."""
    timeline = anchored_at(600_000)
    for elapsed in range(1, 31):
        timeline.saw_same_cue(now=float(elapsed))
    timeline.saw_new_cue(now=30.0)

    # The seconds the hold took out of the clock stay out; the walk back does not.
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
    # With no anchor left the session can find the video again, on the same
    # evidence any first match needs.
    assert timeline.accepts(1_200_000, 400, score=100.0, now=10.0)


def test_an_anchor_no_match_has_confirmed_for_a_long_time_expires() -> None:
    timeline = anchored_at(600_000)
    late = ANCHOR_MAX_AGE_S + 1
    assert timeline.position_ms(now=late) is None
    assert not timeline.anchored
    assert read(timeline, 60_000, 20, score=100.0, now=late)
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


def test_the_clock_anchors_to_when_the_cue_appeared_not_when_it_was_read() -> None:
    timeline = PlaybackTimeline()
    timeline.saw_new_cue(now=10.0)
    # Capturing every quarter second and then running OCR puts the read a beat
    # behind the picture.
    assert timeline.accepts(600_000, 10, score=100.0, now=10.5)
    # The line began half a second ago, so the video is half a second past its
    # start - not sitting on it, which is what made every drawn line late.
    assert timeline.predicted_ms(now=10.5) == 600_500


def test_a_weak_first_match_waits_for_a_second_that_agrees_with_it() -> None:
    """One ordinary match is not enough to place a whole episode.

    Most reads share no words with the file, so the score that gets one over the
    threshold is often circumstantial. A wrong anchor then draws wrong subtitles
    until something disagrees with it, which is far more expensive than waiting.
    """
    timeline = PlaybackTimeline()
    assert not read(timeline, 600_000, 10, score=70.0, now=0.0)
    assert not timeline.anchored
    # Four seconds later, four seconds further into the file: the same playback.
    assert read(timeline, 604_000, 12, score=70.0, now=4.0)
    assert timeline.predicted_ms(now=4.0) == 604_000


def test_a_weak_first_match_is_refused_when_the_second_disagrees() -> None:
    timeline = PlaybackTimeline()
    assert not read(timeline, 600_000, 10, score=70.0, now=0.0)
    # Four seconds of playback cannot have moved the video a minute on, so these
    # two reads are not describing the same video.
    assert not read(timeline, 660_000, 90, score=70.0, now=4.0)
    assert not timeline.anchored


def test_agreement_is_judged_on_position_rather_than_on_the_line_number() -> None:
    """Two matches agree when they put the video in the same place.

    Lines are not evenly spaced - a minute of silence and a minute of argument
    are the same number of lines apart or wildly different - so the distance
    between two line numbers says nothing about whether they agree.
    """
    timeline = PlaybackTimeline()
    assert not read(timeline, 600_000, 10, score=70.0, now=0.0)
    drifted = 600_000 + 4_000 + AGREEING_OFFSET_MS + 1
    assert not read(timeline, drifted, 11, score=70.0, now=4.0)
    assert not timeline.anchored
