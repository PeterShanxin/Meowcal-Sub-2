"""Process lifecycle for the managed llama-server engines.

Two models run, each its own server on its own loopback port: HY-MT translates,
and bge-small-zh matches a read to the subtitle line that means the same thing.
They share one executable and one launch path, differing only in what a
`LaunchPlan` says.

The translation half is ported from the Meowcal Sub v1 Rust runtime: same
argument vector, same dynamic-loopback port policy, same GPU-then-CPU startup
fallback, and the same rule that an engine is only ever the child this process
spawned.
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

# The two models the app runs, each its own llama-server on its own port. They
# share the same executable, so one sweep for strays covers both.
TRANSLATION = "translation"
EMBEDDING = "embedding"

_lock = threading.Lock()
_owned: dict[str, _OwnedEngine] = {}
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


@dataclass(frozen=True)
class LaunchPlan:
    """Everything one llama-server needs: which model, on what port, and how."""

    role: str
    executable: Path
    model: Path
    alias: str
    host: str
    preferred_port: int
    context_size: int
    extra_args: tuple[str, ...]
    log_stem: str
    gpu_layers: int = 0
    policy_args: tuple[str, ...] = ()


def translation_plan(
    paths: InstallPaths, manifest: Manifest, runtime: Runtime, gpu_active: bool
) -> LaunchPlan:
    return LaunchPlan(
        role=TRANSLATION,
        executable=paths.executable,
        model=paths.model,
        alias=manifest.model.id,
        host=manifest.host,
        preferred_port=manifest.preferred_port,
        context_size=manifest.context_size,
        extra_args=manifest.extra_args,
        log_stem="hy-mt-server",
        gpu_layers=runtime.gpu_layers if gpu_active else 0,
        policy_args=runtime.launch_args if gpu_active else (),
    )


def embedding_plan(paths: InstallPaths, manifest: Manifest) -> LaunchPlan:
    """The matching model always runs on CPU: 26MB, and it answers in milliseconds."""
    return LaunchPlan(
        role=EMBEDDING,
        executable=paths.executable,
        model=paths.embedding_model,
        alias=manifest.embedding.id,
        host=manifest.host,
        preferred_port=manifest.embedding.preferred_port,
        context_size=manifest.embedding.context_size,
        extra_args=manifest.embedding.extra_args,
        log_stem="embedding-server",
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
        str(plan.gpu_layers),
        *plan.extra_args,
    ]
    # llama.cpp takes the last --threads it parses; a manifest that pins one wins.
    if "--threads" not in arguments and "-t" not in arguments:
        arguments += ["--threads", str(worker_threads(os.cpu_count() or 1))]
    arguments += list(plan.policy_args)
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


def active_endpoint(role: str = TRANSLATION) -> str | None:
    with _lock:
        engine = _owned.get(role)
        if engine is None:
            return None
        if not engine.is_running():
            del _owned[role]
            return None
        return engine.base_url


def active_gpu_active() -> bool:
    """Whether the translation model is offloaded. The matching model never is."""
    with _lock:
        engine = _owned.get(TRANSLATION)
        return bool(engine and engine.is_running() and engine.gpu_active)


def shutdown(role: str | None = None) -> None:
    """Stop one engine, or every engine this process owns."""
    with _lock:
        wanted = list(_owned) if role is None else [role]
        stopping = [(name, _owned.pop(name)) for name in wanted if name in _owned]
    for name, engine in stopping:
        logger.info("Stopping the managed %s engine (pid=%s)", name, engine.process.pid)
        engine.process.terminate()
        try:
            engine.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            engine.process.kill()


def _start(plan: LaunchPlan, paths: InstallPaths) -> _OwnedEngine:
    if not plan.executable.is_file():
        raise EngineStartError(f"Translation runtime is missing: {plan.executable}")
    if not plan.model.is_file():
        raise EngineStartError(f"The {plan.role} model is missing: {plan.model}")

    port = select_loopback_port(plan.preferred_port)
    log_dir = _log_directory(paths)
    arguments = launch_arguments(plan, port)
    gpu_active = plan.gpu_layers > 0

    logger.info(
        "Starting the %s engine on port %d (%s)",
        plan.role,
        port,
        "Adreno GPU" if gpu_active else "CPU",
    )
    with open(log_dir / f"{plan.log_stem}.log", "a", encoding="utf-8") as stdout, open(
        log_dir / f"{plan.log_stem}.err.log", "a", encoding="utf-8"
    ) as stderr:
        process = subprocess.Popen(
            [str(plan.executable), *arguments],
            cwd=str(plan.executable.parent),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=CREATE_NO_WINDOW,
        )
    _attach_to_process_lifetime(process)
    engine = _OwnedEngine(
        process=process,
        executable=str(plan.executable),
        model=str(plan.model),
        port=port,
        gpu_active=gpu_active,
    )
    with _lock:
        _owned[plan.role] = engine
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
        plan = translation_plan(
            paths, manifest, runtime, gpu_active=not force_cpu and gpu_launch_supported(runtime)
        )
        engine = await asyncio.to_thread(_start, plan, paths)
        window = min(GPU_STARTUP_MAX_S, remaining / 2) if engine.gpu_active else remaining
        if await _wait_healthy(engine, window):
            return engine.base_url
        if not engine.gpu_active:
            break
        logger.warning(
            "Translation engine did not become ready on the GPU within %.0fs; retrying on CPU",
            window,
        )
        shutdown(TRANSLATION)

    shutdown(TRANSLATION)
    raise EngineStartError(
        f"The translation engine did not become ready within {timeout_s:.0f} seconds."
    )


async def ensure_embedding_ready(
    paths: InstallPaths,
    manifest: Manifest,
    timeout_s: float,
) -> str:
    """Start the model that matches reads to subtitle lines by meaning.

    No GPU fallback to attempt: it is 26MB and never offloaded, so a start that
    fails has failed for a reason retrying on CPU cannot fix.
    """
    endpoint = active_endpoint(EMBEDDING)
    if endpoint and await is_endpoint_healthy(endpoint):
        return endpoint

    engine = await asyncio.to_thread(_start, embedding_plan(paths, manifest), paths)
    if await _wait_healthy(engine, timeout_s):
        return engine.base_url

    shutdown(EMBEDDING)
    raise EngineStartError(
        f"The subtitle matching model did not become ready within {timeout_s:.0f} seconds."
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
