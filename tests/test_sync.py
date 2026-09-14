import asyncio
from time import monotonic
from unittest.mock import AsyncMock, MagicMock

import pytest

from meocosub2.config import AppConfig
from meocosub2.engine import EngineStartError
from meocosub2.models import SourceSubtitleCandidate, SubtitleLine, SubtitlePair
from meocosub2.sync import (
    CandidateSession,
    DirectTranslationSession,
    LiveTranslator,
    run_session_loop,
)


def make_candidate(result_id: str, lines: list[SubtitleLine]) -> SourceSubtitleCandidate:
    return SourceSubtitleCandidate(
        result_id=result_id,
        file_name=f"{result_id}.srt",
        provider="test",
        language="en",
        path=f"/tmp/{result_id}.srt",
        pair=SubtitlePair(source_lines=lines),
    )


def paired_lines() -> list[SubtitleLine]:
    return [
        SubtitleLine(index=0, start_ms=0, end_ms=3000, text="Hello there", translated="你好"),
        SubtitleLine(index=1, start_ms=3000, end_ms=6000, text="Goodbye now", translated="再见"),
    ]


def translator_factory(translator: LiveTranslator):
    async def open_it() -> LiveTranslator:
        return translator

    return open_it


def fake_translator(reply: str = "翻译"):
    client = MagicMock()
    client.translate = AsyncMock(return_value=reply)
    return translator_factory(LiveTranslator(client, "en", "zh"))


def never_translates():
    async def open_it() -> LiveTranslator:
        raise AssertionError("a paired session must not open the engine")

    return open_it


async def drive_with_source(session, config, reads: list[str]) -> list[tuple[str, str]]:
    """Run the capture loop over a fixed list of OCR reads and collect broadcasts."""
    broadcasts: list[tuple[str, str]] = []
    remaining = list(reads)

    async def ocr(_image, _language) -> str:
        if not remaining:
            # Translations run as tasks beside the loop. Giving them a few turns
            # before it unwinds is what a session gets from its next capture.
            for _ in range(3):
                await asyncio.sleep(0)
            raise asyncio.CancelledError()
        return remaining.pop(0)

    async def broadcast(text: str, source: str) -> None:
        broadcasts.append((text, source))

    import meocosub2.sync as sync_module

    original_ocr = sync_module.ocr_image
    original_capture = sync_module.capture_region
    sync_module.ocr_image = ocr
    sync_module.capture_region = lambda region: MagicMock()
    try:
        with pytest.raises(asyncio.CancelledError):
            await run_session_loop(session, config, broadcast)
    finally:
        sync_module.ocr_image = original_ocr
        sync_module.capture_region = original_capture
    return broadcasts


async def drive(session, config, reads: list[str]) -> list[str]:
    return [text for text, _ in await drive_with_source(session, config, reads)]


def config(**overrides) -> AppConfig:
    return AppConfig(capture_interval_ms=0, capture_region=[0, 0, 100, 20], **overrides)


@pytest.mark.asyncio
async def test_a_matched_line_is_broadcast_with_its_paired_translation() -> None:
    session = CandidateSession([make_candidate("a", paired_lines())], config(), never_translates())
    assert await drive(session, config(), ["Hello there"]) == ["你好"]


@pytest.mark.asyncio
async def test_a_re_read_of_the_same_line_is_not_broadcast_again() -> None:
    session = CandidateSession([make_candidate("a", paired_lines())], config(), never_translates())
    reads = ["Hello there", "Hello there", "Hello ihere"]
    assert await drive(session, config(), reads) == ["你好"]


@pytest.mark.asyncio
async def test_the_next_line_is_broadcast_when_the_cue_changes() -> None:
    session = CandidateSession([make_candidate("a", paired_lines())], config(), never_translates())
    reads = ["Hello there", "Goodbye now"]
    assert await drive(session, config(), reads) == ["你好", "再见"]


@pytest.mark.asyncio
async def test_the_overlay_clears_after_the_region_reads_empty() -> None:
    # Nothing has matched, so a run of empty reads is all there is to go on.
    session = DirectTranslationSession([], config(), fake_translator("你好"))
    assert await drive(session, config(), ["Hello there", "Hello there", "", "", ""]) == [
        "你好",
        "",
    ]


@pytest.mark.asyncio
async def test_empty_reads_do_not_blank_a_line_the_clock_is_sure_of() -> None:
    # OCR comes back empty often enough - a frame caught mid-fade, pale text on
    # a pale background - that it cannot be allowed to take down a line the
    # subtitle file says is on screen.
    session = CandidateSession([make_candidate("a", paired_lines())], config(), never_translates())
    assert await drive(session, config(), ["Hello there", "", "", ""]) == ["你好"]


@pytest.mark.asyncio
@pytest.mark.parametrize("now", [1.0, 30.0])
async def test_silence_releases_the_clock_and_same_phrase_can_match_again(monkeypatch, now) -> None:
    import meocosub2.sync as sync
    import meocosub2.timeline as timeline

    clock = 0.0
    monkeypatch.setattr(timeline, "monotonic", lambda: clock)
    monkeypatch.setattr(sync, "monotonic", lambda: clock)
    session = CandidateSession([make_candidate("a", paired_lines())], config(), never_translates())
    await drive(session, config(), ["Hello there", "", "", ""])
    clock = now
    assert session.clock_ms() == int(now * 1000) + sync.DISPLAY_LEAD_MS
    if now == 1.0:
        # Empty frames separated this phrase from its earlier read.
        session.saw_new_cue(now)
        resolution = await session.match("Hello there")
        assert resolution is not None and resolution.detail.get("confirmed")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial_index,resumed_time,completed_time,resumed_index",
    [(0, 5.0, 5.0, 1), (1, 6.0, 6.0, 1), (0, 1.0, 5.0, 0)],
)
async def test_repeated_phrase_after_silence_follows_the_nearest_occurrence(
    monkeypatch, initial_index, resumed_time, completed_time, resumed_index
) -> None:
    import meocosub2.timeline as timeline

    now = float(initial_index * 5)
    monkeypatch.setattr(timeline, "monotonic", lambda: now)
    lines = [
        SubtitleLine(0, 0, 2000, "Can you hear me", "first occurrence"),
        SubtitleLine(1, 5000, 7000, "Can you hear me", "second occurrence"),
    ]
    session = CandidateSession([make_candidate("a", lines)], config(), never_translates())
    # Establish the real position without using the ambiguous phrase itself.
    assert session._timeline.accepts(initial_index * 5000, initial_index, 100, now=now)
    session.clear_cue()
    now = resumed_time
    session.saw_new_cue(now)
    now = completed_time
    result = await session.match("Can you hear me")
    assert result is not None
    assert result.detail["matchIdx"] == resumed_index
    assert result.text == lines[resumed_index].translated


@pytest.mark.asyncio
async def test_direct_translation_reuses_target_text_after_the_phrase_disappears() -> None:
    target = [SubtitleLine(0, 0, 3000, "Please close the door.")]
    session = DirectTranslationSession(target, config(), fake_translator("Please close door"))
    assert await session.translate("关门") == "Please close the door."
    session.clear_cue()
    assert await session.translate("关门") == "Please close the door."


@pytest.mark.asyncio
async def test_expired_session_waits_for_dialogue_to_confirm_a_backward_seek(monkeypatch) -> None:
    import meocosub2.timeline as timeline

    now = 0.0
    monkeypatch.setattr(timeline, "monotonic", lambda: now)
    lines = [
        SubtitleLine(0, 100_000, 102_000, "The earlier scene begins", "earlier target"),
        SubtitleLine(1, 103_000, 105_000, "Someone answers the telephone", "recovered target"),
        SubtitleLine(2, 600_000, 603_000, "We have arrived at the station", "initial target"),
    ]
    session = CandidateSession([make_candidate("a", lines)], config(), never_translates())
    assert (await session.match(lines[2].text)).text == "initial target"
    now = timeline.ANCHOR_MAX_AGE_S + 1
    session.saw_new_cue(now)
    assert await session.match(lines[0].text) is None
    assert not session.anchored
    now += 3
    session.saw_new_cue(now)
    assert (await session.match(lines[1].text)).text == "recovered target"
    assert session.anchored


@pytest.mark.asyncio
async def test_translation_cannot_fill_a_plate_after_its_match_expires(monkeypatch) -> None:
    import meocosub2.sync as sync
    import meocosub2.timeline as timeline

    now = 0.0
    monkeypatch.setattr(timeline, "monotonic", lambda: now)
    monkeypatch.setattr(sync, "monotonic", lambda: now)
    ready = asyncio.Event()
    client = MagicMock()

    async def translate(*args):
        await ready.wait()
        return "late target"

    client.translate = AsyncMock(side_effect=translate)
    session = CandidateSession(
        [make_candidate("a", [SubtitleLine(0, 0, 3000, "The last source sentence")])],
        config(),
        translator_factory(LiveTranslator(client, "en", "zh")),
    )
    first = True
    shown = []

    async def ocr(*args):
        nonlocal first, now
        if first:
            first = False
            return "The last source sentence"
        now = timeline.ANCHOR_MAX_AGE_S + 1
        assert session.clock_ms() is None
        ready.set()
        for _ in range(5):
            await asyncio.sleep(0)
        raise asyncio.CancelledError()

    async def broadcast(text, source):
        shown.append(text)

    monkeypatch.setattr(sync, "ocr_image", ocr)
    monkeypatch.setattr(sync, "capture_region", lambda region: MagicMock())
    with pytest.raises(asyncio.CancelledError):
        await run_session_loop(session, config(), broadcast)
    assert client.translate.await_count == 1
    assert shown == []


@pytest.mark.asyncio
async def test_a_matched_line_without_a_translation_is_translated_live() -> None:
    untranslated = [SubtitleLine(index=0, start_ms=0, end_ms=3000, text="Hello there")]
    translator = fake_translator("你好")
    session = CandidateSession([make_candidate("a", untranslated)], config(), translator)
    assert await drive(session, config(), ["Hello there"]) == ["你好"]


@pytest.mark.asyncio
async def test_several_candidates_need_agreement_before_text_is_shown() -> None:
    weak = [SubtitleLine(index=0, start_ms=0, end_ms=3000, text="Hello there", translated="你好")]
    other = [
        SubtitleLine(index=0, start_ms=0, end_ms=3000, text="Total mismatch", translated="别的")
    ]
    session = CandidateSession(
        [make_candidate("a", weak), make_candidate("b", other)], config(), never_translates()
    )
    # An exact read locks candidate "a" on the first frame and shows its line.
    assert await drive(session, config(), ["Hello there"]) == ["你好"]


@pytest.mark.asyncio
async def test_direct_translation_shows_the_translated_read() -> None:
    session = DirectTranslationSession([], config(), fake_translator("你好"))
    assert await drive(session, config(), ["Hello there", "Hello there"]) == ["你好"]


@pytest.mark.asyncio
async def test_direct_translation_prefers_a_matching_target_subtitle_line() -> None:
    target = [SubtitleLine(index=7, start_ms=0, end_ms=3000, text="你好呀")]
    session = DirectTranslationSession(target, config(), fake_translator("你好呀"))
    assert await drive(session, config(), ["Hello there", "Hello there"]) == ["你好呀"]


@pytest.mark.asyncio
async def test_a_repeated_read_is_translated_only_once() -> None:
    client = MagicMock()
    client.translate = AsyncMock(return_value="你好")
    session = DirectTranslationSession(
        [], config(), translator_factory(LiveTranslator(client, "en", "zh"))
    )
    await drive(session, config(), ["Hello there", "Hello there", "Hello there"])
    assert client.translate.await_count == 1


@pytest.mark.asyncio
async def test_direct_translation_waits_for_the_fade_to_resolve() -> None:
    clean = "The cat is waiting by the window."
    translator = MagicMock()
    translator.translate = AsyncMock(return_value="猫正在窗边等待。")
    session = DirectTranslationSession([], config(), translator_factory(translator))
    reads = ["Thexat is waiting by the window.", clean, clean, clean]
    assert await drive(session, config(), reads) == ["猫正在窗边等待。"]
    translator.translate.assert_awaited_once_with(clean)


@pytest.mark.asyncio
@pytest.mark.parametrize("reads", [["Hello there"], ["Hello there", "", "Hello there"]])
async def test_direct_translation_does_not_send_an_unconfirmed_read(reads) -> None:
    translator = MagicMock()
    translator.translate = AsyncMock(return_value="你好")
    session = DirectTranslationSession([], config(), translator_factory(translator))
    assert await drive(session, config(), reads) == []
    translator.translate.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_translation_updates_after_a_paused_seek() -> None:
    first, following = "The cat is waiting by the window.", "Let us walk home together."
    translator = MagicMock()
    translator.translate = AsyncMock(side_effect=lambda text: text)
    session = DirectTranslationSession([], config(), translator_factory(translator))
    reads = [first] * 5 + [following] * 5
    assert await drive(session, config(), reads) == [first, following]
    assert [call.args[0] for call in translator.translate.await_args_list] == [first, following]


@pytest.mark.asyncio
async def test_direct_translation_returns_to_a_recent_cue_after_a_seek() -> None:
    first, following = "Let us walk home together.", "The cat is waiting by the window."
    translations = {first: "让我们一起回家吧。", following: "猫正在窗边等待。"}
    client = MagicMock()
    client.translate = AsyncMock(side_effect=lambda text, *_: translations[text])
    session = DirectTranslationSession(
        [], config(), translator_factory(LiveTranslator(client, "en", "zh"))
    )
    reads = [first] * 3 + [following] * 3 + [first] * 3
    assert await drive(session, config(), reads) == [
        translations[first],
        translations[following],
        translations[first],
    ]
    assert client.translate.await_count == 2


@pytest.mark.asyncio
async def test_direct_translation_reconfirms_a_phrase_after_silence() -> None:
    translator = MagicMock()
    translator.translate = AsyncMock(return_value="你好")
    session = DirectTranslationSession([], config(), translator_factory(translator))
    reads = ["Hello there", "Hello there", "", "", "", "Hello there", "Hello there"]
    assert await drive(session, config(), reads) == ["你好", "", "你好"]
    assert translator.translate.await_count == 2


@pytest.mark.asyncio
async def test_the_loop_follows_a_region_reselected_mid_session() -> None:
    session = CandidateSession([make_candidate("a", paired_lines())], config(), never_translates())
    regions: list[tuple[int, ...]] = []
    selected = [(0, 0, 100, 20)]

    import meocosub2.sync as sync_module

    reads = ["Hello there", "Goodbye now"]

    async def ocr(_image, _language) -> str:
        if not reads:
            raise asyncio.CancelledError()
        selected[0] = (10, 20, 30, 40)
        return reads.pop(0)

    original_ocr = sync_module.ocr_image
    original_capture = sync_module.capture_region
    sync_module.ocr_image = ocr
    sync_module.capture_region = lambda region: regions.append(region) or MagicMock()
    try:
        with pytest.raises(asyncio.CancelledError):
            await run_session_loop(
                session,
                config(),
                lambda text, source: asyncio.sleep(0),
                region_source=lambda: selected[0],
            )
    finally:
        sync_module.ocr_image = original_ocr
        sync_module.capture_region = original_capture

    assert regions[0] == (0, 0, 100, 20)
    assert regions[-1] == (10, 20, 30, 40)


@pytest.mark.asyncio
async def test_a_fully_paired_session_never_opens_the_engine() -> None:
    session = CandidateSession([make_candidate("a", paired_lines())], config(), never_translates())
    assert await drive(session, config(), ["Hello there", "Goodbye now"]) == ["你好", "再见"]


@pytest.mark.asyncio
async def test_a_read_that_matches_nothing_is_translated_and_marked_as_such() -> None:
    session = CandidateSession(
        [make_candidate("a", paired_lines())], config(), fake_translator("临时翻译")
    )
    # Nothing in the file resembles this, so the plate is filled by the model
    # rather than left blank while the viewer waits.
    assert await drive_with_source(session, config(), ["Something else entirely"]) == [
        ("临时翻译", "translated")
    ]


@pytest.mark.asyncio
async def test_a_matched_line_is_marked_as_coming_from_the_file() -> None:
    session = CandidateSession([make_candidate("a", paired_lines())], config(), never_translates())
    assert await drive_with_source(session, config(), ["Hello there"]) == [("你好", "matched")]


@pytest.mark.asyncio
async def test_a_cue_that_matches_on_a_later_read_stops_being_provisional() -> None:
    client = MagicMock()
    client.translate = AsyncMock(return_value="临时翻译")
    session = CandidateSession(
        [make_candidate("a", paired_lines())],
        config(),
        translator_factory(LiveTranslator(client, "en", "zh")),
    )
    # The first read is too damaged to match and gets a translation; the same
    # cue read again is clean, and the file's line replaces it.
    broadcasts = await drive_with_source(session, config(), ["He11o 1here", "Hello there"])
    assert broadcasts[-1] == ("你好", "matched")


@pytest.mark.asyncio
async def test_a_cue_the_file_splits_in_two_is_matched_as_the_pair() -> None:
    split = [
        SubtitleLine(
            index=0, start_ms=0, end_ms=1500, text="We should go", translated="我们该走了"
        ),
        SubtitleLine(
            index=1, start_ms=1500, end_ms=3000, text="before it gets dark", translated="趁天还没黑"
        ),
    ]
    session = CandidateSession([make_candidate("a", split)], config(), never_translates())
    shown = await drive(session, config(), ["We should go before it gets dark"])
    assert shown == ["我们该走了 趁天还没黑"]


@pytest.mark.asyncio
async def test_a_pair_sharing_one_target_line_does_not_say_it_twice() -> None:
    # Alignment pairs by time overlap, so a target file that breaks the sentence
    # elsewhere can hand both halves the same line.
    shared = [
        SubtitleLine(
            index=0, start_ms=0, end_ms=1500, text="for the rest", translated="今天剩下的时间"
        ),
        SubtitleLine(
            index=1, start_ms=1500, end_ms=3000, text="of the day", translated="今天剩下的时间"
        ),
    ]
    session = CandidateSession([make_candidate("a", shared)], config(), never_translates())
    assert await drive(session, config(), ["for the rest of the day"]) == ["今天剩下的时间"]


def episode_lines() -> list[SubtitleLine]:
    """Three cues a few seconds apart, each with a translation ready to show."""
    return [
        SubtitleLine(index=0, start_ms=0, end_ms=2000, text="Hello there", translated="你好"),
        SubtitleLine(
            index=1, start_ms=10_000, end_ms=12_000, text="Goodbye now", translated="再见"
        ),
        SubtitleLine(index=2, start_ms=20_000, end_ms=22_000, text="See you", translated="回见"),
    ]


async def test_a_read_that_matches_nothing_is_placed_by_the_clock() -> None:
    session = CandidateSession([make_candidate("a", episode_lines())], config(), never_translates())
    # One match anchors the session on the file's second line.
    assert await session.match("Goodbye now") is not None
    # The next read shares no words with the file, which is the ordinary case:
    # the burned-in subtitles are a different translation. The clock still knows
    # which line the viewer is on.
    followed = await session.match("nothing like the file")
    assert followed is not None
    assert followed.text == "再见"
    assert followed.detail["confirmed"] is False


async def test_a_repeat_read_is_never_placed_by_the_clock() -> None:
    session = CandidateSession([make_candidate("a", episode_lines())], config(), never_translates())
    assert await session.match("Goodbye now") is not None
    assert await session.match("nothing like the file", follow=False) is None


async def test_the_clock_places_nothing_before_a_match_anchors_it() -> None:
    session = CandidateSession([make_candidate("a", episode_lines())], config(), never_translates())
    assert await session.match("nothing like the file") is None


@pytest.mark.asyncio
async def test_a_followed_line_keeps_trying_to_match_until_one_confirms_it() -> None:
    session = CandidateSession([make_candidate("a", episode_lines())], config(), never_translates())
    shown = await drive_with_source(session, config(), ["Hello there", "utterly different words"])
    # Both reads put a line from the file on the plate, the second by position.
    assert [source for _, source in shown] == ["matched", "matched"]


@pytest.mark.asyncio
async def test_the_clock_plays_the_next_line_without_waiting_for_a_read() -> None:
    """Once a match has placed the video, the file plays itself forward.

    OCR does not see every cue - and even when it does, it sees it a beat after
    the picture. Holding each line until a read arrives is what left lines
    missing and the rest late.
    """
    lines = [
        SubtitleLine(index=0, start_ms=0, end_ms=150, text="Hello there", translated="你好"),
        SubtitleLine(index=1, start_ms=250, end_ms=900, text="Goodbye now", translated="再见"),
    ]
    session = CandidateSession([make_candidate("a", lines)], config(), never_translates())
    broadcasts: list[str] = []

    async def broadcast(text: str, source: str) -> None:
        broadcasts.append(text)

    reads = ["Hello there"]

    async def ocr(_image, _language) -> str:
        if reads:
            return reads.pop(0)
        # The reader stalls, as it does whenever OCR cannot make out the strip.
        await asyncio.sleep(10)
        return ""

    import meocosub2.sync as sync_module

    original_ocr, original_capture = sync_module.ocr_image, sync_module.capture_region
    original_lead = sync_module.DISPLAY_LEAD_MS
    sync_module.ocr_image = ocr
    sync_module.capture_region = lambda region: MagicMock()
    # The lag has its own test; here it would only decide how long to sleep for.
    sync_module.DISPLAY_LEAD_MS = 0
    try:
        loop = asyncio.create_task(run_session_loop(session, config(), broadcast))
        await asyncio.sleep(0.5)
        loop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop
    finally:
        sync_module.ocr_image = original_ocr
        sync_module.capture_region = original_capture
        sync_module.DISPLAY_LEAD_MS = original_lead

    assert broadcasts[0] == "你好"
    assert "再见" in broadcasts


async def test_the_plate_holds_back_by_the_display_lag() -> None:
    """Lines land a beat after the dialogue rather than a beat before it.

    Measured against a real player: the clock anchors at the moment a cue was
    first seen rather than the moment it was recognised, so it needs no help
    arriving early, and an unshifted plate read half a second ahead.
    """
    lines = [
        SubtitleLine(index=0, start_ms=0, end_ms=5_000, text="Hello there", translated="你好"),
        SubtitleLine(index=1, start_ms=5_000, end_ms=9_000, text="Goodbye now", translated="再见"),
    ]
    session = CandidateSession([make_candidate("a", lines)], config(), never_translates())
    assert await session.match("Hello there") is not None

    # Playback has just reached the second line; the plate is still on the first.
    now = monotonic() + 5.0
    assert session._timeline.position_ms(now) >= 5_000
    assert session.clock_ms(now) < 5_000


async def test_the_lag_never_reads_behind_the_line_that_anchored_the_clock() -> None:
    """Otherwise a match would blank the plate it had just filled."""
    lines = [
        SubtitleLine(index=0, start_ms=0, end_ms=2_000, text="Hello there", translated="你好"),
        SubtitleLine(
            index=1, start_ms=10_000, end_ms=12_000, text="Goodbye now", translated="再见"
        ),
    ]
    session = CandidateSession([make_candidate("a", lines)], config(), never_translates())
    assert await session.match("Goodbye now") is not None

    assert session.clock_ms() >= 10_000
    followed = session.line_now()
    assert followed is not None and followed.text == "再见"


@pytest.mark.asyncio
async def test_cues_changing_faster_than_a_poll_are_all_drawn(monkeypatch) -> None:
    """Fast dialogue changes cue faster than any poll worth running notices.

    Each line is scheduled at the timestamp the file gives it, so a cue that is
    up for barely longer than a frame still reaches the plate.
    """
    import meocosub2.sync as sync_module

    # The lead is a separate concern; zero it so this measures the scheduling.
    monkeypatch.setattr(sync_module, "DISPLAY_LEAD_MS", 0)
    lines = [
        SubtitleLine(index=0, start_ms=0, end_ms=90, text="Hello there", translated="你好"),
        # Up for 40ms, and starting between two ticks of any 100ms poll.
        SubtitleLine(index=1, start_ms=120, end_ms=160, text="Goodbye now", translated="再见"),
        SubtitleLine(index=2, start_ms=180, end_ms=380, text="See you", translated="回见"),
    ]
    session = CandidateSession([make_candidate("a", lines)], config(), never_translates())
    broadcasts: list[str] = []

    async def broadcast(text: str, source: str) -> None:
        broadcasts.append(text)

    reads = ["Hello there"]

    async def ocr(_image, _language) -> str:
        if reads:
            return reads.pop(0)
        # OCR stalls, which is the case this whole mechanism exists for.
        await asyncio.sleep(10)
        return ""

    original_ocr, original_capture = sync_module.ocr_image, sync_module.capture_region
    sync_module.ocr_image = ocr
    sync_module.capture_region = lambda region: MagicMock()
    try:
        loop = asyncio.create_task(run_session_loop(session, config(), broadcast))
        # Waited for rather than timed. A fixed window measures how quickly the
        # runner gets the first match anchored as much as it measures the
        # scheduling, and the last cue is drawn 60ms after the one before it.
        # An implementation that polls still never produces the middle cue,
        # however long this waits.
        deadline = monotonic() + 5.0
        while len([text for text in broadcasts if text]) < 3 and monotonic() < deadline:
            await asyncio.sleep(0.01)
        loop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop
    finally:
        sync_module.ocr_image = original_ocr
        sync_module.capture_region = original_capture

    assert [text for text in broadcasts if text] == ["你好", "再见", "回见"]


class StubIndex:
    """An index that is already built, standing in for the embedding engine."""

    ready = True

    def __init__(self, hit) -> None:
        self._hit = hit

    async def build(self, texts) -> None:
        return None

    async def best(self, text, indices=None):
        return self._hit


async def settled(session) -> None:
    """Wait for the background index build the session kicked off.

    Reaching for the task rather than sleeping: the build is deliberately off
    the capture loop, and a sleep long enough to be safe is a slow flaky test.
    """
    if session._semantic_build is not None:
        await session._semantic_build


async def test_a_read_no_wording_can_place_is_placed_by_meaning() -> None:
    from meocosub2.semantic import SemanticHit

    lines = episode_lines()

    async def open_index() -> StubIndex:
        return StubIndex(SemanticHit(index=1, score=0.83))

    session = CandidateSession(
        [make_candidate("a", lines)], config(), never_translates(), open_index
    )
    # The first read starts the build; nothing is matched by meaning yet.
    await session.match("Goodbye now")
    await settled(session)

    # A different translation of the same line: no shared wording at all.
    result = await session.match("So long then")

    assert result is not None
    assert result.text == "再见"
    assert result.detail["matchBy"] == "semantic"


async def test_switching_candidates_throws_away_the_index_built_for_the_old_one() -> None:
    """Its row numbers mean different lines in a different subtitle file.

    Kept across a switch, the vectors of the abandoned candidate would let the
    new one anchor the clock on an unrelated line.
    """
    from meocosub2.semantic import SemanticHit

    async def open_index() -> StubIndex:
        return StubIndex(SemanticHit(index=1, score=0.83))

    session = CandidateSession(
        [make_candidate("a", episode_lines()), make_candidate("b", episode_lines())],
        config(),
        never_translates(),
        open_index,
    )
    session._lock("a")
    await session.match("Goodbye now")
    await settled(session)
    assert session._semantic is not None

    session._lock("b")

    assert session._semantic is None
    assert session._semantic_build is None


async def test_a_session_without_the_matching_model_still_matches_on_wording() -> None:
    """A machine that never installed the model, or an adopted v1 engine."""

    async def refuse() -> StubIndex:
        raise EngineStartError("The subtitle matching model is not installed yet.")

    session = CandidateSession(
        [make_candidate("a", episode_lines())], config(), never_translates(), refuse
    )
    await session.match("Hello there")
    await settled(session)

    result = await session.match("Goodbye now")

    assert result is not None and result.text == "再见"
    assert result.detail["matchBy"] == "text"


async def test_the_viewer_can_shift_the_plate_off_the_measured_lag() -> None:
    """A player the measurement did not cover leaves the plate consistently off.

    The offset the dock sets and the measured lag answer the same question, so
    they add: raising it moves the clock forward and each line arrives sooner.
    """
    lines = [
        SubtitleLine(index=0, start_ms=0, end_ms=5_000, text="Hello there", translated="你好"),
        SubtitleLine(index=1, start_ms=5_000, end_ms=9_000, text="Goodbye now", translated="再见"),
    ]
    bias_ms = 0
    session = CandidateSession(
        [make_candidate("a", lines)],
        config(),
        never_translates(),
        bias_source=lambda: bias_ms,
    )
    assert await session.match("Hello there") is not None

    now = monotonic() + 5.0
    unshifted = session.clock_ms(now)
    assert unshifted is not None

    # Read rather than captured, so the dock retimes a session already running.
    bias_ms = 900
    shifted = session.clock_ms(now)
    assert shifted is not None
    assert shifted - unshifted == 900


async def test_asking_for_a_later_plate_is_not_swallowed_by_the_anchor_floor() -> None:
    """The floor guards a match against the measured lag, not against the viewer.

    Just after a match the floor binds, and folding the offset inside it left the
    minus button doing nothing for the 650ms-plus that follows every match -
    which, against cues that run a couple of seconds, was most of the time.
    """
    lines = [
        SubtitleLine(index=0, start_ms=0, end_ms=5_000, text="Hello there", translated="你好"),
        SubtitleLine(index=1, start_ms=5_000, end_ms=9_000, text="Goodbye now", translated="再见"),
    ]
    bias_ms = 0
    session = CandidateSession(
        [make_candidate("a", lines)],
        config(),
        never_translates(),
        bias_source=lambda: bias_ms,
    )
    assert await session.match("Hello there") is not None

    # Half a second past the match, which is where the floor is holding.
    now = monotonic() + 0.5
    held = session.clock_ms(now)
    assert held is not None

    bias_ms = -900
    later = session.clock_ms(now)
    assert later is not None
    assert later == held - 900


async def _ready(translator: "_FakeTranslator") -> "_FakeTranslator":
    return translator


class _FakeTranslator:
    """Stands in for the engine, recording what the filler asked it."""

    def __init__(self) -> None:
        self.filled: list[str] = []

    async def translate(self, text: str) -> str:
        return f"live {text}"

    async def translate_from_file(self, text: str, pairs: list[tuple[str, str]]) -> str:
        self.filled.append(text)
        return f"filled {text}"


def _gapped_candidate(result_id: str, *, with_target: bool) -> SourceSubtitleCandidate:
    """One answered cue and one nothing has an answer for.

    Without a target file nothing has answered any of them, which is what a
    live-translation session actually looks like - the cues are not gaps in a
    file, they are the whole file waiting on the model.
    """
    candidate = make_candidate(
        result_id,
        [
            SubtitleLine(
                index=0,
                start_ms=0,
                end_ms=3000,
                text="Hello there",
                translated="你好" if with_target else "",
            ),
            SubtitleLine(index=1, start_ms=3000, end_ms=6000, text="Goodbye now", translated=""),
        ],
    )
    if with_target:
        candidate.pair.target_lines = [
            SubtitleLine(index=0, start_ms=0, end_ms=3000, text="你好", translated="")
        ]
    return candidate


async def test_a_session_with_a_target_file_fills_what_it_left_unpaired() -> None:
    translator = _FakeTranslator()
    session = CandidateSession(
        [_gapped_candidate("a", with_target=True)], config(), lambda: _ready(translator)
    )

    await drive(session, config(), ["Hello there"])

    assert translator.filled == ["Goodbye now"]


async def test_a_session_without_a_target_file_never_fills_ahead() -> None:
    """Without a target file every cue is unanswered, so there is no gap to fill.

    Treating them as gaps would spend the single-slot engine on the opening of
    the file while the viewer waits on the read in front of them - which is the
    whole of what a session with no target file is doing.
    """
    translator = _FakeTranslator()
    session = CandidateSession(
        [_gapped_candidate("a", with_target=False)], config(), lambda: _ready(translator)
    )

    await drive(session, config(), ["Hello there"])

    assert translator.filled == []


async def test_filling_moves_to_the_candidate_the_session_locks_onto_next() -> None:
    """A session can let one candidate go and lock another mid-fill.

    The fill stops there, because the file it was answering is no longer drawn.
    Without picking the new one up, the file the viewer is actually reading keeps
    its gaps for the rest of the episode.
    """
    translator = _FakeTranslator()
    first = _gapped_candidate("a", with_target=True)
    second = _gapped_candidate("b", with_target=True)
    session = CandidateSession([first, second], config(), lambda: _ready(translator))
    session._locked = "a"

    relocked = False

    async def translate_from_file(text: str, pairs: list[tuple[str, str]]) -> str:
        nonlocal relocked
        translator.filled.append(text)
        if not relocked:
            relocked = True
            session._locked = "b"
        return f"filled {text}"

    session.translate_from_file = translate_from_file

    await drive(session, config(), ["Hello there"] * 12)

    # Once for the file it started on, once for the one it was moved to.
    assert translator.filled == ["Goodbye now", "Goodbye now"]
    assert second.pair.source_lines[1].translated == "filled Goodbye now"


async def test_a_candidate_that_wins_again_gets_the_gaps_its_first_pass_left(monkeypatch) -> None:
    """Coming back to a file is not the same as having finished it.

    A session lets a candidate go when reads stop agreeing with it and takes it
    again when they do. Remembering only which file was filled last leaves the
    rest of that file's gaps unfilled for the episode, because the list it hands
    back on the way back is the same object it handed back before.
    """
    import meocosub2.sync as sync_module

    # The watcher's pacing, not its behaviour: this test cannot spend a second
    # of wall clock waiting for the look that finds the candidate locked again.
    monkeypatch.setattr(sync_module, "FOLLOW_POLL_S", 0)

    translator = _FakeTranslator()
    candidate = make_candidate(
        "a",
        [
            SubtitleLine(index=0, start_ms=0, end_ms=2000, text="Hello there", translated="你好"),
            SubtitleLine(index=1, start_ms=2000, end_ms=4000, text="first gap", translated=""),
            SubtitleLine(index=2, start_ms=4000, end_ms=6000, text="second gap", translated=""),
        ],
    )
    candidate.pair.target_lines = [
        SubtitleLine(index=0, start_ms=0, end_ms=2000, text="你好", translated="")
    ]
    session = CandidateSession([candidate], config(), lambda: _ready(translator))

    async def translate_from_file(text: str, pairs: list[tuple[str, str]]) -> str:
        translator.filled.append(text)
        if len(translator.filled) == 1:
            # Reads stop agreeing, so the session lets the candidate go. The
            # pass ends there with the second gap unanswered.
            session._locked = None
        return f"filled {text}"

    session.translate_from_file = translate_from_file

    matched = 0
    original_match = session.match

    async def match(ocr_text: str, follow: bool = True):
        nonlocal matched
        matched += 1
        if matched > 3:
            # Reads agree with it again.
            session._locked = "a"
        return await original_match(ocr_text, follow=follow)

    session.match = match

    await drive(session, config(), ["Hello there"] * 20)

    assert translator.filled == ["first gap", "second gap"]


async def test_the_renderer_does_not_sleep_past_a_retime(monkeypatch) -> None:
    """Changing the offset moves every boundary the renderer already worked out.

    Nothing tells it so, and it can be asleep until a cue boundary seconds away,
    so without a bound on that sleep the plate ignores the dock until the sleep
    it was already in runs out.
    """
    import meocosub2.sync as sync_module

    lines = [
        SubtitleLine(index=0, start_ms=0, end_ms=60_000, text="Hello there", translated="你好"),
        SubtitleLine(
            index=1, start_ms=60_000, end_ms=120_000, text="Goodbye now", translated="再见"
        ),
    ]
    bias_ms = 0
    session = CandidateSession(
        [make_candidate("a", lines)],
        config(),
        never_translates(),
        bias_source=lambda: bias_ms,
    )
    assert await session.match("Hello there") is not None

    # The next boundary is a minute out, which is what the renderer would sleep
    # for. The offset reaches across it.
    assert session.seconds_to_next_line() > sync_module.RETIME_CHECK_S
    bias_ms = 61_000
    line = session.line_now()
    assert line is not None and line.text == "再见"


async def test_a_source_that_answered_itself_still_gets_its_gaps_filled() -> None:
    """A bilingual source leaves gaps too, and no target file to notice them by.

    Its answers live on the source lines, not in a target file, so a session
    that judged by `target_lines` alone saw nothing to fill and left the cues
    the file itself could not answer holding the previous line.
    """
    translator = _FakeTranslator()
    candidate = make_candidate(
        "a",
        [
            SubtitleLine(index=0, start_ms=0, end_ms=3000, text="Hello there", translated="你好"),
            SubtitleLine(index=1, start_ms=3000, end_ms=6000, text="Goodbye now", translated=""),
        ],
    )
    # Nothing was paired against it: the answer above came from its own cue.
    assert candidate.pair.target_lines == []
    session = CandidateSession([candidate], config(), lambda: _ready(translator))

    await drive(session, config(), ["Hello there"])

    assert translator.filled == ["Goodbye now"]


async def test_nothing_places_the_fill_until_a_match_places_the_video() -> None:
    session = CandidateSession([make_candidate("a", episode_lines())], config(), never_translates())
    assert session.followed_position is None


async def test_the_fill_starts_from_the_cue_the_video_has_reached() -> None:
    """A viewer who joins an episode partway is not waiting on its opening."""
    session = CandidateSession([make_candidate("a", episode_lines())], config(), never_translates())

    assert await session.match("Goodbye now") is not None

    assert session.followed_position == 1
