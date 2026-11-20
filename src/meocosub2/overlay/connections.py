"""Ordered, bounded event delivery for each connected studio window."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress

from anyio import CancelScope
from fastapi import WebSocket, WebSocketDisconnect

SEND_TIMEOUT_S = 2.0
MAX_PENDING = 32


async def _send_events(socket: WebSocket, queue: asyncio.Queue[str]) -> None:
    while True:
        event = await queue.get()
        async with asyncio.timeout(SEND_TIMEOUT_S):
            await socket.send_text(event)


async def _receive_until_disconnect(socket: WebSocket) -> None:
    while True:
        await socket.receive_text()


class StudioConnections:
    def __init__(self) -> None:
        self._writers: dict[asyncio.Queue[str], asyncio.Task[None]] = {}

    def publish(self, message: dict[str, object]) -> None:
        encoded = json.dumps(message)
        for queue, writer in self._writers.items():
            try:
                queue.put_nowait(encoded)
            except asyncio.QueueFull:
                # Reconnect with a fresh snapshot instead of skipping ordered cue boundaries.
                writer.cancel()

    async def serve(self, socket: WebSocket, initial: list[dict[str, object]]) -> None:
        queue: asyncio.Queue[str] = asyncio.Queue(MAX_PENDING)
        for message in initial:
            queue.put_nowait(json.dumps(message))
        writer = asyncio.create_task(_send_events(socket, queue))
        reader = asyncio.create_task(_receive_until_disconnect(socket))
        self._writers[queue] = writer
        try:
            done, _ = await asyncio.wait((reader, writer), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if not task.cancelled():
                    with suppress(WebSocketDisconnect, OSError, TimeoutError):
                        task.result()
        finally:
            del self._writers[queue]
            reader.cancel()
            writer.cancel()
            # The ASGI host may cancel this connection while the peer disconnects.
            # Finish the bounded close and join both workers before leaving its scope.
            with CancelScope(shield=True):
                await asyncio.gather(reader, writer, return_exceptions=True)
                with suppress(WebSocketDisconnect, OSError, RuntimeError, TimeoutError):
                    async with asyncio.timeout(SEND_TIMEOUT_S):
                        await socket.close()
