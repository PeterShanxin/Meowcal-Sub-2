"""Validate the architecture and required resources of a portable Windows package."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


def pe_machine(path: Path) -> int:
    with path.open("rb") as handle:
        if handle.read(2) != b"MZ":
            raise ValueError(f"Not a Windows executable: {path.name}")
        handle.seek(0x3C)
        offset = struct.unpack("<I", handle.read(4))[0]
        handle.seek(offset)
        if handle.read(4) != b"PE\0\0":
            raise ValueError(f"Invalid PE header: {path.name}")
        return struct.unpack("<H", handle.read(2))[0]


def check_package(package: Path, architecture: str) -> None:
    expected = {"x64": 0x8664, "arm64": 0xAA64}[architecture]
    for relative in ("Meowcal Sub 2.exe", "backend/python.exe", "core/meowcal-core.exe"):
        if pe_machine(package / relative) != expected:
            raise ValueError(f"{relative} does not match {architecture}")
    for relative in (
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
        if not (package / relative).is_file():
            raise ValueError(f"Required package resource is missing: {relative}")
    if (package / "backend/Lib/site-packages/meocosub2/overlay/ui").exists():
        raise ValueError("Studio development files must not be distributed in the backend.")
    if list((package / "backend/Lib/site-packages").glob("*.dist-info/direct_url.json")):
        raise ValueError("Local wheel provenance must not expose build-machine paths.")
    if (package / "backend/Lib/site-packages/bin").exists():
        raise ValueError("Unused console launchers must not expose build-machine paths.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("architecture", choices=("x64", "arm64"))
    args = parser.parse_args()
    check_package(args.package, args.architecture)
    print(f"Windows {args.architecture} package resources and PE architectures passed.")
