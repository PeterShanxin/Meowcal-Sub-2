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


def test_target_coverage_is_available_without_source_translation_or_an_engine() -> None:
    from meocosub2.models import PreparedRuntime, SourceSubtitleCandidate

    source = [SubtitleLine(0, 0, 4000, "source")]
    target = [SubtitleLine(0, 0, 2000, "first"), SubtitleLine(1, 2000, 4000, "second")]
    pair = SubtitlePair(source, target)
    candidate = SourceSubtitleCandidate("a", "a.srt", "test", "en", "a.srt", pair)
    runtime = PreparedRuntime("subtitle_pair", target, source_candidates=[candidate])

    assert not runtime.needs_live_translation
    assert source[0].translated == ""
    assert pair.presentation.resolve_at(2500).text == "second"
