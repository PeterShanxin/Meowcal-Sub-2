"""Owned llama-server lifecycle for Sub2's independent BGE matcher."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx

from meocosub2.core_process import attach_process_to_lifetime, close_process_job, terminate_process
from meocosub2.engine import orphans
from meocosub2.engine.manifest import Manifest
from meocosub2.engine.paths import InstallPaths

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
HEALTH_TIMEOUT_S = 2.0
RESERVED_CORES = 4
MIN_ENGINE_THREADS = 4

_lock = threading.Lock()
_owned: _OwnedEngine | None = None
_swept = False


@dataclass
class _OwnedEngine:
    process: subprocess.Popen
    executable: str
    model: str
    port: int

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def is_running(self) -> bool:
        return self.process.poll() is None


class EngineStartError(RuntimeError):
    """The subtitle matching process could not become ready."""


def worker_threads(available_cores: int) -> int:
    return max(available_cores - RESERVED_CORES, MIN_ENGINE_THREADS)


@dataclass(frozen=True)
class LaunchPlan:
    executable: Path
    model: Path
    alias: str
    host: str
    preferred_port: int
    context_size: int
    extra_args: tuple[str, ...]


def embedding_plan(paths: InstallPaths, manifest: Manifest) -> LaunchPlan:
    return LaunchPlan(
        executable=paths.executable,
        model=paths.embedding_model,
        alias=manifest.embedding.id,
        host=manifest.host,
        preferred_port=manifest.embedding.preferred_port,
        context_size=manifest.embedding.context_size,
        extra_args=manifest.embedding.extra_args,
    )


def launch_arguments(plan: LaunchPlan, port: int) -> list[str]:
    arguments = [
        "-m",
        str(plan.model),
        "--alias",
        plan.alias,
        "--host",
        plan.host,
        "--port",
        str(port),
        "-c",
        str(plan.context_size),
        "-ngl",
        "0",
        *plan.extra_args,
    ]
    if "--threads" not in arguments and "-t" not in arguments:
        arguments += ["--threads", str(worker_threads(os.cpu_count() or 1))]
    return arguments


def select_loopback_port(preferred: int) -> int:
    for candidate in (preferred, 0):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", candidate))
                return probe.getsockname()[1]
        except OSError:
            continue
    raise EngineStartError("No loopback port was available for subtitle matching.")


async def is_endpoint_healthy(base_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT_S) as client:
            response = await client.get(f"{base_url}/health")
            return response.is_success
    except httpx.HTTPError:
        return False


def active_endpoint() -> str | None:
    global _owned
    with _lock:
        if _owned is None:
            return None
        if not _owned.is_running():
            close_process_job(_owned.process)
            _owned = None
            return None
        return _owned.base_url


def shutdown() -> None:
    global _owned
    with _lock:
        engine, _owned = _owned, None
    if engine is None:
        return
    logger.info("Stopping the subtitle matching engine (pid=%s)", engine.process.pid)
    engine.process.terminate()
    try:
        engine.process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        engine.process.kill()
        engine.process.wait(timeout=3)
    finally:
        close_process_job(engine.process)


def _start(plan: LaunchPlan, paths: InstallPaths) -> _OwnedEngine:
    global _owned
    shutdown()
    if not plan.executable.is_file():
        raise EngineStartError(f"Subtitle matching runtime is missing: {plan.executable}")
    if not plan.model.is_file():
        raise EngineStartError(f"Subtitle matching model is missing: {plan.model}")

    port = select_loopback_port(plan.preferred_port)
    log_dir = paths.executable.parent
    log_dir.mkdir(parents=True, exist_ok=True)
    with (
        open(log_dir / "embedding-server.log", "a", encoding="utf-8") as stdout,
        open(log_dir / "embedding-server.err.log", "a", encoding="utf-8") as stderr,
    ):
        process = subprocess.Popen(
            [str(plan.executable), *launch_arguments(plan, port)],
            cwd=str(plan.executable.parent),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=CREATE_NO_WINDOW,
        )
    try:
        attach_process_to_lifetime(process)
    except OSError as error:
        terminate_process(process)
        raise EngineStartError(f"Subtitle matching process ownership failed: {error}") from error
    engine = _OwnedEngine(process, str(plan.executable), str(plan.model), port)
    with _lock:
        _owned = engine
    return engine


def _sweep_once(executable: Path) -> None:
    global _swept
    with _lock:
        if _swept:
            return
        _swept = True
    ended = orphans.reap(executable)
    if ended:
        logger.info("Ended %d subtitle matching process(es) left by earlier runs", ended)


async def ensure_embedding_ready(paths: InstallPaths, manifest: Manifest, timeout_s: float) -> str:
    endpoint = active_endpoint()
    if endpoint and await is_endpoint_healthy(endpoint):
        return endpoint
    await asyncio.to_thread(_sweep_once, paths.executable)
    engine = await asyncio.to_thread(_start, embedding_plan(paths, manifest), paths)
    loop = asyncio.get_running_loop()
    limit = loop.time() + timeout_s
    while loop.time() < limit:
        if not engine.is_running():
            break
        if await is_endpoint_healthy(engine.base_url):
            return engine.base_url
        await asyncio.sleep(0.5)
    shutdown()
    raise EngineStartError(
        f"The subtitle matching model did not become ready within {timeout_s:.0f} seconds."
    )
