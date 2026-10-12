from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from installer_assets import (  # noqa: E402
    nsis_command,
    registry_matches,
    require_hosted_work,
    settings_visible,
    verify_assets,
)


def hosted(temporary: Path) -> dict[str, str]:
    return {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "Windows",
        "RUNNER_TEMP": str(temporary),
    }


@pytest.mark.parametrize(
    "field,value",
    [("GITHUB_ACTIONS", "false"), ("RUNNER_ENVIRONMENT", "self-hosted"), ("RUNNER_OS", "Linux")],
)
def test_native_acceptance_refuses_non_disposable_hosts(tmp_path, field, value):
    environment = hosted(tmp_path)
    environment[field] = value
    with pytest.raises(RuntimeError, match="disposable"):
        require_hosted_work(tmp_path / "acceptance", environment)


def test_native_acceptance_refuses_temp_root_escape_and_reuse(tmp_path):
    for target in (tmp_path, tmp_path / ".." / "elsewhere"):
        with pytest.raises(RuntimeError, match="strictly inside"):
            require_hosted_work(target, hosted(tmp_path))
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(RuntimeError, match="already exists"):
        require_hosted_work(existing, hosted(tmp_path))
    require_hosted_work(tmp_path / "fresh", hosted(tmp_path))


def test_changed_installer_is_rejected_before_executing_any_verifier(tmp_path):
    version = tmp_path / "0.2.1"
    version.mkdir()
    (version / "meowcal-sub-2-v0.2.1-windows-arm64-setup.exe").write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="differs from pinned build"):
        verify_assets(
            tmp_path,
            {"version": "0.2.1", "arm64": {"installer": "0" * 64}},
            "arm64",
            tmp_path / "must-not-run.exe",
        )


def test_nsis_quoted_install_location_keeps_exact_destination_and_version(tmp_path):
    destination = tmp_path / "installed app"
    rows = [{"InstallLocation": f'"{destination}"', "DisplayVersion": "0.2.1"}]
    assert registry_matches(rows, "0.2.1", destination)
    assert not registry_matches(rows, "0.2.0", destination)
    assert not registry_matches(rows, "0.2.1", tmp_path / "other")
    assert not registry_matches(rows * 2, "0.2.1", destination)


def test_nsis_custom_directory_with_spaces_is_last_and_unquoted(tmp_path):
    installer = tmp_path / "signed installer.exe"
    destination = tmp_path / "Meowcal Sub 2"
    command = nsis_command(installer, ("/S", "/NS", "/UPDATE", "/R", f"/D={destination}"))
    assert command == f'"{installer}" /S /NS /UPDATE /R /D={destination}'
    with pytest.raises(RuntimeError, match="absolute"):
        nsis_command(installer, ("/D=relative path",))
    with pytest.raises(RuntimeError, match="Invalid"):
        nsis_command(installer, (f'/D={destination}"',))


def test_studio_search_field_cannot_satisfy_settings_acceptance():
    search = {"type": "ControlType.Edit", "name": "Search", "enabled": True, "offscreen": False}
    close = {
        "type": "ControlType.Button",
        "name": "Close settings",
        "enabled": True,
        "offscreen": False,
    }
    assert not settings_visible([search])
    assert settings_visible([search, close])
    assert not settings_visible([search, {**close, "offscreen": True}])
    assert not settings_visible([search, {**close, "enabled": False}])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows acceptance process contract")
def test_pid_reuse_cannot_adopt_an_old_compiler_process():
    script = Path(__file__).resolve().parents[1] / "scripts/tests/installer-processes.Tests.ps1"
    subprocess.run(["pwsh", "-NoProfile", "-File", str(script)], check=True, timeout=20)
