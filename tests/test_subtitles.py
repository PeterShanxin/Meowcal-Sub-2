from pathlib import Path

from meocosub2.models import SubtitleLine
from meocosub2.subtitles import align_subtitles, load_subtitle_file

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
    subtitle = (
        "1\n"
        "00:00:01,000 --> 00:00:02,000\n"
        "Ol\xe9 mundo\n"
    )
    path = tmp_path / "latin1.srt"
    path.write_bytes(subtitle.encode("latin-1"))
    lines = load_subtitle_file(path)
    assert lines[0].text == "Olé mundo"


def test_align_subtitles_pairs_by_index() -> None:
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
