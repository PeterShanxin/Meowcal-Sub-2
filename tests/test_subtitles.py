from pathlib import Path

import pytest

from meocosub2.models import SubtitleLine
from meocosub2.subtitles import (
    align_subtitles,
    alignment_report,
    load_subtitle_file,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_srt_parses_lines() -> None:
    lines = load_subtitle_file(FIXTURES / "sample.srt")
    assert len(lines) == 5
    assert lines[0].index == 0
    assert lines[0].text == "Hello, world!"
    assert lines[0].start_ms == 1000
    assert lines[0].end_ms == 4000


def test_load_subtitle_file_strips_formatting_tags() -> None:
    lines = load_subtitle_file(FIXTURES / "sample.ass")
    assert "{" not in lines[2].text
    assert "Bold" in lines[2].text


def test_load_subtitle_file_falls_back_to_latin1(tmp_path: Path) -> None:
    subtitle = "1\n00:00:01,000 --> 00:00:02,000\nOl\xe9 mundo\n"
    path = tmp_path / "latin1.srt"
    path.write_bytes(subtitle.encode("latin-1"))
    lines = load_subtitle_file(path)
    assert lines[0].text == "Olé mundo"


def test_loading_automatically_orders_and_deduplicates_without_rewriting(tmp_path: Path) -> None:
    path = tmp_path / "unordered.srt"
    raw = (
        b"1\n00:00:03,000 --> 00:00:04,000\nLater\n\n"
        b"2\n00:00:01,000 --> 00:00:02,000\nFirst\n\n"
        b"3\n00:00:01,000 --> 00:00:02,000\nFirst\n\n"
        b"4\n00:00:01,500 --> 00:00:02,500\nAnother speaker\n\n"
        b"5\n00:00:05,000 --> 00:00:06,000\nFirst\n"
    )
    path.write_bytes(raw)
    checks = []
    lines = load_subtitle_file(path, checks=checks)
    assert [(line.index, line.start_ms, line.text) for line in lines] == [
        (0, 1000, "First"),
        (1, 1500, "Another speaker"),
        (2, 3000, "Later"),
        (3, 5000, "First"),
    ]
    assert checks[0].duplicates_removed == 1
    assert checks[0].reordered
    assert path.read_bytes() == raw
    assert load_subtitle_file(path) == lines


@pytest.mark.parametrize("end", ["00:00:01,000", "00:00:00,500"])
def test_bad_timing_is_reported_instead_of_guessed(tmp_path: Path, end: str) -> None:
    path = tmp_path / "broken.srt"
    path.write_text(f"1\n00:00:01,000 --> {end}\nKeep this dialogue\n", encoding="utf-8")
    with pytest.raises(ValueError, match="broken.srt.*cue 1.*timing"):
        load_subtitle_file(path)


def test_empty_and_nul_text_do_not_claim_a_ready_track(tmp_path: Path) -> None:
    path = tmp_path / "broken.srt"
    path.write_text("1\n00:00:01,000 --> 00:00:02,000\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no playable"):
        load_subtitle_file(path)
    path.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\0world\n", encoding="utf-8")
    with pytest.raises(ValueError, match="NUL"):
        load_subtitle_file(path)


def test_equal_start_times_keep_speaker_order_and_empty_cues_are_counted(tmp_path: Path) -> None:
    path = tmp_path / "speakers.srt"
    path.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nFirst speaker\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nSecond speaker\n\n"
        "3\n00:00:04,000 --> 00:00:05,000\n<i></i>\n",
        encoding="utf-8",
    )
    checks = []
    lines = load_subtitle_file(path, checks=checks)
    assert [line.text for line in lines] == ["First speaker", "Second speaker"]
    assert checks[0].empty_removed == 1
    assert not checks[0].reordered


def test_align_subtitles_keeps_both_tracks() -> None:
    source = [
        SubtitleLine(index=0, start_ms=0, end_ms=1000, text="Hello"),
        SubtitleLine(index=1, start_ms=1000, end_ms=2000, text="World"),
    ]
    target = [
        SubtitleLine(index=0, start_ms=0, end_ms=1000, text="你好"),
        SubtitleLine(index=1, start_ms=1000, end_ms=2000, text="世界"),
    ]
    pair = align_subtitles(source, target)
    assert pair.source_lines[0].text == "Hello"
    assert pair.target_lines[0].text == "你好"


def test_align_subtitles_empty_target() -> None:
    source = [SubtitleLine(index=0, start_ms=0, end_ms=1000, text="Hello")]
    pair = align_subtitles(source, [])
    assert pair.target_lines == []


def _cue(index: int, start_ms: int, end_ms: int, text: str) -> SubtitleLine:
    return SubtitleLine(index=index, start_ms=start_ms, end_ms=end_ms, text=text)


def test_a_target_file_that_answers_everything_leaves_nothing_unpaired() -> None:
    source = [_cue(0, 0, 2000, "s0"), _cue(1, 3000, 5000, "s1")]
    target = [_cue(0, 0, 2000, "t0"), _cue(1, 3000, 5000, "t1")]

    report = alignment_report(source, target)

    assert report.total_cues == 2
    assert report.unpaired_cues == 0
    assert report.unpaired_ms == 0


def test_the_report_counts_the_seconds_the_plate_would_hold_the_wrong_line() -> None:
    # A cue the target file has nothing over is a cue the plate spends showing
    # the line before it, so the cost is measured in time rather than in lines.
    source = [_cue(0, 0, 2000, "s0"), _cue(1, 60_000, 64_500, "s1")]
    target = [_cue(0, 0, 2000, "t0")]

    report = alignment_report(source, target)

    assert report.unpaired_cues == 1
    assert report.unpaired_ms == 4500


def test_reporting_on_a_candidate_leaves_the_session_lines_alone() -> None:
    # The viewer's own choice is already paired; asking about a rival must not
    # repair or disturb it.
    source = [_cue(0, 0, 2000, "s0")]
    source[0].translated = "chosen"

    alignment_report(source, [_cue(0, 0, 2000, "rival")])

    assert source[0].translated == "chosen"


def test_a_target_file_with_no_lines_answers_nothing() -> None:
    source = [_cue(0, 0, 2000, "s0"), _cue(1, 3000, 5000, "s1")]

    report = alignment_report(source, [])

    assert report.unpaired_cues == 2
    assert report.unpaired_ms == 4000
