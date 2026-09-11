"""Discovery and Windows lifetime ownership for Meowcal Core processes."""

from __future__ import annotations

import os
import subprocess
import sys
from collections import deque
from contextlib import suppress
from pathlib import Path

from meocosub2.core_protocol import CoreClientError


def ended_message(process: subprocess.Popen[bytes], tail: deque[str]) -> str:
    code = process.poll()
    detail = tail[-1] if tail else "no diagnostics"
    return f"Meowcal Core ended unexpectedly (exit={code}; {detail})"


def core_profile() -> str:
    value = os.environ.get("MEOWCAL_CORE_PROFILE", "production").strip().lower()
    value = {"prod": "production", "dev": "development"}.get(value, value)
    if value not in {"production", "development"}:
        raise CoreClientError("MEOWCAL_CORE_PROFILE must be production or development")
    return value


def core_storage_override() -> Path | None:
    value = os.environ.get("MEOWCAL_CORE_STORAGE_ROOT", "").strip()
    if not value:
        return None
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raise CoreClientError("MEOWCAL_CORE_STORAGE_ROOT must be absolute")
    return raw.resolve()


def legacy_engine_roots(profile: str | None = None) -> list[Path]:
    """Existing app-owned HY-MT roots eligible for one-time verified import."""
    selected = profile or core_profile()
    suffix = ".dev" if selected == "development" else ""
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    candidates = [
        base / f"com.meowcal.sub2{suffix}" / "engine",
        base / f"com.meowcal.sub{suffix}" / "meowcal-sub",
    ]
    return [path.resolve() for path in candidates if path.is_dir()]


def resolve_core_executable() -> Path:
    """Find the pinned Core binary supplied by development or Tauri packaging."""
    override = os.environ.get("MEOWCAL_CORE_EXE", "").strip()
    if override:
        path = Path(override).expanduser().resolve()
        if path.is_file():
            return path
        raise CoreClientError(f"MEOWCAL_CORE_EXE does not name a file: {path}")

    relative = Path("resources") / "core" / "meowcal-core.exe"
    repository = Path(__file__).resolve().parents[2] / "src-tauri" / relative
    candidates = [
        Path(sys.executable).resolve().parent / relative,
        Path.cwd().resolve() / "src-tauri" / relative,
        repository,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise CoreClientError("The bundled Meowcal Core executable is missing.")


def attach_process_to_lifetime(process: subprocess.Popen) -> None:
    """Make Windows end this child process if the Python backend disappears."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
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

    class IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = 0x2000
    armed = kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
    process_handle = wintypes.HANDLE(process._handle)  # noqa: SLF001
    assigned = armed and kernel32.AssignProcessToJobObject(job, process_handle)
    if not assigned:
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise ctypes.WinError(error)
    process._meowcal_core_job = job  # noqa: SLF001


def close_process_job(process: subprocess.Popen) -> None:
    if os.name != "nt":
        return
    # Timeout and the unblocked writer can finish cleanup concurrently.
    job = vars(process).pop("_meowcal_core_job", None)
    if not job:
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle(job)


def terminate_process(process: subprocess.Popen) -> None:
    """End and reap the exact child before closing its blocking streams."""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=3)
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            with suppress(OSError, ValueError):
                stream.close()
    close_process_job(process)


def drain_stderr(process: subprocess.Popen[bytes], tail: deque[str], max_chars: int) -> None:
    """Keep bounded diagnostics without allowing an unbounded native log line."""
    if process.stderr is None:
        return
    while True:
        try:
            line = process.stderr.readline(max_chars + 1)
        except (OSError, ValueError):
            return
        if not line:
            return
        tail.append(line[:max_chars].decode("utf-8", errors="replace").strip())
