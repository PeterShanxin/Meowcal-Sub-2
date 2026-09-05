import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from meocosub2.config import AppConfig
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
    assert await drive(session, config(), ["Hello there", "", "", ""]) == ["你好", ""]


@pytest.mark.asyncio
async def test_empty_reads_do_not_blank_a_line_the_clock_is_sure_of() -> None:
    # OCR comes back empty often enough - a frame caught mid-fade, pale text on
    # a pale background - that it cannot be allowed to take down a line the
    # subtitle file says is on screen.
    session = CandidateSession([make_candidate("a", paired_lines())], config(), never_translates())
    assert await drive(session, config(), ["Hello there", "", "", ""]) == ["你好"]


@pytest.mark.asyncio
async def test_a_matched_line_without_a_translation_is_translated_live() -> None:
    untranslated = [SubtitleLine(index=0, start_ms=0, end_ms=3000, text="Hello there")]
    translator = fake_translator("你好")
    session = CandidateSession([make_candidate("a", untranslated)], config(), translator)
    assert await drive(session, config(), ["Hello there"]) == ["你好"]


@pytest.mark.asyncio
async def test_several_candidates_need_agreement_before_text_is_shown() -> None:
    weak = [SubtitleLine(index=0, start_ms=0, end_ms=3000, text="Hello there", translated="你好")]
    other = [SubtitleLine(index=0, start_ms=0, end_ms=3000, text="Total mismatch", translated="别的")]
    session = CandidateSession(
        [make_candidate("a", weak), make_candidate("b", other)], config(), never_translates()
    )
    # An exact read locks candidate "a" on the first frame and shows its line.
    assert await drive(session, config(), ["Hello there"]) == ["你好"]


@pytest.mark.asyncio
async def test_direct_translation_shows_the_translated_read() -> None:
    session = DirectTranslationSession([], config(), fake_translator("你好"))
    assert await drive(session, config(), ["Hello there"]) == ["你好"]


@pytest.mark.asyncio
async def test_direct_translation_prefers_a_matching_target_subtitle_line() -> None:
    target = [SubtitleLine(index=7, start_ms=0, end_ms=3000, text="你好呀")]
    session = DirectTranslationSession(target, config(), fake_translator("你好呀"))
    assert await drive(session, config(), ["Hello there"]) == ["你好呀"]


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
    session = CandidateSession(
        [make_candidate("a", paired_lines())], config(), never_translates()
    )
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
        SubtitleLine(index=0, start_ms=0, end_ms=1500, text="We should go", translated="我们该走了"),
        SubtitleLine(index=1, start_ms=1500, end_ms=3000, text="before it gets dark", translated="趁天还没黑"),
    ]
    session = CandidateSession([make_candidate("a", split)], config(), never_translates())
    shown = await drive(session, config(), ["We should go before it gets dark"])
    assert shown == ["我们该走了 趁天还没黑"]


@pytest.mark.asyncio
async def test_a_pair_sharing_one_target_line_does_not_say_it_twice() -> None:
    # Alignment pairs by time overlap, so a target file that breaks the sentence
    # elsewhere can hand both halves the same line.
    shared = [
        SubtitleLine(index=0, start_ms=0, end_ms=1500, text="for the rest", translated="今天剩下的时间"),
        SubtitleLine(index=1, start_ms=1500, end_ms=3000, text="of the day", translated="今天剩下的时间"),
    ]
    session = CandidateSession([make_candidate("a", shared)], config(), never_translates())
    assert await drive(session, config(), ["for the rest of the day"]) == ["今天剩下的时间"]


def episode_lines() -> list[SubtitleLine]:
    """Three cues a few seconds apart, each with a translation ready to show."""
    return [
        SubtitleLine(index=0, start_ms=0, end_ms=2000, text="Hello there", translated="你好"),
        SubtitleLine(index=1, start_ms=10_000, end_ms=12_000, text="Goodbye now", translated="再见"),
        SubtitleLine(index=2, start_ms=20_000, end_ms=22_000, text="See you", translated="回见"),
    ]


def test_a_read_that_matches_nothing_is_placed_by_the_clock() -> None:
    session = CandidateSession([make_candidate("a", episode_lines())], config(), never_translates())
    # One match anchors the session on the file's second line.
    assert session.match("Goodbye now") is not None
    # The next read shares no words with the file, which is the ordinary case:
    # the burned-in subtitles are a different translation. The clock still knows
    # which line the viewer is on.
    followed = session.match("nothing like the file")
    assert followed is not None
    assert followed.text == "再见"
    assert followed.detail["confirmed"] is False


def test_a_repeat_read_is_never_placed_by_the_clock() -> None:
    session = CandidateSession([make_candidate("a", episode_lines())], config(), never_translates())
    assert session.match("Goodbye now") is not None
    assert session.match("nothing like the file", follow=False) is None


def test_the_clock_places_nothing_before_a_match_anchors_it() -> None:
    session = CandidateSession([make_candidate("a", episode_lines())], config(), never_translates())
    assert session.match("nothing like the file") is None


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
    sync_module.ocr_image = ocr
    sync_module.capture_region = lambda region: MagicMock()
    try:
        loop = asyncio.create_task(run_session_loop(session, config(), broadcast))
        await asyncio.sleep(0.5)
        loop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop
    finally:
        sync_module.ocr_image = original_ocr
        sync_module.capture_region = original_capture

    assert broadcasts[0] == "你好"
    assert "再见" in broadcasts


def test_the_lead_draws_the_line_the_video_is_about_to_reach() -> None:
    """The plate runs slightly ahead of the clock, on purpose.

    The clock anchors to the read that first saw a cue, and the cue can have
    gone up any time since the previous capture, so an unshifted clock draws
    every line a fraction late.
    """
    lines = [
        SubtitleLine(index=0, start_ms=0, end_ms=200, text="Hello there", translated="你好"),
        SubtitleLine(index=1, start_ms=300, end_ms=500, text="Goodbye now", translated="再见"),
    ]
    session = CandidateSession([make_candidate("a", lines)], config(), never_translates())
    assert session.match("Hello there") is not None

    # Anchored at the first line, but the lead has already reached the second.
    assert session.clock_ms() >= 300
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
        await asyncio.sleep(0.45)
        loop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop
    finally:
        sync_module.ocr_image = original_ocr
        sync_module.capture_region = original_capture

    assert [text for text in broadcasts if text] == ["你好", "再见", "回见"]
