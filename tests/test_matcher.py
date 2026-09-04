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


def test_is_repeated_frame_reports_duplicate_normalized_ocr() -> None:
    matcher = SubtitleMatcher([SubtitleLine(index=0, start_ms=0, end_ms=1000, text="Hello there")])

    assert matcher.is_repeated_frame("Hello there") is False
    assert matcher.match("Hello there") is not None
    assert matcher.is_repeated_frame("Hello there!") is True


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
    assert list(matcher._search_indices()) == list(range(35))


def test_first_search_respects_configured_forward_window() -> None:
    matcher = SubtitleMatcher(make_lines(200), window_forward=100, window_backward=10)
    assert list(matcher._search_indices()) == list(range(110))


def test_short_cjk_line_matches() -> None:
    matcher = SubtitleMatcher([SubtitleLine(index=0, start_ms=0, end_ms=1000, text="好的。")])
    result = matcher.match("好的")
    assert result is not None
    assert result.line_index == 0


def test_single_cjk_char_can_match() -> None:
    matcher = SubtitleMatcher([SubtitleLine(index=0, start_ms=0, end_ms=1000, text="是。")])
    result = matcher.match("是")
    assert result is not None
    assert result.line_index == 0


def test_cjk_match_tolerates_ocr_char_drop() -> None:
    matcher = SubtitleMatcher(
        [SubtitleLine(index=0, start_ms=0, end_ms=1000, text="我今天很开心")],
        fuzzy_threshold=80,
    )
    result = matcher.match("我今很开心")
    assert result is not None
    assert result.line_index == 0


def _unique_lines(count: int = 100) -> list[SubtitleLine]:
    import hashlib
    out: list[SubtitleLine] = []
    for i in range(count):
        digest = hashlib.sha1(f"line-{i}".encode()).hexdigest()
        text = f"{digest[:8]} {digest[8:16]} {digest[16:24]} {digest[24:32]}"
        out.append(SubtitleLine(index=i, start_ms=i * 1000, end_ms=(i + 1) * 1000, text=text))
    return out


def test_reset_clears_window_anchor() -> None:
    lines = _unique_lines()
    matcher = SubtitleMatcher(lines)
    target = lines[90].text
    result = matcher.match(target)
    assert result is not None and result.line_index == 90
    matcher.reset()
    assert matcher._last_match_position is None
    assert matcher._last_frame_hash is None
    assert list(matcher._search_indices()) == list(range(35))


def test_seek_back_self_heals_via_full_scan() -> None:
    lines = _unique_lines()
    matcher = SubtitleMatcher(lines)
    matcher._last_match_position = 90
    result = matcher.match(lines[5].text)
    assert result is not None
    assert result.line_index == 5
    assert matcher._last_match_position == 5


def test_window_backward_is_configurable() -> None:
    matcher = SubtitleMatcher(make_lines(), window_forward=10, window_backward=20)
    matcher._last_match_position = 30
    assert list(matcher._search_indices()) == list(range(10, 41))


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


def test_match_handles_spaced_cjk_and_script_variants() -> None:
    matcher = SubtitleMatcher(
        [SubtitleLine(index=0, start_ms=0, end_ms=1000, text="之前拿到的资料，我都看过了", translated="I already read it.")]
    )
    result = matcher.match("之 前 拿 到 的 資 料 ， 我 都 看 過 了")
    assert result is not None
    assert result.target_text == "I already read it."


def test_is_repeated_frame_recognizes_short_cjk_repeat() -> None:
    matcher = SubtitleMatcher([SubtitleLine(index=0, start_ms=0, end_ms=1000, text="是。")])
    # First call seeds the hash via match().
    assert matcher.match("是") is not None
    # Same 1-char CJK frame must be flagged as a repeat, mirroring match()'s
    # min-length rule — otherwise the auto-candidate loop counts the duplicate
    # as a miss and unlocks the locked subtitle prematurely.
    assert matcher.is_repeated_frame("是") is True


def test_is_repeated_frame_rejects_short_ascii() -> None:
    matcher = SubtitleMatcher(make_lines())
    matcher._last_frame_hash = matcher._hash_text("hi")
    assert matcher.is_repeated_frame("hi") is False


def test_stray_edge_marks_beside_chinese_dialogue_are_dropped() -> None:
    from meocosub2.textnorm import clean_cjk_text

    assert clean_cjk_text("0 = 很自然 我们甚至不会察觉") == "很自然我们甚至不会察觉"
    assert clean_cjk_text("很自然 0") == "很自然"


def test_numbers_beside_latin_text_are_kept() -> None:
    from meocosub2.textnorm import clean_cjk_text

    assert clean_cjk_text("Chapter 7") == "Chapter 7"
    assert clean_cjk_text("- Can you do it?") == "- Can you do it?"
