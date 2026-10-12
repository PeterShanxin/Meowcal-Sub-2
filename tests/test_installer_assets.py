from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from installer_assets import registry_matches, require_hosted_work, verify_assets  # noqa: E402


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
