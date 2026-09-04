"""Managed local translation engine (Tencent HY-MT1.5 on llama-server).

The app owns the engine process: it installs the artifacts, starts the server on a
loopback port, health-checks it, and stops it when the app exits. Nothing about the
translation path requires the user to run a server by hand.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field

from meocosub2.engine import install as install_module
from meocosub2.engine import runtime as runtime_module
from meocosub2.engine.install import EngineInstallError
from meocosub2.engine.manifest import UnsupportedHost, load_manifest
from meocosub2.engine.paths import resolve_paths
from meocosub2.engine.runtime import EngineStartError, shutdown

logger = logging.getLogger(__name__)

STARTUP_TIMEOUT_S = 120.0

__all__ = [
    "EngineInstallError",
    "EngineStartError",
    "EngineStatus",
    "ensure_ready",
    "install_engine",
    "shutdown",
    "status",
]


@dataclass(frozen=True)
class EngineStatus:
    """What the product can honestly say about the translation engine right now."""

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


_install_job: _InstallJob | None = None
_install_lock = threading.Lock()
_start_lock = asyncio.Lock()


def _accelerator_label() -> str:
    return "GPU" if runtime_module.active_gpu_active() else "CPU"


def status() -> EngineStatus:
    """A synchronous snapshot. Never starts or installs anything."""
    try:
        manifest = load_manifest()
        runtime = manifest.runtime_for_host()
    except UnsupportedHost as error:
        return EngineStatus("unsupported", str(error))

    model = manifest.model.id
    with _install_lock:
        job = _install_job
    if job is not None and not job.done:
        return EngineStatus("installing", job.message, model, install_percent=job.percent)
    if job is not None and job.error:
        return EngineStatus("failed", job.error, model)

    endpoint = runtime_module.active_endpoint()
    if endpoint is not None:
        return EngineStatus(
            "ready",
            f"Local translation is ready ({_accelerator_label()}).",
            model,
            endpoint=endpoint,
            install_percent=100,
            accelerator=_accelerator_label(),
        )

    paths = resolve_paths(manifest, runtime)
    if paths.is_complete(manifest, runtime):
        return EngineStatus("idle", "Local translation is installed and starts with a session.", model, install_percent=100)
    return EngineStatus(
        "needsSetup",
        "Local translation needs a one-time 1.1 GB download before it can run.",
        model,
    )


def install_engine() -> EngineStatus:
    """Start (or report) the background download of the engine artifacts."""
    manifest = load_manifest()
    runtime = manifest.runtime_for_host()
    paths = resolve_paths(manifest, runtime)
    if paths.is_complete(manifest, runtime):
        return status()

    with _install_lock:
        global _install_job
        already_running = _install_job is not None and not _install_job.done
        if not already_running:
            job = _InstallJob()
            _install_job = job
    if already_running:
        # A second request while the download runs reports on the one in flight.
        # `status()` takes the same lock, so it must be called outside it.
        return status()

    def progress(message: str, percent: int) -> None:
        job.message = message
        job.percent = percent

    def run() -> None:
        try:
            install_module.install(paths, manifest, runtime, progress)
        except (EngineInstallError, OSError) as error:
            logger.exception("Translation engine install failed")
            job.error = str(error)
        finally:
            job.done = True

    job.thread = threading.Thread(target=run, name="engine-install", daemon=True)
    job.thread.start()
    return status()


async def ensure_ready(timeout_s: float = STARTUP_TIMEOUT_S) -> str:
    """Return a healthy engine endpoint, starting the process if needed.

    Installation is never implicit: a machine without the artifacts is told to run
    setup rather than silently pulling 1.1 GB in the middle of a session.
    """
    manifest = load_manifest()
    runtime = manifest.runtime_for_host()
    paths = resolve_paths(manifest, runtime)
    if not paths.is_complete(manifest, runtime):
        raise EngineStartError(
            "Local translation is not installed yet. Run setup from Settings to "
            "download the translation engine."
        )
    async with _start_lock:
        endpoint = await runtime_module.ensure_ready(paths, manifest, runtime, timeout_s)
    logger.info("Translation engine ready at %s (%s)", endpoint, _accelerator_label())
    return endpoint
