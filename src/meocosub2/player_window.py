"""Conservative attribution to one visible desktop player's client window."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import PureWindowsPath

# Browser PID/session attribution cannot identify the selected tab. Do not use
# its audio (or the system mix) as proof that this rectangle's video is playing.
DESKTOP_PLAYERS = frozenset(
    (
        "ffplay.exe",
        "mpv.exe",
        "vlc.exe",
        "mpc-hc.exe",
        "mpc-hc64.exe",
        "mpc-be.exe",
        "mpc-be64.exe",
        "potplayermini.exe",
        "potplayermini64.exe",
    )
)


@dataclass(frozen=True)
class PlayerWindow:
    process_id: int
    region: tuple[int, int, int, int]


def contains(outer: tuple[int, ...], inner: tuple[int, ...]) -> bool:
    if len(outer) != 4 or len(inner) != 4 or min(*outer[2:], *inner[2:]) <= 0:
        return False
    x, y, width, height = inner
    ox, oy, ow, oh = outer
    return ox <= x and oy <= y and x + width <= ox + ow and y + height <= oy + oh


def _api():
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.WindowFromPoint.argtypes, user.WindowFromPoint.restype = [wintypes.POINT], wintypes.HWND
    user.GetAncestor.argtypes, user.GetAncestor.restype = (
        [wintypes.HWND, ctypes.c_uint],
        wintypes.HWND,
    )
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    return user


def _client_region(user, window) -> tuple[int, int, int, int] | None:
    rect, origin = wintypes.RECT(), wintypes.POINT()
    if not user.GetClientRect(window, ctypes.byref(rect)) or not user.ClientToScreen(
        window, ctypes.byref(origin)
    ):
        return None
    return origin.x, origin.y, rect.right - rect.left, rect.bottom - rect.top


def _process_name(process_id: int) -> str:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = (
        [ctypes.c_uint, wintypes.BOOL, wintypes.DWORD],
        wintypes.HANDLE,
    )
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        ctypes.c_uint,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, process_id)
    if not handle:
        return ""
    try:
        buffer, length = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        return (
            PureWindowsPath(buffer.value).name.casefold()
            if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length))
            else ""
        )
    finally:
        kernel.CloseHandle(handle)


def _single_player_window(user, process_id: int) -> bool:
    count, visited = 0, 0
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(window, _):
        nonlocal count, visited
        visited += 1
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(pid))
        region = _client_region(user, window)
        if (
            pid.value == process_id
            and user.IsWindowVisible(window)
            and region
            and region[2] >= 320
            and region[3] >= 180
        ):
            count += 1
        return count < 2 and visited < 512

    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumWindows(visit, 0)
    return count == 1 and visited < 512


def find_player_window(region: tuple[int, ...]) -> PlayerWindow | None:
    """Reject occlusion, browsers, multiple same-process players and bad crops."""
    if os.name != "nt" or len(region) != 4 or min(region[2:]) <= 0:
        return None
    user = _api()
    # Selection/capture coordinates are physical pixels. Scope DPI awareness to
    # this worker, before MSS's first capture, and restore it on every path.
    previous_dpi = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    if not previous_dpi:
        return None
    try:
        return _find_player_window(user, region)
    finally:
        user.SetThreadDpiAwarenessContext(previous_dpi)


def _find_player_window(user, region: tuple[int, ...]) -> PlayerWindow | None:
    x, y, width, height = region
    roots = [
        user.GetAncestor(
            user.WindowFromPoint(wintypes.POINT(x + width * fraction // 4, y + height // 2)), 2
        )
        for fraction in (1, 2, 3)
    ]
    if not roots[0] or any(window != roots[0] for window in roots):
        return None
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(roots[0], ctypes.byref(pid))
    client = _client_region(user, roots[0])
    if (
        not client
        or not contains(client, region)
        or _process_name(pid.value) not in DESKTOP_PLAYERS
        or not _single_player_window(user, pid.value)
    ):
        return None
    return PlayerWindow(pid.value, client)
