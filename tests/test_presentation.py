from dataclasses import asdict

from meocosub2.models import SubtitleLine
from meocosub2.presentation import PresentationTrack


def line(
    index: int, start: int, end: int, text: str, translated: str = "", source: str = "human"
) -> SubtitleLine:
    cue = SubtitleLine(index=index, start_ms=start, end_ms=end, text=text, translated=translated)
    cue.translation_source = source
    return cue


def test_target_segmentation_preserves_each_active_target_cue() -> None:
    source = [line(0, 0, 4000, "source")]
    target = [line(3, 0, 2000, "first"), line(4, 2000, 4000, "second")]

    track = PresentationTrack(source, target)

    assert track.resolve_at(1000).text == "first"
    assert track.resolve_at(2500).text == "second"
    assert [asdict(cue) for cue in track.resolve_at(2500).cues] == [
        {"index": 4, "start_ms": 2000, "end_ms": 4000, "kind": "target"}
    ]


def test_adjacent_target_cues_are_half_open() -> None:
    track = PresentationTrack(
        [line(0, 0, 2000, "source")],
        [line(0, 0, 1000, "left"), line(1, 1000, 2000, "right")],
    )

    assert track.resolve_at(999).text == "left"
    assert track.resolve_at(1000).text == "right"


def test_true_target_overlap_keeps_both_cues_in_target_start_order() -> None:
    track = PresentationTrack(
        [line(0, 0, 3000, "source")],
        [line(3, 500, 2500, "late\nwrap"), line(4, 0, 1500, "early\nwrap")],
    )

    frame = track.resolve_at(1000)

    assert frame.text == "early wrap\nlate wrap"
    assert track.answer(track.source_lines[0]) == "early wrap\nlate wrap"
    assert [cue.index for cue in frame.cues] == [4, 3]


def test_target_coverage_keeps_silence_between_target_intervals() -> None:
    source = [line(0, 0, 5000, "source", "own")]
    target = [line(0, 1000, 2000, "target")]
    track = PresentationTrack(source, target)

    assert track.answer(source[0]) == "target"
    assert track.resolve_at(500).text == ""
    assert track.resolve_at(1000).text == "target"
    assert track.resolve_at(2000).text == ""


def test_next_change_uses_short_projected_target_boundaries() -> None:
    source = [line(0, 0, 5000, "source")]
    target = [line(0, 1000, 1100, "brief")]
    track = PresentationTrack(source, target)

    assert track.next_change_ms(999) == 1000
    assert track.next_change_ms(1000) == 1100


def test_uncovered_source_uses_current_human_then_model_translation() -> None:
    source = [line(0, 0, 2000, "source", "human answer")]
    track = PresentationTrack(source, [])

    assert track.resolve_at(1000).cues[0].kind == "human"
    source[0].translated = "model answer"
    source[0].translation_source = "model"

    frame = track.resolve_at(1000)
    assert frame.text == "model answer"
    assert frame.cues[0].kind == "model"


def test_overlapping_source_fallbacks_keep_each_cue_formatting_and_a_row_between_cues() -> None:
    source = [
        line(0, 0, 2000, "first", "first\nwrapped"),
        line(1, 0, 2000, "second", "second\nwrapped"),
    ]

    frame = PresentationTrack(source, []).resolve_at(1000)

    assert frame.text == "first wrapped\nsecond wrapped"
    assert [cue.index for cue in frame.cues] == [0, 1]


def test_partial_target_overlap_never_becomes_source_fallback() -> None:
    source = [line(0, 0, 4000, "source", "own")]
    target = [line(0, 1000, 2000, "target")]
    track = PresentationTrack(source, target)

    assert track.resolve_at(0).text == ""
    assert track.resolve_at(3000).text == ""


def test_ordered_unique_anchors_choose_robust_offset_and_ignore_repeats() -> None:
    source = [
        line(0, 0, 1000, "s0", "first"),
        line(1, 2000, 3000, "s1", "repeated"),
        line(2, 4000, 5000, "s2", "repeated"),
        line(3, 6000, 7000, "s3", "steady"),
        line(4, 8000, 9000, "s4", "late"),
    ]
    target = [
        line(0, 900, 1900, "first"),
        line(1, 2900, 3900, "repeated"),
        line(2, 4900, 5900, "repeated"),
        line(3, 6900, 7900, "steady"),
        line(4, 9300, 10300, "late"),
    ]

    track = PresentationTrack(source, target)

    assert track.anchor_count == 3
    assert track.offset_ms == 900


def test_model_translation_does_not_anchor_and_no_anchors_defaults_to_zero() -> None:
    source = [line(0, 1000, 2000, "source", "same", "model")]
    target = [line(0, 1900, 2900, "same")]

    track = PresentationTrack(source, target)

    assert track.anchor_count == 0
    assert track.offset_ms == 0


def test_each_candidate_calculates_its_own_offset() -> None:
    target = [line(0, 1000, 2000, "shared")]
    first = PresentationTrack([line(0, 0, 1000, "a", "shared")], target)
    second = PresentationTrack([line(0, 500, 1500, "b", "shared")], target)

    assert first.offset_ms == 1000
    assert second.offset_ms == 500
