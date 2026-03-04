from meocosub2.models import MatchResult, SubtitleLine, SubtitlePair


def test_subtitle_line_defaults() -> None:
    line = SubtitleLine(index=0, start_ms=1000, end_ms=3000, text="Hello")
    assert line.translated == ""
    assert line.index == 0


def test_subtitle_pair_empty_target() -> None:
    source = [SubtitleLine(index=0, start_ms=0, end_ms=1000, text="Hi")]
    pair = SubtitlePair(source_lines=source, target_lines=[])
    assert len(pair.target_lines) == 0


def test_match_result_fields() -> None:
    result = MatchResult(line_index=5, score=87.3, source_text="Hello", target_text="你好")
    assert result.line_index == 5
    assert result.score == 87.3
    assert result.target_text == "你好"
