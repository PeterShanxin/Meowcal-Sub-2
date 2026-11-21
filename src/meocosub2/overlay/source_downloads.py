"""Share source downloads between inspection and playback preparation for one search."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from meocosub2.subtitle_sources import AggregatedSubtitleResult


class SourceDownloads:
    def __init__(self) -> None:
        self._files: dict[str, asyncio.Task[Path]] = {}

    def clear(self) -> None:
        for task in self._files.values():
            task.cancel()
        self._files.clear()

    async def get(
        self,
        entry: AggregatedSubtitleResult,
        download: Callable[[AggregatedSubtitleResult], Coroutine[Any, Any, Path]],
    ) -> Path:
        key = entry.result_id
        task = self._files.get(key)
        if (
            task
            and task.done()
            and (task.cancelled() or task.exception() is not None or not task.result().is_file())
        ):
            task = None
        if task is None:
            task = asyncio.create_task(download(entry))
            self._files[key] = task
            # A cancelled HTTP caller can leave the shared lookup without a waiter.
            task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            path = await asyncio.shield(task)
        except asyncio.CancelledError:
            if self._files.get(key) is task:
                raise
            raise ValueError(
                "These results are out of date. Search again to pick a title."
            ) from None
        if self._files.get(key) is not task:
            raise ValueError("These results are out of date. Search again to pick a title.")
        return path
