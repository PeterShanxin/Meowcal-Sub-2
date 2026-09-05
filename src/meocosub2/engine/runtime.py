"""Process lifecycle for the managed HY-MT translation engine.

Ported from the Meowcal Sub v1 Rust runtime: same llama-server argument vector,
same dynamic-loopback port policy, same GPU-then-CPU startup fallback, and the
same rule that the engine is only ever the child this process spawned.
"""

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

from meocosub2.engine import orphans
from meocosub2.engine.manifest import ADRENO_RUNTIME_ID, Manifest, Runtime
from meocosub2.engine.paths import InstallPaths

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
HEALTH_TIMEOUT_S = 2.0
# Measured v1 GPU readiness is 3-6s, ~11s under load. A GPU start that misses this
# window is retried on CPU inside the caller's overall deadline.
GPU_STARTUP_MAX_S = 30.0
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
    gpu_active: bool

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def is_running(self) -> bool:
        return self.process.poll() is None


class EngineStartError(RuntimeError):
    """The engine could not be started or did not become ready."""


def worker_threads(available_cores: int) -> int:
    return max(available_cores - RESERVED_CORES, MIN_ENGINE_THREADS)


def launch_arguments(
    paths: InstallPaths,
    manifest: Manifest,
    runtime: Runtime,
    port: int,
    gpu_layers: int,
    policy_args: tuple[str, ...],
) -> list[str]:
    arguments = [
        "-m",
        str(paths.model),
        "--alias",
        manifest.model.id,
        "--host",
        manifest.host,
        "--port",
        str(port),
        "-c",
        str(manifest.context_size),
        "-ngl",
        str(gpu_layers),
        *manifest.extra_args,
    ]
    # llama.cpp takes the last --threads it parses; a manifest that pins one wins.
    if "--threads" not in arguments and "-t" not in arguments:
        arguments += ["--threads", str(worker_threads(os.cpu_count() or 1))]
    arguments += list(policy_args)
    return arguments


def gpu_launch_supported(runtime: Runtime) -> bool:
    """Whether this host may run the runtime's GPU policy.

    v1 benchmarked full-layer Adreno offload on exactly one GPU and driver
    combination and gated the policy on it; every other machine, and every
    enumeration failure, starts on CPU.
    """
    if runtime.gpu_layers <= 0:
        return False
    if runtime.id != ADRENO_RUNTIME_ID:
        return True
    return _validated_adreno_present()


def _validated_adreno_present() -> bool:
    if os.name != "nt":
        return False
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_VideoController | "
                "ForEach-Object { \"$($_.Name)|$($_.DriverVersion)\" }",
            ],
            capture_output=True,
            text=True,
            timeout=10.0,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    for line in (completed.stdout or "").splitlines():
        name, _, driver = line.partition("|")
        if "Adreno" in name and "X1-85" in name and driver.strip() == "31.0.148.0":
            return True
    return False


def select_loopback_port(preferred: int) -> int:
    for candidate in (preferred, 0):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", candidate))
                return probe.getsockname()[1]
        except OSError:
            continue
    raise EngineStartError("No loopback port was available for the translation engine.")


def _attach_to_process_lifetime(process: subprocess.Popen) -> None:
    """Tie the engine to this process so it cannot outlive a crash or a force-kill."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    class _JobObjectBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in
                    ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                     "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _JobObjectExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JobObjectBasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    JobObjectExtendedLimitInformation = 9
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Declaring the signatures is not tidiness. Undeclared, ctypes assumes a
    # 32-bit signed int return, so a handle above 2GB comes back sign-extended
    # into a different value - and the job would then be armed and assigned
    # against handles that are not the ones Windows gave us.
    kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        logger.debug("Engine job object could not be created; engine may outlive a crash.")
        return
    info = _JobObjectExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
    ):
        # A job that does not kill on close is worse than none: the engine would
        # join it, still outlive us, and we would have logged success.
        logger.debug("Engine job object could not be armed; engine may outlive a crash.")
        kernel32.CloseHandle(job)
        return
    # Reopening by PID is safe here and nowhere else: Popen holds a handle to the
    # child, so the kernel cannot recycle its PID onto a stranger between the
    # spawn and this call.
    handle = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, process.pid)
    if not handle:
        kernel32.CloseHandle(job)
        return
    assigned = kernel32.AssignProcessToJobObject(job, handle)
    kernel32.CloseHandle(handle)
    if not assigned:
        logger.debug("Engine could not be assigned to its job; it may outlive a crash.")
        kernel32.CloseHandle(job)
        return
    # The job handle is deliberately leaked: the kill-on-close limit fires when the
    # last handle to it closes, which is when this process dies for any reason.
    process._meowcal_job_handle = job  # noqa: SLF001 - keeps the handle alive with the child


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
            _owned = None
            return None
        return _owned.base_url


def active_gpu_active() -> bool:
    with _lock:
        return bool(_owned and _owned.is_running() and _owned.gpu_active)


def shutdown() -> None:
    global _owned
    with _lock:
        engine = _owned
        _owned = None
    if engine is None:
        return
    logger.info("Stopping managed translation engine (pid=%s)", engine.process.pid)
    engine.process.terminate()
    try:
        engine.process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        engine.process.kill()


def _start(
    paths: InstallPaths,
    manifest: Manifest,
    runtime: Runtime,
    force_cpu: bool,
) -> _OwnedEngine:
    global _owned
    if not paths.executable.is_file():
        raise EngineStartError(f"Translation runtime is missing: {paths.executable}")
    if not paths.model.is_file():
        raise EngineStartError(f"Translation model is missing: {paths.model}")

    gpu_active = not force_cpu and gpu_launch_supported(runtime)
    gpu_layers = runtime.gpu_layers if gpu_active else 0
    policy_args = runtime.launch_args if gpu_active else ()
    port = select_loopback_port(manifest.preferred_port)
    log_dir = _log_directory(paths)
    arguments = launch_arguments(paths, manifest, runtime, port, gpu_layers, policy_args)

    logger.info(
        "Starting translation engine on port %d (%s)",
        port,
        "Adreno GPU" if gpu_active else "CPU",
    )
    with open(log_dir / "hy-mt-server.log", "a", encoding="utf-8") as stdout, open(
        log_dir / "hy-mt-server.err.log", "a", encoding="utf-8"
    ) as stderr:
        process = subprocess.Popen(
            [str(paths.executable), *arguments],
            cwd=str(paths.executable.parent),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=CREATE_NO_WINDOW,
        )
    _attach_to_process_lifetime(process)
    engine = _OwnedEngine(
        process=process,
        executable=str(paths.executable),
        model=str(paths.model),
        port=port,
        gpu_active=gpu_active,
    )
    with _lock:
        _owned = engine
    return engine


def _log_directory(paths: InstallPaths) -> Path:
    """Engine logs go beside our own install; an adopted v1 tree is never written to."""
    directory = paths.executable.parent if not paths.adopted else paths.root.parent / "engine-logs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _sweep_once(executable: Path) -> None:
    """End engines stranded by earlier runs, once per process.

    Reading the process table costs a subprocess, and `ensure_ready` is called
    for every translation, so this runs on the first cold start and never again.
    """
    global _swept
    with _lock:
        if _swept:
            return
        _swept = True
    ended = orphans.reap(executable)
    if ended:
        logger.info("Ended %d translation engine(s) left behind by earlier runs", ended)


async def ensure_ready(
    paths: InstallPaths,
    manifest: Manifest,
    runtime: Runtime,
    timeout_s: float,
) -> str:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s

    endpoint = active_endpoint()
    if endpoint and await is_endpoint_healthy(endpoint):
        return endpoint

    await asyncio.to_thread(_sweep_once, paths.executable)

    for force_cpu in (False, True):
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        engine = await asyncio.to_thread(_start, paths, manifest, runtime, force_cpu)
        window = min(GPU_STARTUP_MAX_S, remaining / 2) if engine.gpu_active else remaining
        if await _wait_healthy(engine, window):
            return engine.base_url
        if not engine.gpu_active:
            break
        logger.warning(
            "Translation engine did not become ready on the GPU within %.0fs; retrying on CPU",
            window,
        )
        shutdown()

    shutdown()
    raise EngineStartError(
        f"The translation engine did not become ready within {timeout_s:.0f} seconds."
    )


async def _wait_healthy(engine: _OwnedEngine, window_s: float) -> bool:
    loop = asyncio.get_running_loop()
    limit = loop.time() + window_s
    while loop.time() < limit:
        if not engine.is_running():
            return False
        if await is_endpoint_healthy(engine.base_url):
            return True
        await asyncio.sleep(0.5)
    return False
