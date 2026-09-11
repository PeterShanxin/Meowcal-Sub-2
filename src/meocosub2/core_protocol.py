"""Pinned Meowcal Core protocol constants and typed failures."""

import asyncio
import json
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any, BinaryIO

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
        "ocrRecognizeBgra",
    }
)
FRAME_BYTES = 256 * 1024
OCR_PAYLOAD_BYTES = 64 * 1024 * 1024
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


def decode_error(value: Any) -> CoreError | CoreTimeoutError:
    if not isinstance(value, dict):
        raise CoreProtocolError("Core returned an invalid error")
    code, message = value.get("code"), value.get("message")
    if not isinstance(code, str) or not isinstance(message, str):
        raise CoreProtocolError("Core returned an invalid error")
    if code.endswith("TIMEOUT"):
        return CoreTimeoutError(code, message)
    return CoreError(code, message)


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
        or not all(isinstance(capability, str) for capability in capabilities)
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


def validate_payload(method: str, params: dict[str, Any], payload: bytes) -> None:
    if method != "ocrRecognizeBgra":
        if payload:
            raise CoreProtocolError("Only OCR requests accept a binary payload")
        return
    width, height = params.get("width"), params.get("height")
    stride, timeout = params.get("stride"), params.get("timeoutMs")
    if (
        set(params) != {"language", "width", "height", "stride", "timeoutMs"}
        or not isinstance(params.get("language"), str)
        or any(type(value) is not int for value in (width, height, stride, timeout))
        or not (0 < width <= 4096 and 0 < height <= 4096)
        or stride != width * 4
        or not 1 <= timeout <= 30000
        or len(payload) != stride * height
        or len(payload) > OCR_PAYLOAD_BYTES
    ):
        raise CoreProtocolError("Invalid packed BGRA OCR request")


def write_request(
    stream: BinaryIO, request_id: int, method: str, params: dict[str, Any], payload: bytes
) -> None:
    frame = json.dumps(
        {
            "id": request_id,
            "api": CORE_API_VERSION,
            "method": method,
            "params": params,
            "payloadBytes": len(payload),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    header = (frame + "\n").encode("utf-8")
    if len(header) > FRAME_BYTES:
        raise CoreProtocolError(f"Core {method} request exceeds the protocol limit")
    # Unbuffered stdin lets termination unblock a full pipe; slices share pixels.
    for part in (header, payload):
        remaining = memoryview(part)
        while remaining:
            written = stream.write(remaining)
            if written is None or written <= 0:
                raise CoreProtocolError("Core request write made no progress")
            remaining = remaining[written:]
