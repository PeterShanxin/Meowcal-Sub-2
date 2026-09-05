from pathlib import Path

from meocosub2.devtools.window_capture import (
    WindowInfo,
    build_output_path,
    filter_windows,
    sanitize_filename,
)


def test_sanitize_filename_replaces_reserved_characters() -> None:
    assert sanitize_filename('Meowcal Sub 2: Main/Studio?*') == "meowcal-sub-2-main-studio"


def test_filter_windows_matches_title_case_insensitive() -> None:
    windows = [
        WindowInfo(handle=100, title="Other App"),
        WindowInfo(handle=200, title="Meowcal Sub 2"),
        WindowInfo(handle=300, title="meowcal sub 2 - Capture"),
    ]

    matches = filter_windows(windows, "MEOWCAL SUB 2")

    assert matches == [windows[1], windows[2]]


def test_build_output_path_uses_explicit_path_when_provided(tmp_path: Path) -> None:
    output = build_output_path("Meowcal Sub 2", output_dir=tmp_path, explicit_path=tmp_path / "window.png")

    assert output == tmp_path / "window.png"


def test_build_output_path_generates_sanitized_filename(tmp_path: Path) -> None:
    output = build_output_path("Meowcal Sub 2: Main/Studio", output_dir=tmp_path)

    assert output.parent == tmp_path
    assert output.name.startswith("meowcal-sub-2-main-studio-")
    assert output.suffix == ".png"
