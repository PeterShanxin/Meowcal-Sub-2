import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect

from meocosub2.overlay import connections
from meocosub2.overlay.connections import StudioConnections


class Window:
    def __init__(self, slow=False, fail_initial=False):
        self.writes = asyncio.Queue()
        self.started = asyncio.Event()
        self.disconnected = asyncio.Event()
        self.closed = asyncio.Event()
        self.slow = slow
        self.fail_initial = fail_initial

    async def send_text(self, text):
        self.started.set()
        if self.fail_initial:
            raise WebSocketDisconnect()
        if self.slow:
            await asyncio.Future()
        self.writes.put_nowait(json.loads(text))

    async def receive_text(self):
        await self.disconnected.wait()
        raise WebSocketDisconnect()

    async def close(self):
        self.closed.set()


@pytest.mark.parametrize("slow_exit", ["timeout", "overflow"])
async def test_healthy_window_gets_every_boundary_while_other_window_stalls(monkeypatch, slow_exit):
    monkeypatch.setattr(connections, "SEND_TIMEOUT_S", 0.1 if slow_exit == "timeout" else 60)
    monkeypatch.setattr(connections, "MAX_PENDING", 2)
    hub = StudioConnections()
    slow, healthy = Window(slow=True), Window()
    initial = [{"type": "state"}, {"type": "style"}]
    slow_task = asyncio.create_task(hub.serve(slow, initial))
    healthy_task = asyncio.create_task(hub.serve(healthy, initial))
    async with asyncio.timeout(2):
        await slow.started.wait()
        for first in initial:
            assert await healthy.writes.get() == first
        for line in ["hello", "", "goodbye"]:
            hub.publish({"text": line})
            assert await healthy.writes.get() == {"text": line}
            if slow_exit == "timeout":
                await slow.closed.wait()
        await slow_task
        healthy.disconnected.set()
        await healthy_task
    assert healthy.closed.is_set()
    assert not hub._writers


async def test_initial_send_failure_unregisters_window_and_next_window_receives_snapshot():
    hub = StudioConnections()
    failed = Window(fail_initial=True)
    await asyncio.wait_for(hub.serve(failed, [{"type": "state"}]), 1)
    assert failed.closed.is_set()
    assert not hub._writers
    reconnected = Window()
    serving = asyncio.create_task(hub.serve(reconnected, [{"text": "current"}]))
    assert await asyncio.wait_for(reconnected.writes.get(), 1) == {"text": "current"}
    reconnected.disconnected.set()
    await asyncio.wait_for(serving, 1)
