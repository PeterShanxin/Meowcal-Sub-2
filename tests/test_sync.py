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
    session = CandidateSession([make_candidate("a", paired_lines())], config(), never_translates())
    reads = ["Hello there", "", "", ""]
    assert await drive(session, config(), reads) == ["你好", ""]


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
