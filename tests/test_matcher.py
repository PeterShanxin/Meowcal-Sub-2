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


def bilingual_lines() -> list[SubtitleLine]:
    """A source file that carries the dialogue and its translation in one cue."""
    rows = [
        "我们就跳进那缸酸\nwe jump into the vat of acid,",
        "你不是个发明家么\nAren't you an inventor?",
        "你带的是假水晶 还带了枪\nYou brought fake crystals and a gun",
        "慢慢来 老大\nTake your time, boss.",
    ]
    return [
        SubtitleLine(index=i, start_ms=i * 2000, end_ms=i * 2000 + 1500, text=text)
        for i, text in enumerate(rows)
    ]


def test_a_read_is_scored_against_its_own_half_of_a_bilingual_cue() -> None:
    matcher = SubtitleMatcher(bilingual_lines(), target_language="en")
    result = matcher.match("慢慢来老大")
    assert result is not None
    assert result.line_index == 3
    # Against the whole cue, its English half included, the same read scored 90.
    assert result.score == 100.0


def test_a_read_of_something_that_is_not_a_subtitle_matches_nothing() -> None:
    matcher = SubtitleMatcher(bilingual_lines(), target_language="en")
    # A stray read of a terminal. Scored against whole bilingual cues it used to
    # come back at 85.5, because a long line rewards a good match on a fragment.
    assert matcher.match("o ps c formerd repos meowcal sub 2 src tauri") is None


def test_a_read_far_shorter_than_the_line_is_not_that_line() -> None:
    matcher = SubtitleMatcher(bilingual_lines(), target_language="en")
    assert matcher.match("你不是说") is None


def episode_lines() -> list[SubtitleLine]:
    return [
        SubtitleLine(index=0, start_ms=0, end_ms=2000, text="Hello there", translated="你好"),
        SubtitleLine(index=1, start_ms=10_000, end_ms=12_000, text="Goodbye now", translated="再见"),
    ]


def test_the_file_line_at_a_point_in_the_video() -> None:
    matcher = SubtitleMatcher(episode_lines())
    found = matcher.line_at(11_000)
    assert found is not None and found.line_index == 1
    assert found.target_text == "再见"


def test_the_file_has_no_line_in_the_silence_between_its_cues() -> None:
    matcher = SubtitleMatcher(episode_lines())
    assert matcher.line_at(6_000) is None
    assert matcher.line_at(-1) is None


def test_a_line_still_counts_just_past_its_own_end() -> None:
    # Two translations of one scene rarely break their cues in the same places,
    # so the file's line often ends a beat before the burned-in one does.
    matcher = SubtitleMatcher(episode_lines())
    assert matcher.line_at(13_000) is not None
    assert matcher.line_at(14_000) is None


def spaced_lines() -> list[SubtitleLine]:
    """Three cues with real gaps between them, so the grace period is reachable."""
    return [
        SubtitleLine(index=0, start_ms=0, end_ms=2000, text="Hello there", translated="你好"),
        SubtitleLine(index=1, start_ms=10_000, end_ms=12_000, text="Goodbye now", translated="再见"),
        SubtitleLine(index=2, start_ms=20_000, end_ms=22_000, text="See you", translated="回见"),
    ]


def test_a_line_on_screen_changes_when_its_grace_runs_out() -> None:
    matcher = SubtitleMatcher(spaced_lines())
    # The next cue is ten seconds off, so this line expiring is what changes first.
    assert matcher.next_change_ms(500) == 2000 + 1500 + 1


def test_a_clock_in_a_gap_waits_for_the_next_cue() -> None:
    matcher = SubtitleMatcher(spaced_lines())
    assert matcher.line_at(5000) is None
    assert matcher.next_change_ms(5000) == 10_000


def test_a_cue_that_ends_after_the_next_one_starts_changes_at_the_next_one() -> None:
    overlapping = [
        SubtitleLine(index=0, start_ms=0, end_ms=1000, text="Hello there", translated="你好"),
        SubtitleLine(index=1, start_ms=1200, end_ms=2000, text="Goodbye now", translated="再见"),
    ]
    matcher = SubtitleMatcher(overlapping)
    # The first line's grace would carry it to 2501, past where the second begins.
    assert matcher.next_change_ms(500) == 1200


def test_nothing_changes_after_the_last_line_has_gone() -> None:
    matcher = SubtitleMatcher(spaced_lines())
    assert matcher.next_change_ms(25_000) is None


def test_the_first_cue_is_scheduled_from_before_the_file_starts() -> None:
    matcher = SubtitleMatcher(spaced_lines()[1:])
    assert matcher.next_change_ms(0) == 10_000
