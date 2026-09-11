"""Pinned Meowcal Core protocol constants and typed failures."""

import asyncio
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

CORE_API_VERSION = 1
CORE_VERSION = "0.1.0"
CORE_CAPABILITIES = frozenset(
    {
        "status",
        "install",
        "ready",
        "complete",
        "shutdown",
        "ocrInitialize",
        "ocrLanguages",
        "ocrRecognize",
    }
)
FRAME_BYTES = 256 * 1024
OCR_FRAME_BYTES = 96 * 1024 * 1024
PROGRESS_CHARS = 4096


class CoreClientError(RuntimeError):
    """The Core process or its protocol could not satisfy a request."""


class CoreError(CoreClientError):
    """A typed error returned by Core."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CoreTimeoutError(TimeoutError, CoreClientError):
    """Core or its owned native operation exceeded a bounded deadline."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CoreProtocolError(CoreClientError):
    """Core ended or returned a frame outside the pinned protocol."""


def hello_params(
    client: str,
    profile: str,
    expected_version: str,
    legacy_roots: Iterable[Path],
    storage_root: Path | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "client": client,
        "profile": profile,
        "expectedVersion": expected_version,
        "legacyRoots": [str(path) for path in legacy_roots],
    }
    if storage_root is not None:
        params["storageRoot"] = str(storage_root)
    return params


def validate_hello(value: Any, expected_version: str) -> None:
    if not isinstance(value, dict):
        raise CoreProtocolError("Core hello result must be an object")
    capabilities = value.get("capabilities")
    if (
        value.get("version") != expected_version
        or value.get("api") != CORE_API_VERSION
        or not isinstance(capabilities, list)
        or set(capabilities) != CORE_CAPABILITIES
        or not isinstance(value.get("model"), str)
        or not value["model"]
        or not isinstance(value.get("storageRoot"), str)
        or not Path(value["storageRoot"]).is_absolute()
    ):
        raise CoreProtocolError("Core hello does not match the pinned contract")


async def settle_core_task(task: asyncio.Task[dict[str, Any]]) -> None:
    with suppress(CoreClientError, OSError, ValueError):
        await task
