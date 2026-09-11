"""Sub2 adapters for translation Core and the independent BGE matcher."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any

from meocosub2.core_client import CoreClient, CoreClientError, CoreError, resolve_core_executable
from meocosub2.engine import install as embedding_install
from meocosub2.engine import runtime as embedding_runtime
from meocosub2.engine.manifest import load_manifest
from meocosub2.engine.paths import own_paths

logger = logging.getLogger(__name__)

STARTUP_TIMEOUT_S = 120.0
INSTALL_TIMEOUT_S = 1810.0
REPAIR_REQUIRED_MESSAGE = (
    "Local translation files are incomplete or damaged. Run setup from Settings to repair them."
)


EngineInstallError = embedding_install.EngineInstallError
EngineStartError = embedding_runtime.EngineStartError


@dataclass(frozen=True)
class EngineStatus:
    phase: str
    message: str
    model: str = ""
    endpoint: str | None = None
    install_percent: int = 0
    accelerator: str = ""

    @property
    def ready(self) -> bool:
        return self.phase == "ready"

    def payload(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "message": self.message,
            "model": self.model,
            "endpoint": self.endpoint,
            "ready": self.ready,
            "installPercent": self.install_percent,
            "accelerator": self.accelerator,
        }


@dataclass
class _InstallJob:
    message: str = "Preparing the translation engine..."
    percent: int = 0
    error: str = ""
    done: bool = False
    thread: threading.Thread | None = field(default=None, repr=False)


_client: CoreClient | None = None
_client_lock = threading.Lock()
_install_job: _InstallJob | None = None
_install_lock = threading.Lock()
_repair_error = ""
_translation_ready_lock = asyncio.Lock()
_ready_generation: int | None = None
_ready_endpoint: str | None = None
_embedding_start_lock = asyncio.Lock()
_embedding_install_lock = asyncio.Lock()


def _core() -> CoreClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = CoreClient(resolve_core_executable())
        return _client


def _model() -> str:
    hello = _core().hello_result
    if hello is None:
        _core().request_sync("status", {}, timeout_s=15.0)
        hello = _core().hello_result
    assert hello is not None
    return str(hello["model"])


def _status_from_result(result: dict[str, Any]) -> EngineStatus:
    model = str(result.get("model") or "")
    if result.get("ready") is True:
        acceleration = str(result.get("acceleration") or "").upper()
        managed = result.get("managedConfig")
        port = managed.get("port") if isinstance(managed, dict) else None
        endpoint = f"http://127.0.0.1:{port}" if isinstance(port, int) else None
        suffix = f" ({acceleration})" if acceleration else ""
        return EngineStatus(
            "ready",
            f"Local translation is ready{suffix}.",
            model,
            endpoint=endpoint,
            install_percent=100,
            accelerator=acceleration,
        )
    if result.get("installed") is True:
        return EngineStatus(
            "idle",
            "Local translation is installed and starts with a session.",
            model,
            install_percent=100,
        )
    return EngineStatus(
        "needsSetup",
        "Local translation needs a one-time 1.1 GB download before it can run.",
        model,
    )


def status() -> EngineStatus:
    """Return a snapshot without starting or installing the HY-MT runtime."""
    with _install_lock:
        job = _install_job
        repair_error = _repair_error
    if job is not None and not job.done:
        return EngineStatus("installing", job.message, install_percent=job.percent)
    if job is not None and job.error:
        return EngineStatus("failed", job.error)
    if repair_error:
        return EngineStatus("failed", repair_error)
    try:
        return _status_from_result(_core().request_sync("status", {}, timeout_s=15.0))
    except CoreClientError as error:
        return EngineStatus("failed", str(error))


def install_engine() -> EngineStatus:
    """Start or report the one background Core installation request."""
    current = status()
    if current.phase in {"ready", "idle", "installing"}:
        return current

    with _install_lock:
        global _install_job
        if _install_job is not None and not _install_job.done:
            return EngineStatus(
                "installing", _install_job.message, install_percent=_install_job.percent
            )
        job = _InstallJob()
        _install_job = job
    _invalidate_ready()

    def progress(message: str) -> None:
        job.message = message
        match = re.search(r"\b(\d{1,3})%", message)
        if match:
            job.percent = max(0, min(99, int(match.group(1))))

    def run() -> None:
        global _repair_error
        try:
            _core().request_sync("install", {}, timeout_s=INSTALL_TIMEOUT_S, progress=progress)
            job.percent = 100
            with _install_lock:
                _repair_error = ""
        except CoreClientError as error:
            logger.exception("Translation engine install failed")
            job.error = str(error)
        finally:
            job.done = True

    job.thread = threading.Thread(target=run, name="core-install", daemon=True)
    job.thread.start()
    return EngineStatus("installing", job.message, install_percent=job.percent)


async def ensure_ready(timeout_s: float = STARTUP_TIMEOUT_S) -> str:
    """Ask Core to verify, start, and health-check the pinned HY-MT model."""
    global _ready_endpoint, _ready_generation, _repair_error
    client = _core()
    async with _translation_ready_lock:
        generation = client.process_generation
        if generation is not None and generation == _ready_generation and _ready_endpoint:
            return _ready_endpoint
        try:
            result = await client.request("ready", {}, timeout_s=timeout_s)
        except CoreError as error:
            if "ASSET" in error.code:
                with _install_lock:
                    _repair_error = REPAIR_REQUIRED_MESSAGE
                raise EngineInstallError(str(error)) from error
            raise EngineStartError(str(error)) from error
        except CoreClientError as error:
            raise EngineStartError(str(error)) from error
        managed = result.get("managedConfig")
        generation = client.process_generation
        if (
            not isinstance(managed, dict)
            or not isinstance(managed.get("port"), int)
            or generation is None
        ):
            raise EngineStartError("Core returned an invalid ready configuration.")
        _ready_generation = generation
        _ready_endpoint = f"http://127.0.0.1:{managed['port']}"
        with _install_lock:
            _repair_error = ""
            if _install_job is not None and _install_job.done:
                _install_job.error = ""
        return _ready_endpoint


async def complete(request: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    """Send one owned OpenAI-compatible request through Core."""
    await ensure_ready()
    request = dict(request)
    request["model"] = _model()
    timeout_ms = max(1, min(90_000, int(timeout_s * 1000)))
    try:
        return await _core().request(
            "complete",
            {"request": request, "timeoutMs": timeout_ms},
            timeout_s=timeout_s + 2.0,
        )
    except CoreError as error:
        if error.code == "NOT_READY":
            _invalidate_ready()
        raise EngineStartError(str(error)) from error
    except CoreClientError as error:
        raise EngineStartError(str(error)) from error


def _invalidate_ready() -> None:
    global _ready_endpoint, _ready_generation
    _ready_generation = None
    _ready_endpoint = None


async def ensure_embedding_ready(timeout_s: float = STARTUP_TIMEOUT_S) -> str:
    """Start Sub2's independent CPU BGE model from its own verified tree."""
    manifest = load_manifest()
    runtime = manifest.runtime_for_host()
    paths = own_paths(manifest, runtime)
    if not paths.embedding_is_complete(manifest, runtime):
        async with _embedding_install_lock:
            if not paths.embedding_is_complete(manifest, runtime):
                await asyncio.to_thread(
                    embedding_install.install_embedding, paths, manifest, runtime
                )
    async with _embedding_start_lock:
        return await embedding_runtime.ensure_embedding_ready(paths, manifest, timeout_s)


def shutdown() -> None:
    """Stop every Core process and BGE process owned by this backend."""
    global _client
    with _client_lock:
        client, _client = _client, None
    _invalidate_ready()
    if client is not None:
        client.close_sync()
    embedding_runtime.shutdown()
    from meocosub2 import native_ocr

    native_ocr.shutdown()


__all__ = [
    "EngineInstallError",
    "EngineStartError",
    "EngineStatus",
    "complete",
    "ensure_embedding_ready",
    "ensure_ready",
    "install_engine",
    "shutdown",
    "status",
]
