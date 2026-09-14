import pytest

from meocosub2.subtitle_gate import LineChange, SubtitleGate, classify, is_entirely_noise


def test_an_identical_re_read_is_a_repeat() -> None:
    assert classify("Hello there", "Hello there") is LineChange.REPEAT


def test_punctuation_and_spacing_differences_are_a_repeat() -> None:
    assert classify("Hello, there.", "Hello there") is LineChange.REPEAT


def test_a_read_that_dropped_a_glyph_is_a_repeat() -> None:
    assert classify("击碎她的信仰", "击的信仰") is LineChange.REPEAT


def test_different_dialogue_is_new() -> None:
    assert classify("Hello there", "Where are you going") is LineChange.NEW


def test_a_short_reply_is_not_swallowed_by_a_longer_line() -> None:
    assert classify("I don't know.", "No.") is LineChange.NEW


def test_a_second_row_arriving_is_an_extension() -> None:
    assert (
        classify("However, isn't he", "However, isn't he a hero from an era") is LineChange.EXTENDED
    )


def test_one_more_resolved_character_is_not_an_extension() -> None:
    assert classify("活下去", "活下去 0") is LineChange.REPEAT


def test_a_garbled_prefix_on_the_same_line_is_a_repeat() -> None:
    assert (
        classify("However, isn't he a hero", "bf//dzz:: However, isn't he a hero")
        is LineChange.REPEAT
    )


def test_a_real_clause_arriving_before_the_line_is_still_an_extension() -> None:
    assert (
        classify("department opened today", "The R&D department opened today")
        is LineChange.EXTENDED
    )


@pytest.mark.parametrize("text", ["bf//dzz:: 0", "@~", "|_"])
def test_pure_noise_is_recognised(text: str) -> None:
    assert is_entirely_noise(text)


@pytest.mark.parametrize("text", ["R&D department", "AT&T calling", "hello"])
def test_real_text_is_not_noise(text: str) -> None:
    assert not is_entirely_noise(text)


def test_the_gate_treats_the_first_read_as_new() -> None:
    assert SubtitleGate().classify("Hello there", now=0.0) is LineChange.NEW


def test_stable_reads_ignore_punctuation_but_still_deduplicate_the_cue() -> None:
    gate = SubtitleGate(require_stable_read=True)
    assert gate.classify("Hello, there.", now=0.0) is LineChange.UNSTABLE
    assert gate.classify("Hello there", now=0.5) is LineChange.NEW
    gate.remember("Hello there", now=0.5)
    assert gate.classify("Hello there!", now=1.0) is LineChange.REPEAT


def test_a_confirmed_second_row_still_extends_the_cue() -> None:
    gate = SubtitleGate(require_stable_read=True)
    gate.classify("However, isn't he", now=0.0)
    assert gate.classify("However, isn't he", now=0.5) is LineChange.NEW
    gate.remember("However, isn't he", now=0.5)
    extended = "However, isn't he a hero from an era"
    assert gate.classify(extended, now=1.0) is LineChange.UNSTABLE
    assert gate.classify(extended, now=1.5) is LineChange.EXTENDED


def test_the_gate_suppresses_a_row_it_saw_two_reads_ago() -> None:
    gate = SubtitleGate()
    gate.remember("Top row of the cue", now=0.0)
    gate.remember("Bottom row of the cue", now=0.5)
    assert gate.classify("Top row of the cue", now=1.0) is LineChange.REPEAT


def test_the_gate_lets_the_same_words_through_again_after_the_window() -> None:
    gate = SubtitleGate()
    gate.remember("Hello there", now=0.0)
    assert gate.classify("Hello there", now=30.0) is LineChange.NEW


def test_a_repeat_keeps_a_cue_alive_while_it_stays_on_screen() -> None:
    gate = SubtitleGate()
    gate.remember("Hello there", now=0.0)
    for moment in (4.0, 8.0, 12.0):
        assert gate.classify("Hello there", now=moment) is LineChange.REPEAT


def test_clearing_the_gate_forgets_the_cue() -> None:
    gate = SubtitleGate()
    gate.remember("Hello there", now=0.0)
    gate.clear()
    assert gate.classify("Hello there", now=1.0) is LineChange.NEW
