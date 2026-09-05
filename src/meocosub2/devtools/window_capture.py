"""Capture a real Windows app window to an image for local UI debugging."""

from __future__ import annotations

import argparse
import ctypes
import os
import re
import tempfile
import time
from contextlib import suppress
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageGrab

DEFAULT_WINDOW_TITLE = "Meowcal Sub 2"


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str


def sanitize_filename(title: str) -> str:
    sanitized = re.sub(r"[^0-9A-Za-z]+", "-", title.strip().lower()).strip("-")
    return sanitized or "window-capture"


def filter_windows(windows: list[WindowInfo], title_query: str) -> list[WindowInfo]:
    query = title_query.strip().lower()
    if not query:
        return list(windows)
    return [window for window in windows if query in window.title.lower()]


def build_output_path(
    title: str,
    output_dir: Path,
    explicit_path: Path | None = None,
    timestamp: str | None = None,
) -> Path:
    if explicit_path is not None:
        return explicit_path
    suffix = timestamp or time.strftime("%Y%m%d-%H%M%S")
    return output_dir / f"{sanitize_filename(title)}-{suffix}.png"


def default_output_dir(mode: str) -> Path:
    if mode == "temp":
        return Path(tempfile.gettempdir()) / "meowcal-sub2"
    return Path.cwd() / "output" / "screenshots"


def _require_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("Window capture is only supported on Windows.")
    _become_dpi_aware()


def _become_dpi_aware() -> None:
    """Report window bounds in physical pixels.

    Without this the process sees scaled coordinates while `ImageGrab` grabs
    physical ones, so on a scaled display every capture is offset and cropped.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        with suppress(AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()


def enumerate_windows() -> list[WindowInfo]:
    _require_windows()
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    windows: list[WindowInfo] = []

    @callback_type
    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        title_length = user32.GetWindowTextLengthW(hwnd)
        if title_length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        title = buffer.value.strip()
        if title:
            windows.append(WindowInfo(handle=int(hwnd), title=title))
        return True

    user32.EnumWindows(callback, 0)
    return windows


def active_window() -> WindowInfo:
    _require_windows()
    user32 = ctypes.windll.user32
    hwnd = int(user32.GetForegroundWindow())
    if hwnd == 0:
        raise RuntimeError("No active window is available.")
    title_length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(title_length + 1)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    title = buffer.value.strip() or "active-window"
    return WindowInfo(handle=hwnd, title=title)


def select_window(windows: list[WindowInfo], title_query: str) -> WindowInfo:
    matches = filter_windows(windows, title_query)
    if not matches:
        visible_titles = ", ".join(window.title for window in windows[:8]) or "none"
        raise RuntimeError(f'No visible window matched "{title_query}". Visible windows: {visible_titles}')
    exact = [window for window in matches if window.title.lower() == title_query.strip().lower()]
    ranked = exact or matches
    return min(ranked, key=lambda window: (len(window.title), window.title.lower()))


def window_bounds(handle: int) -> tuple[int, int, int, int]:
    _require_windows()

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    rect = RECT()
    if not ctypes.windll.user32.GetWindowRect(handle, ctypes.byref(rect)):
        raise RuntimeError(f"Failed to read bounds for window handle {handle}.")
    if rect.right <= rect.left or rect.bottom <= rect.top:
        raise RuntimeError(f"Window handle {handle} has invalid bounds.")
    return rect.left, rect.top, rect.right, rect.bottom


def capture_window_image(window: WindowInfo, output_path: Path) -> Path:
    bounds = window_bounds(window.handle)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = ImageGrab.grab(bbox=bounds, all_screens=True)
    image.save(output_path)
    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture the Meowcal desktop window to a PNG.")
    parser.add_argument("--title", default=DEFAULT_WINDOW_TITLE, help="Window title substring to match.")
    parser.add_argument("--path", type=Path, help="Explicit PNG output path.")
    parser.add_argument(
        "--mode",
        choices=("temp", "cwd"),
        default="temp",
        help="Default output location when --path is not provided.",
    )
    parser.add_argument("--list-windows", action="store_true", help="List visible windows matching --title.")
    parser.add_argument("--active-window", action="store_true", help="Capture the current foreground window instead.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.active_window:
        window = active_window()
        output_path = build_output_path(window.title, default_output_dir(args.mode), args.path)
        print(capture_window_image(window, output_path))
        return 0

    windows = enumerate_windows()
    if args.list_windows:
        for window in filter_windows(windows, args.title):
            print(f"{window.handle}\t{window.title}")
        return 0

    window = select_window(windows, args.title)
    output_path = build_output_path(window.title, default_output_dir(args.mode), args.path)
    print(capture_window_image(window, output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
