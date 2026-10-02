import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from meocosub2.auth import TOKEN_HEADER
from meocosub2.overlay.server import OverlayServer

TEST_TOKEN = "test-run-token"


@pytest.fixture(autouse=True)
def isolated_event_log(tmp_path, monkeypatch):
    """Keep test runs out of the installed app's diagnostics.

    Without this every run appends to the same file the desktop app writes, so a
    real failure is buried among events no user ever produced.
    """
    monkeypatch.setenv("MEOCOSUB2_EVENT_LOG_PATH", str(tmp_path / "meowcal-sub-2.events.jsonl"))


def studio_client(server: OverlayServer) -> TestClient:
    """A client that carries this run's token, like the studio page does."""
    return TestClient(server.app, headers={TOKEN_HEADER: TEST_TOKEN})


@pytest.fixture
def scheduler_clock(monkeypatch):
    """Advance requested renderer deadlines without host scheduling or capture IO."""
    import meocosub2.sync as sync
    import meocosub2.timeline as timeline
    from meocosub2.timeline import PlaybackState

    now = 10.0
    monkeypatch.setattr(sync, "monotonic", lambda: now)
    monkeypatch.setattr(timeline, "monotonic", lambda: now)

    class ClockEvent:
        def __init__(self):
            self._set = False

        def set(self):
            self._set = True

        def clear(self):
            self._set = False

        def is_set(self):
            return self._set

        def wait(self):
            return self

    async def advance_to_timeout(event, timeout):
        nonlocal now
        await asyncio.sleep(0)
        if event.is_set():
            return
        now += timeout
        raise TimeoutError

    clock_asyncio = SimpleNamespace(**vars(asyncio))
    clock_asyncio.Event = ClockEvent
    clock_asyncio.wait_for = advance_to_timeout
    monkeypatch.setattr(sync, "asyncio", clock_asyncio)

    class Capture:
        confidence = 1.0

        async def capture(self, grab, region, at):
            return grab(region), PlaybackState.ADVANCING

        def observe_text(self, text, at, captured):
            return captured

    monkeypatch.setattr(sync, "PlaybackCapture", lambda _: Capture())
