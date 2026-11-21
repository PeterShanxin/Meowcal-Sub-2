import os
import socket
import subprocess
from pathlib import Path

import pytest

from scripts.check_checkout_port import check_port

ROOT = Path(__file__).resolve().parents[1]


def test_conflicting_custom_listener_survives_launch_check():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert not check_port(port)
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            connection, _ = listener.accept()
            connection.close()
    assert check_port(port)


@pytest.mark.skipif(os.name != "nt", reason="Windows launcher")
def test_launcher_process_ownership():
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts/tests/checkout-launch.Tests.ps1"),
        ],
        check=True,
        timeout=30,
    )


def test_launcher_delegates_unchanged_and_changed_inputs_to_cargo():
    launcher = (ROOT / "run_app.vbs").read_text(encoding="utf-8")
    assert 'WshShell.CurrentDirectory = repoRoot & "\\src-tauri"' in launcher
    assert 'WshShell.Run("cargo build --locked"' in launcher
    assert "If buildResult <> 0 Then" in launcher
    assert "If forceRebuild Or IsRebuildNeeded()" not in launcher
    assert (ROOT / "src-tauri/Cargo.lock").is_file()
    assert "rerun-if-changed=../src/meocosub2/overlay/static" in (
        ROOT / "src-tauri/build.rs"
    ).read_text(encoding="utf-8")
