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


def fake_translator(reply: str = "翻译") -> LiveTranslator:
    client = MagicMock()
    client.translate = AsyncMock(return_value=reply)
    return LiveTranslator(client, "en", "zh")


async def drive(session, config, reads: list[str]) -> list[str]:
    """Run the capture loop over a fixed list of OCR reads and collect broadcasts."""
    broadcasts: list[str] = []
    remaining = list(reads)

    async def ocr(_image, _language) -> str:
        if not remaining:
            raise asyncio.CancelledError()
        return remaining.pop(0)

    async def broadcast(text: str) -> None:
        broadcasts.append(text)

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


def config(**overrides) -> AppConfig:
    return AppConfig(capture_interval_ms=0, capture_region=[0, 0, 100, 20], **overrides)


@pytest.mark.asyncio
async def test_a_matched_line_is_broadcast_with_its_paired_translation() -> None:
    session = CandidateSession([make_candidate("a", paired_lines())], config(), None)
    assert await drive(session, config(), ["Hello there"]) == ["你好"]


@pytest.mark.asyncio
async def test_a_re_read_of_the_same_line_is_not_broadcast_again() -> None:
    session = CandidateSession([make_candidate("a", paired_lines())], config(), None)
    reads = ["Hello there", "Hello there", "Hello ihere"]
    assert await drive(session, config(), reads) == ["你好"]


@pytest.mark.asyncio
async def test_the_next_line_is_broadcast_when_the_cue_changes() -> None:
    session = CandidateSession([make_candidate("a", paired_lines())], config(), None)
    reads = ["Hello there", "Goodbye now"]
    assert await drive(session, config(), reads) == ["你好", "再见"]


@pytest.mark.asyncio
async def test_the_overlay_clears_after_the_region_reads_empty() -> None:
    session = CandidateSession([make_candidate("a", paired_lines())], config(), None)
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
        [make_candidate("a", weak), make_candidate("b", other)], config(), None
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
    session = DirectTranslationSession([], config(), LiveTranslator(client, "en", "zh"))
    await drive(session, config(), ["Hello there", "Hello there", "Hello there"])
    assert client.translate.await_count == 1


@pytest.mark.asyncio
async def test_the_loop_follows_a_region_reselected_mid_session() -> None:
    session = CandidateSession([make_candidate("a", paired_lines())], config(), None)
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
                lambda text: asyncio.sleep(0),
                region_source=lambda: selected[0],
            )
    finally:
        sync_module.ocr_image = original_ocr
        sync_module.capture_region = original_capture

    assert regions[0] == (0, 0, 100, 20)
    assert regions[-1] == (10, 20, 30, 40)
