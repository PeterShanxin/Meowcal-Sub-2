"""Check that every shipped app manifest agrees with the Tauri version."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path

VERSION = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")


def manifest_versions(root: Path) -> dict[str, str]:
    ui = root / "src/meocosub2/overlay/ui"
    package_lock = json.loads((ui / "package-lock.json").read_text(encoding="utf-8"))
    cargo_lock = tomllib.loads((root / "src-tauri/Cargo.lock").read_text(encoding="utf-8"))
    shell = [item for item in cargo_lock["package"] if item["name"] == "meowcal-sub-2-shell"]
    if len(shell) != 1:
        raise ValueError("Cargo.lock must contain exactly one meowcal-sub-2-shell package")
    return {
        "src-tauri/tauri.conf.json": json.loads(
            (root / "src-tauri/tauri.conf.json").read_text(encoding="utf-8")
        )["version"],
        "src-tauri/Cargo.toml": tomllib.loads(
            (root / "src-tauri/Cargo.toml").read_text(encoding="utf-8")
        )["package"]["version"],
        "src-tauri/Cargo.lock": shell[0]["version"],
        "pyproject.toml": tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]["version"],
        "src/meocosub2/overlay/ui/package.json": json.loads(
            (ui / "package.json").read_text(encoding="utf-8")
        )["version"],
        "src/meocosub2/overlay/ui/package-lock.json": package_lock["version"],
        "src/meocosub2/overlay/ui/package-lock.json#root": package_lock["packages"][""]["version"],
    }


def check_versions(versions: dict[str, str], tag: str | None = None) -> str:
    version = versions["src-tauri/tauri.conf.json"]
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ValueError(f"Tauri version must be major.minor.patch: {version!r}")
    mismatched = {path: value for path, value in versions.items() if value != version}
    if mismatched:
        details = ", ".join(f"{path}={value!r}" for path, value in mismatched.items())
        raise ValueError(f"App manifests disagree with {version}: {details}")
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"Release tag must be v{version}; got {tag!r}")
    return version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Require an exact vX.Y.Z release tag")
    parser.add_argument(
        "--require-head-tag", action="store_true", help="Require --tag to point at HEAD"
    )
    args = parser.parse_args()
    if args.require_head_tag and not args.tag:
        parser.error("--require-head-tag requires --tag")
    root = Path(__file__).resolve().parents[1]
    version = check_versions(manifest_versions(root), args.tag)
    if args.require_head_tag:
        tagged_commit = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/tags/{args.tag}^{{commit}}"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if tagged_commit != head:
            raise ValueError(f"Tag {args.tag} does not point at HEAD")
    print(f"App manifests match v{version}.")


if __name__ == "__main__":
    main()
