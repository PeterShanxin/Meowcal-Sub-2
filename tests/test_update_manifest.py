from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "write_update_manifest", ROOT / "scripts/write_update_manifest.py"
)
assert SPEC and SPEC.loader
write_update_manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(write_update_manifest)


def signed_installers(dist: Path) -> None:
    for architecture in ("x64", "arm64"):
        name = f"meowcal-sub-2-v0.2.0-windows-{architecture}-setup.exe"
        (dist / name).write_bytes(b"fixture installer")
        (dist / f"{name}.sig").write_text("signed-fixture\n", encoding="utf-8")


def test_manifest_includes_both_signed_targets(tmp_path: Path) -> None:
    signed_installers(tmp_path)
    manifest = write_update_manifest.build_manifest(tmp_path, "0.2.0", "v0.2.0")
    assert set(manifest["platforms"]) == {"windows-x86_64", "windows-aarch64"}
    assert manifest["platforms"]["windows-aarch64"]["url"].endswith(
        "meowcal-sub-2-v0.2.0-windows-arm64-setup.exe"
    )


def test_missing_signature_fails(tmp_path: Path) -> None:
    signed_installers(tmp_path)
    (tmp_path / "meowcal-sub-2-v0.2.0-windows-arm64-setup.exe.sig").unlink()
    with pytest.raises(ValueError, match="signature is missing"):
        write_update_manifest.build_manifest(tmp_path, "0.2.0", "v0.2.0")


def test_wrong_tag_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Release tag must be"):
        write_update_manifest.build_manifest(tmp_path, "0.2.0", "v0.1.0")
