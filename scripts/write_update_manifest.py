"""Assemble a Tauri updater manifest from both signed Windows packages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from check_app_version import check_versions, manifest_versions

REPOSITORY = "PeterShanxin/Meowcal-Sub-2"
TARGETS = {"x64": "windows-x86_64", "arm64": "windows-aarch64"}


def build_manifest(dist: Path, version: str, tag: str) -> dict[str, object]:
    if tag != f"v{version}":
        raise ValueError(f"Release tag must be v{version}")
    platforms = {}
    for architecture, target in TARGETS.items():
        name = f"meowcal-sub-2-v{version}-windows-{architecture}-setup.exe"
        installer = dist / name
        signature_file = dist / f"{name}.sig"
        if not installer.is_file() or installer.stat().st_size == 0:
            raise ValueError(f"Signed installer is missing or empty: {installer}")
        if not signature_file.is_file():
            raise ValueError(f"Updater signature is missing: {signature_file}")
        signature = signature_file.read_text(encoding="utf-8").strip()
        if not signature or "\n" in signature:
            raise ValueError(f"Updater signature is empty or malformed: {signature_file}")
        platforms[target] = {
            "signature": signature,
            "url": f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}",
        }
    return {"version": version, "platforms": platforms}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = check_versions(manifest_versions(root), args.tag)
    manifest = build_manifest(args.dist, version, args.tag)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote signed update manifest for v{version} to {args.output}")


if __name__ == "__main__":
    main()
