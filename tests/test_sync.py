import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from meocosub2.config import AppConfig
from meocosub2.models import SubtitleLine, SubtitlePair
from meocosub2.sync import run_sync_loop


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
