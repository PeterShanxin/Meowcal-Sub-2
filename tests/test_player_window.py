import ctypes
import os
from ctypes import wintypes
from unittest.mock import MagicMock

import pytest

import meocosub2.player_window as player
from meocosub2.player_window import DESKTOP_PLAYERS, contains


def test_client_containment_accepts_negative_desktop_origins():
    assert contains((-1920, 0, 1920, 1080), (-1800, 800, 1000, 100))
    assert not contains((-1920, 0, 1920, 1080), (-100, 800, 1000, 100))
    assert not contains((0, 0, 640, 480), (0, 0, 640, 481))
    assert not contains((0, 0, 640, 480), (0, 0, 0, 100))
    assert not contains((0, 0, 640), (0, 0, 100, 100))


def test_browser_or_shell_process_audio_is_never_attributed_to_a_tab():
    for name in (
        "chrome.exe",
        "msedge.exe",
        "firefox.exe",
        "msedgewebview2.exe",
        "meowcal-sub-2.exe",
    ):
        assert name not in DESKTOP_PLAYERS


def test_visual_context_expands_upwards_within_client_at_negative_origin():
    assert player.context_region((-1920, 0, 1920, 1080), (-1800, 800, 640, 60)) == (
        -1800,
        500,
        640,
        360,
    )
    assert player.context_region((0, 0, 640, 480), (0, 450, 640, 60)) is None
    assert player.context_region((0, 0, 640, 480), (0, 100, 319, 60)) is None
    assert player.context_region((0, 0, 640, 480), (0, 0, 640, 60)) is None


class WindowSystem:
    def __init__(self, *, occluded=False, extra=False, browser=False):
        self.api = MagicMock()
        self.api.SetThreadDpiAwarenessContext.return_value = 17
        self.api.WindowFromPoint.side_effect = [100, 200 if occluded else 100, 100]
        self.api.GetAncestor.side_effect = lambda window, _: window
        self.api.IsWindowVisible.return_value = True

        def pid(_, pointer):
            ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))[0] = 42
            return 1

        self.api.GetWindowThreadProcessId.side_effect = pid

        def client(_, pointer):
            rect = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
            rect.right, rect.bottom = 640, 480
            return 1

        self.api.GetClientRect.side_effect = client

        def origin(_, pointer):
            point = ctypes.cast(pointer, ctypes.POINTER(wintypes.POINT)).contents
            point.x, point.y = -640, 0
            return 1

        self.api.ClientToScreen.side_effect = origin

        def enumerate_windows(callback, data):
            callback(100, data)
            if extra:
                callback(101, data)
            return 1

        self.api.EnumWindows.side_effect = enumerate_windows
        self.name = "chrome.exe" if browser else "ffplay.exe"

    def install(self, monkeypatch):
        monkeypatch.setattr(player, "_api", lambda: self.api)
        monkeypatch.setattr(player, "_process_name", lambda _: self.name)


@pytest.mark.skipif(os.name != "nt", reason="Windows callback ABI")
@pytest.mark.parametrize(
    "occluded,extra,browser",
    [(False, False, False), (True, False, False), (False, True, False), (False, False, True)],
)
def test_player_binding_requires_one_unoccluded_client_and_restores_dpi(
    monkeypatch, occluded, extra, browser
):
    system = WindowSystem(occluded=occluded, extra=extra, browser=browser)
    system.install(monkeypatch)
    result = player.find_player_window((-600, 400, 400, 60))
    assert result == (
        None if occluded or extra or browser else player.PlayerWindow(42, (-640, 0, 640, 480))
    )
    assert system.api.SetThreadDpiAwarenessContext.call_args_list[-1].args == (17,)


@pytest.mark.skipif(os.name != "nt", reason="Windows callback ABI")
def test_crop_outside_client_or_failed_dpi_scope_is_unknown(monkeypatch):
    system = WindowSystem()
    system.install(monkeypatch)
    assert player.find_player_window((-600, 450, 400, 60)) is None
    assert system.api.SetThreadDpiAwarenessContext.call_args_list[-1].args == (17,)
    system.api.SetThreadDpiAwarenessContext.return_value = None
    assert player.find_player_window((-600, 400, 400, 60)) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows callback ABI")
@pytest.mark.parametrize("blocked", ["desktop", "upper-cover", "subtitle-cover", None])
def test_visual_context_checks_both_bands_and_restores_thread_dpi(monkeypatch, blocked):
    system = WindowSystem(browser=True)
    system.install(monkeypatch)
    system.api.WindowFromPoint.side_effect = (
        [100, 200, 100]
        if blocked == "subtitle-cover"
        else [100, 100, 100, 100, 200 if blocked == "upper-cover" else 100, 100]
    )

    def window_class(_, buffer, length):
        buffer.value = "WorkerW" if blocked == "desktop" else "Chrome_WidgetWin_1"
        return len(buffer.value)

    system.api.GetClassNameW.side_effect = window_class
    result = player.find_visual_context((-600, 400, 400, 60))
    assert result == (None if blocked else player.VisualContext(42, (-600, 235, 400, 225)))
    assert system.api.SetThreadDpiAwarenessContext.call_args_list[-1].args == (17,)
