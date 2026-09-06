import asyncio
from unittest.mock import AsyncMock

import pytest

from meocosub2.config import AppConfig
from meocosub2.models import SubtitleLine
from meocosub2.prefill import fill_before_the_session


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


class Answering:
    async def translate_from_file(self, text: str, pairs: list[tuple[str, str]]) -> str:
        return f"answered {text}"


def open_returning(translator, mocker) -> AsyncMock:
    """The engine client the fill opens, so a test can watch it being closed."""
    client = AsyncMock()
    mocker.patch(
        "meocosub2.prefill.open_live_translator",
        new=AsyncMock(return_value=(client, translator)),
    )
    return client


async def test_the_unpaired_cues_are_answered_and_each_one_reported(mocker) -> None:
    episode = lines(("s0", "t0"), ("s1", ""), ("s2", "t2"), ("s3", ""))
    client = open_returning(Answering(), mocker)
    reported: list[int] = []

    async def progress(filled: int) -> None:
        reported.append(filled)

    outcome = await fill_before_the_session(episode, AppConfig(), progress)

    assert outcome.filled == 2
    assert [line.translated for line in episode] == ["t0", "answered s1", "t2", "answered s3"]
    assert reported == [1, 2]
    client.close.assert_awaited_once()


async def test_the_engine_client_is_let_go_when_the_session_starts(mocker) -> None:
    """Cancelled the moment sync starts, which must not leave the client open."""
    asking = asyncio.Event()

    class Blocking:
        async def translate_from_file(self, text: str, pairs: list[tuple[str, str]]) -> str:
            asking.set()
            await asyncio.Event().wait()
            return ""

    episode = lines(("s0", "t0"), ("s1", ""))
    client = open_returning(Blocking(), mocker)

    async def progress(filled: int) -> None:
        return None

    task = asyncio.create_task(fill_before_the_session(episode, AppConfig(), progress))
    await asking.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert episode[1].translated == ""
    client.close.assert_awaited_once()
