import asyncio

from meocosub2.gapfill import MAX_FILLED_LINES, context_pairs, fill_gaps
from meocosub2.models import SubtitleLine


async def unchanged() -> None:
    """A fill that nothing is watching for; the session redraws instead."""


def lines(*specs: tuple[str, str]) -> list[SubtitleLine]:
    return [
        SubtitleLine(
            index=index,
            start_ms=index * 1000,
            end_ms=index * 1000 + 900,
            text=text,
            translated=translated,
        )
        for index, (text, translated) in enumerate(specs)
    ]


def test_the_pairs_around_a_gap_come_from_both_sides_in_playback_order() -> None:
    episode = lines(("s0", "t0"), ("s1", "t1"), ("s2", ""), ("s3", "t3"), ("s4", "t4"))
    assert context_pairs(episode, 2) == [("s0", "t0"), ("s1", "t1"), ("s3", "t3")]


def test_an_unanswered_neighbour_is_not_a_pair() -> None:
    episode = lines(("s0", "t0"), ("s1", ""), ("s2", ""), ("s3", ""), ("s4", "t4"))
    assert context_pairs(episode, 2) == [("s0", "t0"), ("s4", "t4")]


def test_a_gap_at_the_start_of_the_file_still_gets_what_follows_it() -> None:
    episode = lines(("s0", ""), ("s1", "t1"))
    assert context_pairs(episode, 0) == [("s1", "t1")]


async def test_filling_writes_the_answers_onto_the_lines_themselves() -> None:
    episode = lines(("s0", "t0"), ("s1", ""), ("s2", "t2"))

    async def translate(text: str, pairs: list[tuple[str, str]]) -> str:
        return f"answered {text}"

    outcome = await fill_gaps(lambda: episode, translate, lambda: False, unchanged)

    assert outcome.filled == 1
    assert episode[1].translated == "answered s1"


async def test_a_line_the_model_cannot_answer_is_left_unpaired() -> None:
    # The output checks reject a translation that is noise, and the plate holding
    # the previous line beats the plate showing that.
    episode = lines(("s0", "t0"), ("s1", ""))

    async def translate(text: str, pairs: list[tuple[str, str]]) -> str:
        return ""

    outcome = await fill_gaps(lambda: episode, translate, lambda: False, unchanged)

    assert outcome.filled == 0
    assert episode[1].translated == ""


async def test_a_line_just_filled_becomes_context_for_the_next_gap() -> None:
    episode = lines(("s0", "t0"), ("s1", ""), ("s2", ""))
    seen: list[list[tuple[str, str]]] = []

    async def translate(text: str, pairs: list[tuple[str, str]]) -> str:
        seen.append(pairs)
        return f"answered {text}"

    await fill_gaps(lambda: episode, translate, lambda: False, unchanged)

    assert seen[0] == [("s0", "t0")]
    assert seen[1] == [("s0", "t0"), ("s1", "answered s1")]


async def test_filling_waits_while_a_read_is_using_the_model() -> None:
    # The engine answers one request at a time, and the viewer is waiting on the
    # read rather than on a cue that is still minutes away.
    episode = lines(("s0", "t0"), ("s1", ""))
    reading = True
    calls = 0

    async def translate(text: str, pairs: list[tuple[str, str]]) -> str:
        nonlocal calls
        calls += 1
        return "answered"

    task = asyncio.create_task(fill_gaps(lambda: episode, translate, lambda: reading, unchanged))
    await asyncio.sleep(0.05)
    assert calls == 0, "filled a gap while a read still held the model"

    reading = False
    assert (await task).filled == 1
    assert calls == 1


async def test_filling_stops_when_the_engine_stops_answering() -> None:
    episode = lines(("s0", "t0"), ("s1", ""), ("s2", ""))
    calls = 0

    async def translate(text: str, pairs: list[tuple[str, str]]) -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("engine is gone")

    outcome = await fill_gaps(lambda: episode, translate, lambda: False, unchanged)

    assert outcome.filled == 0
    assert calls == 1, "kept asking an engine that had already failed"


async def test_a_fully_paired_file_asks_the_model_nothing() -> None:
    episode = lines(("s0", "t0"), ("s1", "t1"))

    async def translate(text: str, pairs: list[tuple[str, str]]) -> str:
        raise AssertionError("nothing should have been filled")

    assert (await fill_gaps(lambda: episode, translate, lambda: False, unchanged)).filled == 0


async def test_filling_stops_when_the_session_follows_a_different_file() -> None:
    # A session with several candidates can stop following one and take another.
    # The gaps of a file that is no longer drawn are not worth an engine slot,
    # and every one spent on it is one the drawn file does not get.
    abandoned = lines(("s0", "t0"), ("s1", ""), ("s2", ""))
    taken_up = lines(("r0", "t0"), ("r1", ""))
    following = [abandoned]
    asked: list[str] = []

    async def translate(text: str, pairs: list[tuple[str, str]]) -> str:
        asked.append(text)
        following[0] = taken_up
        return f"answered {text}"

    outcome = await fill_gaps(lambda: following[0], translate, lambda: False, unchanged)

    assert asked == ["s1"], "kept filling a file the session had stopped following"
    assert outcome.filled == 1
    assert abandoned[2].translated == ""


async def test_a_file_that_answers_almost_nothing_is_not_worked_through() -> None:
    # A file leaving hundreds of cues unpaired is the wrong file, which the prep
    # card says before the session starts. Working through it would hold the
    # single-slot engine for the length of the episode.
    episode = lines(*[(f"s{i}", "") for i in range(MAX_FILLED_LINES + 30)])
    calls = 0

    async def translate(text: str, pairs: list[tuple[str, str]]) -> str:
        nonlocal calls
        calls += 1
        return "answered"

    outcome = await fill_gaps(lambda: episode, translate, lambda: False, unchanged)

    assert calls == MAX_FILLED_LINES
    assert outcome.filled == MAX_FILLED_LINES


async def test_a_pass_the_session_interrupted_is_not_counted_as_finished() -> None:
    """The watcher comes back to a file it left partway, and not to a finished one."""
    episode = lines(("s0", "t0"), ("s1", ""), ("s2", ""))
    following = [episode]

    async def translate(text: str, pairs: list[tuple[str, str]]) -> str:
        following[0] = lines(("other", ""))
        return f"answered {text}"

    outcome = await fill_gaps(lambda: following[0], translate, lambda: False, unchanged)

    assert outcome.filled == 1
    assert not outcome.completed
    assert not outcome.engine_failed


async def test_an_engine_that_stopped_answering_is_reported_as_such() -> None:
    """Told apart from an interruption, because retrying it is pointless."""
    episode = lines(("s0", "t0"), ("s1", ""))

    async def translate(text: str, pairs: list[tuple[str, str]]) -> str:
        raise RuntimeError("the engine went away")

    outcome = await fill_gaps(lambda: episode, translate, lambda: False, unchanged)

    assert outcome.filled == 0
    assert not outcome.completed
    assert outcome.engine_failed


async def test_the_gaps_ahead_of_the_viewer_are_answered_before_the_ones_behind() -> None:
    episode = lines(("s0", ""), ("s1", "t1"), ("s2", ""), ("s3", "t3"), ("s4", ""))
    asked: list[str] = []

    async def translate(text: str, pairs: list[tuple[str, str]]) -> str:
        asked.append(text)
        return f"answered {text}"

    await fill_gaps(lambda: episode, translate, lambda: False, unchanged, lambda: 2)

    assert asked == ["s2", "s4", "s0"]


async def test_without_a_position_the_files_own_order_is_the_order() -> None:
    """Before a match places the video there is nowhere else to start."""
    episode = lines(("s0", ""), ("s1", "t1"), ("s2", ""))
    asked: list[str] = []

    async def translate(text: str, pairs: list[tuple[str, str]]) -> str:
        asked.append(text)
        return f"answered {text}"

    await fill_gaps(lambda: episode, translate, lambda: False, unchanged, lambda: None)

    assert asked == ["s0", "s2"]


async def test_the_budget_goes_to_what_is_coming_rather_than_what_has_gone_by() -> None:
    """The cap is what makes the order matter: it can be spent entirely behind."""
    episode = lines(*[(f"s{index}", "") for index in range(MAX_FILLED_LINES + 10)])
    asked: list[str] = []

    async def translate(text: str, pairs: list[tuple[str, str]]) -> str:
        asked.append(text)
        return f"answered {text}"

    await fill_gaps(lambda: episode, translate, lambda: False, unchanged, lambda: 10)

    assert asked == [f"s{index}" for index in range(10, MAX_FILLED_LINES + 10)]


async def test_a_pass_that_began_blind_stops_once_a_match_places_the_video() -> None:
    """The session's filler starts before the first read, so it starts blind.

    Ending the pass is what lets the caller order the gaps left around the
    viewer; working through a list built with nowhere to start from can spend
    the whole budget behind them.
    """
    episode = lines(("s0", ""), ("s1", "t1"), ("s2", ""), ("s3", ""))
    placed: list[int | None] = [None]
    asked: list[str] = []

    async def translate(text: str, pairs: list[tuple[str, str]]) -> str:
        asked.append(text)
        placed[0] = 2
        return f"answered {text}"

    outcome = await fill_gaps(
        lambda: episode, translate, lambda: False, unchanged, lambda: placed[0]
    )

    assert asked == ["s0"]
    assert outcome.completed is False


async def test_a_pass_that_knows_where_the_video_is_runs_to_the_end() -> None:
    episode = lines(("s0", ""), ("s1", "t1"), ("s2", ""), ("s3", ""))
    asked: list[str] = []

    async def translate(text: str, pairs: list[tuple[str, str]]) -> str:
        asked.append(text)
        return f"answered {text}"

    outcome = await fill_gaps(lambda: episode, translate, lambda: False, unchanged, lambda: 2)

    assert asked == ["s2", "s3", "s0"]
    assert outcome.completed is True
