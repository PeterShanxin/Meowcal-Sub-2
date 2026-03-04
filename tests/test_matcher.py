from meocosub2.matcher import SubtitleMatcher
from meocosub2.models import SubtitleLine


def make_lines(count: int = 100) -> list[SubtitleLine]:
    return [
        SubtitleLine(index=i, start_ms=i * 1000, end_ms=(i + 1) * 1000, text=f"Line {i}", translated=f"译文 {i}")
        for i in range(count)
    ]


def test_normalize_strips_tags_and_hi_markers() -> None:
    matcher = SubtitleMatcher(make_lines())
    normalized = matcher.normalize_text("<i>Hello</i> {\\an8} [Music] world!")
    assert normalized == "hello world"


def test_duplicate_frames_return_none() -> None:
    matcher = SubtitleMatcher([SubtitleLine(index=0, start_ms=0, end_ms=1000, text="Hello there")])
    assert matcher.match("Hello there") is not None
    assert matcher.match("Hello there") is None


def test_short_noise_returns_none() -> None:
    matcher = SubtitleMatcher(make_lines())
    assert matcher.match("hi") is None


def test_match_returns_translated_text() -> None:
    matcher = SubtitleMatcher([SubtitleLine(index=0, start_ms=0, end_ms=1000, text="Hello there", translated="你好")])
    result = matcher.match("Hello there")
    assert result is not None
    assert result.target_text == "你好"


def test_match_falls_back_to_source_text() -> None:
    matcher = SubtitleMatcher([SubtitleLine(index=0, start_ms=0, end_ms=1000, text="Hello there")])
    result = matcher.match("Hello there")
    assert result is not None
    assert result.target_text == "Hello there"


def test_windowed_search_advances_forward() -> None:
    matcher = SubtitleMatcher(make_lines())
    matcher._last_match_position = 10
    assert list(matcher._search_indices()) == list(range(5, 41))


def test_first_search_uses_initial_window_cap() -> None:
    matcher = SubtitleMatcher(make_lines())
    assert list(matcher._search_indices()) == list(range(50))


def test_fallback_full_scan_when_window_misses() -> None:
    lines = make_lines()
    for index, line in enumerate(lines):
        line.text = f"placeholder {index}"
    lines[80].text = "distant zebra quartz line"
    matcher = SubtitleMatcher(lines)
    matcher._last_match_position = 2
    result = matcher.match("distant zebra quartz line")
    assert result is not None
    assert result.line_index == 80


def test_threshold_blocks_weak_matches() -> None:
    matcher = SubtitleMatcher(make_lines(), fuzzy_threshold=100)
    assert matcher.match("completely unrelated phrase") is None
