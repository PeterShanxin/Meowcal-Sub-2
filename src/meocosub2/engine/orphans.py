"""Translation engines left behind by earlier runs, and ending them.

The engine is a separate executable holding a multi-gigabyte model resident.
`runtime.shutdown` ends it on the graceful path, and the job objects cover the
paths where our code does not get to run - but neither reaches an engine that
was already stranded before this process started. Without a sweep at startup,
one engine per earlier crash stays resident for the life of the machine.

The decision - which processes are ours to end - is a pure function over a list,
so it is testable without a process table, a job object, or Windows.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
SNAPSHOT_TIMEOUT_S = 20.0
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Windows accepts this prefix on any path and reports it on some, so two
# spellings of one file would otherwise compare as two files.
_EXTENDED_LENGTH_PREFIX = "\\\\?\\"


@dataclass(frozen=True)
class ProcessEntry:
    """A process as the process table reported it.

    `image_path` is filled in only for processes worth identifying, so `None`
    means "not a candidate" rather than "path unknown".
    """

    pid: int
    parent_pid: int
    image_path: Path | None


def normalize(path: Path) -> str:
    """Compare paths the way Windows does: case-insensitively, prefix removed."""
    text = str(path)
    if text.startswith(_EXTENDED_LENGTH_PREFIX):
        text = text[len(_EXTENDED_LENGTH_PREFIX) :]
    return text.lower()


def orphans(
    processes: list[ProcessEntry],
    executable: Path,
    own_pid: int,
) -> list[ProcessEntry]:
    """The engine processes that have no owner left.

    Conservative in one direction on purpose. A process whose parent PID has
    been recycled onto some unrelated live process reads as owned and is left
    alone, so a second Meowcal Sub running its own engine is never touched. The
    cost is an orphan occasionally missed, which is a missed cleanup; the
    opposite mistake kills a working engine out from under a running app.

    Ownership is proven by path, never by image name: an unrelated
    `llama-server.exe` from somewhere else on the machine is not ours to end.
    """
    target = normalize(executable)
    live = {process.pid for process in processes}
    return [
        process
        for process in processes
        if process.pid != own_pid
        and process.image_path is not None
        and normalize(process.image_path) == target
        # PID 0 is the idle process and appears in every snapshot, so a process
        # reporting it as a parent has no real parent rather than a live one.
        and not (process.parent_pid != 0 and process.parent_pid in live)
    ]


def _snapshot(file_name: str) -> list[ProcessEntry]:
    """The process table, with image paths kept only for candidates.

    The whole table is read even though one executable is being looked for:
    whether a candidate still has a live parent is a question about every other
    process on the machine.
    """
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, "
                "Name, ExecutablePath | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            timeout=SNAPSHOT_TIMEOUT_S,
            creationflags=CREATE_NO_WINDOW,
        )
        rows = json.loads(completed.stdout or "[]")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        logger.debug("Could not read the process table; stray engines were not swept.")
        return []

    if isinstance(rows, dict):
        rows = [rows]
    entries: list[ProcessEntry] = []
    for row in rows:
        path = row.get("ExecutablePath")
        ours = str(row.get("Name") or "").lower() == file_name.lower()
        entries.append(
            ProcessEntry(
                pid=int(row.get("ProcessId") or 0),
                parent_pid=int(row.get("ParentProcessId") or 0),
                image_path=Path(path) if ours and path else None,
            )
        )
    return entries


def _terminate(pid: int, expected: Path) -> bool:
    """End `pid`, but only while it is still the process the snapshot identified.

    The snapshot proved the identity; by the time we act, the PID may name
    something else entirely - startup is the busiest moment for process creation
    on the machine, and an engine that was still exiting when we looked can free
    its PID onto something else. Re-reading the image path from the handle we
    are about to terminate closes that window rather than narrowing it: the
    handle pins the kernel object, so a PID recycled after the open cannot alias
    what we hold.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return False
        if normalize(Path(buffer.value)) != normalize(expected):
            return False
        return bool(kernel32.TerminateProcess(handle, 1))
    finally:
        kernel32.CloseHandle(handle)


def reap(executable: Path) -> int:
    """End the managed engines left behind by earlier runs. Returns how many."""
    if os.name != "nt" or not executable.name:
        return 0
    ended = 0
    for orphan in orphans(_snapshot(executable.name), executable, os.getpid()):
        if _terminate(orphan.pid, executable):
            logger.info(
                "Ended a translation engine left behind by an earlier run (pid=%d)", orphan.pid
            )
            ended += 1
    return ended
