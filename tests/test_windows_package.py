from __future__ import annotations

import struct
from pathlib import Path

import pytest

from scripts.check_windows_package import check_package, pe_machine


def write_pe(path: Path, machine: int) -> None:
    data = bytearray(0x86)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", data, 0x84, machine)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_rejects_arm_python_in_x64_release(tmp_path: Path) -> None:
    write_pe(tmp_path / "Meowcal Sub 2.exe", 0x8664)
    write_pe(tmp_path / "backend/python.exe", 0xAA64)
    with pytest.raises(ValueError, match="backend/python.exe does not match x64"):
        check_package(tmp_path, "x64")


def test_rejects_package_without_license(tmp_path: Path) -> None:
    for name in ("Meowcal Sub 2.exe", "backend/python.exe", "core/meowcal-core.exe"):
        write_pe(tmp_path / name, 0xAA64)
    with pytest.raises(ValueError, match="Required package resource is missing: LICENSE"):
        check_package(tmp_path, "arm64")


def test_rejects_non_executable_payload(tmp_path: Path) -> None:
    path = tmp_path / "python.exe"
    path.write_text("not a runtime")
    with pytest.raises(ValueError, match="Not a Windows executable"):
        pe_machine(path)


@pytest.mark.parametrize(
    "relative", ["meowcal_sub_2-0.1.0.dist-info/direct_url.json", "bin/uvicorn.exe"]
)
def test_rejects_private_build_provenance_in_an_otherwise_complete_package(
    tmp_path: Path, relative: str
) -> None:
    for name in ("Meowcal Sub 2.exe", "backend/python.exe", "core/meowcal-core.exe"):
        write_pe(tmp_path / name, 0xAA64)
    for name in (
        "LICENSE",
        "backend/LICENSE.txt",
        "backend/MEOWCAL-LICENSE",
        "backend/backend-requirements.txt",
        "backend/python314._pth",
        "backend/Lib/site-packages/meocosub2/overlay/static/index.html",
        "core/meowcal-core.json",
        "core/LICENSE",
        "third-party-licenses/index.json",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    check_package(tmp_path, "arm64")
    provenance = tmp_path / "backend/Lib/site-packages" / relative
    provenance.parent.mkdir()
    provenance.write_text('{"url":"file:///C:/private-build/app.whl"}', encoding="utf-8")
    with pytest.raises(ValueError, match="build-machine paths"):
        check_package(tmp_path, "arm64")
