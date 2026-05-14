import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from meocosub2.config import AppConfig
from meocosub2.models import SourceSubtitleCandidate, SubtitleLine, SubtitlePair
from meocosub2.sync import run_auto_candidate_sync_loop, run_ocr_fallback_loop, run_sync_loop


def make_pair() -> SubtitlePair:
    lines = [
        SubtitleLine(index=0, start_ms=0, end_ms=3000, text="Hello", translated="你好"),
        SubtitleLine(index=1, start_ms=3000, end_ms=6000, text="World", translated="世界"),
    ]
    return SubtitlePair(source_lines=lines, target_lines=[])


@pytest.mark.asyncio
async def test_sync_loop_broadcasts_match(mocker) -> None:
    pair = make_pair()
    config = AppConfig(capture_interval_ms=50)
    broadcasts: list[str] = []

    mocker.patch("meocosub2.sync.capture_region", return_value=MagicMock())
    mocker.patch("meocosub2.sync.ocr_image", new=AsyncMock(return_value="Hello"))

    async def stop_after_one(text: str) -> None:
        broadcasts.append(text)
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await run_sync_loop(pair, config, broadcast=stop_after_one)
    assert broadcasts == ["你好"]


@pytest.mark.asyncio
async def test_sync_loop_does_not_repeat_same_line(mocker) -> None:
    pair = make_pair()
    config = AppConfig(capture_interval_ms=50)
    broadcasts: list[str] = []
    sleep = mocker.patch("meocosub2.sync.asyncio.sleep", new=AsyncMock(side_effect=[None, asyncio.CancelledError()]))
    mocker.patch("meocosub2.sync.capture_region", return_value=MagicMock())
    mocker.patch("meocosub2.sync.ocr_image", new=AsyncMock(side_effect=["Hello", "Hello"]))

    async def record(text: str) -> None:
        broadcasts.append(text)

    with pytest.raises(asyncio.CancelledError):
        await run_sync_loop(pair, config, broadcast=record)
    assert broadcasts == ["你好"]
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_sync_loop_uses_default_region_and_sleeps_remaining_interval(mocker) -> None:
    pair = make_pair()
    config = AppConfig(capture_interval_ms=1500, capture_region=[])
    sleep = mocker.patch("meocosub2.sync.asyncio.sleep", new=AsyncMock(side_effect=asyncio.CancelledError()))
    capture = mocker.patch("meocosub2.sync.capture_region", return_value=MagicMock())
    mocker.patch("meocosub2.sync.ocr_image", new=AsyncMock(return_value="Hello"))
    mocker.patch("meocosub2.sync.monotonic", side_effect=[0.0, 0.5])

    with pytest.raises(asyncio.CancelledError):
        await run_sync_loop(pair, config, broadcast=AsyncMock())
    capture.assert_called_once_with((0, 800, 1920, 200))
    sleep.assert_awaited_once_with(1.0)


@pytest.mark.asyncio
async def test_auto_candidate_sync_loop_locks_from_one_strong_frame(mocker) -> None:
    candidates = [
        SourceSubtitleCandidate(
            result_id="wrong",
            file_name="wrong.srt",
            provider="SubDL",
            language="en",
            path="wrong.srt",
            pair=SubtitlePair(
                source_lines=[SubtitleLine(index=0, start_ms=0, end_ms=3000, text="A distant unrelated line", translated="錯誤")]
            ),
        ),
        SourceSubtitleCandidate(
            result_id="right",
            file_name="right.srt",
            provider="OpenSubtitles",
            language="en",
            path="right.srt",
            pair=SubtitlePair(
                source_lines=[SubtitleLine(index=0, start_ms=0, end_ms=3000, text="The hero arrives now", translated="英雄到了")]
            ),
        ),
    ]
    config = AppConfig(capture_interval_ms=50, fuzzy_threshold=65)
    mocker.patch("meocosub2.sync.capture_region", return_value=MagicMock())
    mocker.patch("meocosub2.sync.ocr_image", new=AsyncMock(return_value="The hero arrives now"))

    async def stop_after_one(text: str) -> None:
        assert text == "英雄到了"
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await run_auto_candidate_sync_loop(candidates, config, broadcast=stop_after_one)


@pytest.mark.asyncio
async def test_ocr_fallback_loop_matches_target_subtitle_and_dedupes_repeated_frames(mocker) -> None:
    config = AppConfig(capture_interval_ms=50)
    target_lines = [SubtitleLine(index=0, start_ms=0, end_ms=3000, text="hello target")]
    broadcasts: list[str] = []
    sleep = mocker.patch("meocosub2.sync.asyncio.sleep", new=AsyncMock(side_effect=[None, asyncio.CancelledError()]))
    fake_client = type("FakeClient", (), {"close": AsyncMock()})()
    mocker.patch("meocosub2.sync.open_translation_client", new=AsyncMock(return_value=(fake_client, "model")))
    mocker.patch("meocosub2.sync.capture_region", return_value=MagicMock())
    mocker.patch("meocosub2.sync.ocr_image", new=AsyncMock(side_effect=["原文字幕", "原文字幕"]))
    translate = mocker.patch("meocosub2.sync.translate_text", new=AsyncMock(return_value="hello target"))

    async def record(text: str) -> None:
        broadcasts.append(text)

    with pytest.raises(asyncio.CancelledError):
        await run_ocr_fallback_loop(target_lines, config, broadcast=record)

    assert broadcasts == ["hello target"]
    translate.assert_awaited_once()
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_ocr_fallback_loop_falls_back_to_live_translation_when_no_target_match(mocker) -> None:
    config = AppConfig(capture_interval_ms=50)
    target_lines = [SubtitleLine(index=0, start_ms=0, end_ms=3000, text="subtitle text")]
    fake_client = type("FakeClient", (), {"close": AsyncMock()})()
    mocker.patch("meocosub2.sync.open_translation_client", new=AsyncMock(return_value=(fake_client, "model")))
    mocker.patch("meocosub2.sync.capture_region", return_value=MagicMock())
    mocker.patch("meocosub2.sync.ocr_image", new=AsyncMock(return_value="原文字幕"))
    mocker.patch("meocosub2.sync.translate_text", new=AsyncMock(return_value="instant translation"))

    async def stop_after_one(text: str) -> None:
        assert text == "instant translation"
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await run_ocr_fallback_loop(target_lines, config, broadcast=stop_after_one)
