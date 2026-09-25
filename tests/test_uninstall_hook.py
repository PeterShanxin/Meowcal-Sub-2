"""The uninstaller's data-removal hook, compiled with NSIS and run against a
temporary tree that stands in for the user's profile folders."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / "src-tauri" / "windows" / "hooks.nsh"

# Tauri's uninstaller sets these two variables before the hook runs; the
# harness takes them, and the tree the hook works in, from the environment.
HARNESS = r"""
Unicode true
!include LogicLib.nsh
OutFile "${OUT}"
RequestExecutionLevel user
SilentInstall silent
Var DeleteAppDataCheckboxState
Var UpdateMode
!include "${HOOKS}"
Section
  ReadEnvStr $R9 HOOK_ROOT
  ReadEnvStr $DeleteAppDataCheckboxState HOOK_DELETE_APP_DATA
  ReadEnvStr $UpdateMode HOOK_UPDATE_MODE
  !insertmacro NSIS_HOOK_POSTUNINSTALL
SectionEnd
"""

SUB2_DATA = (
    "Roaming/meowcal-sub-2/config.toml",
    "Profile/.cache/meowcal-sub-2/subdl/episode.srt",
    "Local/Meowcal/Core/sub2/production/0.1.4/aarch64/model.gguf",
    # Core releases before the per-app level stored every app's engine here.
    "Local/Meowcal/Core/production/0.1.0/aarch64/model.gguf",
)

RunHook = Callable[..., None]


def _makensis() -> Path | None:
    candidates = [shutil.which("makensis")]
    if local := os.environ.get("LOCALAPPDATA"):
        candidates.append(str(Path(local) / "tauri" / "NSIS" / "Bin" / "makensis.exe"))
    if program_files := os.environ.get("PROGRAMFILES(X86)"):
        candidates.append(str(Path(program_files) / "NSIS" / "makensis.exe"))
    return next((Path(c) for c in candidates if c and Path(c).is_file()), None)


@pytest.fixture(scope="module")
def run_hook(tmp_path_factory: pytest.TempPathFactory) -> RunHook:
    makensis = _makensis() if os.name == "nt" else None
    if makensis is None:
        pytest.skip("NSIS is not installed")
    build = tmp_path_factory.mktemp("nsis")
    hooks = HOOKS.read_text(encoding="utf-8")
    for variable, folder in (
        ("$LOCALAPPDATA", "Local"),
        ("$APPDATA", "Roaming"),
        ("$PROFILE", "Profile"),
    ):
        hooks = hooks.replace(variable, f"$R9\\{folder}")
    (build / "hooks.nsh").write_text(hooks, encoding="utf-8")
    (build / "harness.nsi").write_text(HARNESS, encoding="utf-8")
    harness = build / "harness.exe"
    subprocess.run(
        [
            str(makensis),
            "-V1",
            f"-DOUT={harness}",
            f"-DHOOKS={build / 'hooks.nsh'}",
            str(build / "harness.nsi"),
        ],
        check=True,
        timeout=120,
    )

    def run(root: Path, *, delete_app_data: bool, update_mode: bool = False) -> None:
        env = {
            **os.environ,
            "HOOK_ROOT": str(root),
            "HOOK_DELETE_APP_DATA": "1" if delete_app_data else "0",
            "HOOK_UPDATE_MODE": "1" if update_mode else "0",
        }
        subprocess.run([str(harness)], check=True, timeout=60, env=env)

    return run


def _create(root: Path, *files: str) -> None:
    for relative in files:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")


def test_removes_sub2_data_and_the_engine_when_meowcal_sub_never_ran(
    run_hook: RunHook, tmp_path: Path
) -> None:
    _create(tmp_path, *SUB2_DATA, "Profile/.cache/other-app/keep")

    run_hook(tmp_path, delete_app_data=True)

    assert not (tmp_path / "Roaming/meowcal-sub-2").exists()
    assert not (tmp_path / "Profile/.cache/meowcal-sub-2").exists()
    assert not (tmp_path / "Local/Meowcal").exists()
    assert (tmp_path / "Profile/.cache/other-app/keep").exists()


def test_keeps_development_storage(run_hook: RunHook, tmp_path: Path) -> None:
    development = (
        "Local/Meowcal/Core/sub2/development/0.1.4/aarch64/model.gguf",
        "Local/Meowcal/Core/development/0.1.0/aarch64/model.gguf",
    )
    _create(tmp_path, *SUB2_DATA, *development)

    run_hook(tmp_path, delete_app_data=True)

    assert not (tmp_path / "Local/Meowcal/Core/sub2/production").exists()
    assert not (tmp_path / "Local/Meowcal/Core/production").exists()
    assert all((tmp_path / relative).exists() for relative in development)


@pytest.mark.parametrize("sub1_folder", ["Roaming/com.meowcal.sub", "Local/com.meowcal.sub"])
def test_keeps_the_shared_engine_once_meowcal_sub_has_run(
    run_hook: RunHook, tmp_path: Path, sub1_folder: str
) -> None:
    _create(tmp_path, *SUB2_DATA)
    (tmp_path / sub1_folder).mkdir(parents=True)

    run_hook(tmp_path, delete_app_data=True)

    assert not (tmp_path / "Roaming/meowcal-sub-2").exists()
    assert not (tmp_path / "Profile/.cache/meowcal-sub-2").exists()
    assert not (tmp_path / "Local/Meowcal/Core/sub2").exists()
    assert (tmp_path / "Local/Meowcal/Core/production/0.1.0/aarch64/model.gguf").exists()


@pytest.mark.parametrize(
    ("delete_app_data", "update_mode"), [(False, False), (True, True)], ids=["unchecked", "update"]
)
def test_removes_nothing_unless_asked_outside_an_update(
    run_hook: RunHook, tmp_path: Path, delete_app_data: bool, update_mode: bool
) -> None:
    _create(tmp_path, *SUB2_DATA)

    run_hook(tmp_path, delete_app_data=delete_app_data, update_mode=update_mode)

    assert all((tmp_path / relative).exists() for relative in SUB2_DATA)
