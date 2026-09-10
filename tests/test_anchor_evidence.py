import pytest

from meocosub2.timeline import PlaybackTimeline


def offer(timeline, start, index, score, *, now, seen_at, confident=False):
    timeline.saw_new_cue(now=seen_at)
    return timeline.accepts(start, index, score, now=now, seen_at=seen_at, confident=confident)


def anchored() -> PlaybackTimeline:
    timeline = PlaybackTimeline()
    assert offer(timeline, 390_620, 154, 100, now=0, seen_at=0)
    return timeline


@pytest.mark.parametrize("shift", [-7_000, 9_705, 24_000])
@pytest.mark.parametrize("score,confident", [(66.48, False), (87.99, False)])
def test_search_window_does_not_authorize_a_single_jump(shift, score, confident):
    timeline = anchored()
    assert not offer(
        timeline, 396_325 + shift, 162, score, now=5.705, seen_at=5.705, confident=confident
    )
    assert timeline.position_ms(now=5.705) == 396_325


def test_weak_forward_jump_recovers_when_a_different_cue_agrees():
    timeline = anchored()
    assert not offer(timeline, 406_030, 162, 66.48, now=5.705, seen_at=5.705)
    assert offer(timeline, 409_030, 163, 70, now=8.705, seen_at=8.705)
    assert timeline.position_ms(now=8.705) == 409_030


def test_repeated_wrong_cue_cannot_confirm_its_own_jump():
    timeline = anchored()
    for now in (5.705, 6.205, 6.705):
        assert not offer(timeline, 406_030, 162, 70, now=now, seen_at=5.705)
    assert timeline.position_ms(now=6.705) == 397_325


def test_same_capture_cannot_confirm_a_different_match():
    timeline = anchored()
    assert not offer(timeline, 406_030, 162, 70, now=5.705, seen_at=5.705)
    assert not offer(timeline, 407_030, 163, 70, now=6.205, seen_at=5.705)


def test_corroboration_expires_before_an_unrelated_later_read():
    timeline = anchored()
    assert not offer(timeline, 406_030, 162, 70, now=5.705, seen_at=5.705)
    assert not offer(timeline, 436_030, 175, 70, now=35.705, seen_at=35.705)


def test_ocr_latency_does_not_count_as_backward_drift():
    timeline = anchored()
    assert offer(timeline, 396_325, 155, 70, now=9.705, seen_at=5.705)
    assert timeline.position_ms(now=9.705) == 400_325
    assert timeline.status(now=9.705).drift_ms == 0


@pytest.mark.parametrize("start", [60_000, 1_200_000])
def test_whole_file_weak_phrase_does_not_move_the_clock(start):
    timeline = anchored()
    assert not offer(timeline, start, 109, 67.5, now=3, seen_at=3)
    assert timeline.position_ms(now=3) == 393_620


def test_nearby_correct_anchor_clears_rejected_jump_evidence():
    timeline = anchored()
    assert not offer(timeline, 406_030, 162, 70, now=5.705, seen_at=5.705)
    assert offer(timeline, 398_620, 155, 70, now=8, seen_at=8)
    assert not offer(timeline, 409_030, 163, 70, now=8.705, seen_at=8.705)
