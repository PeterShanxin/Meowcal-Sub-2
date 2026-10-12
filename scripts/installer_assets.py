"""Validate fixed signed installers and compare their installed payloads."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

from check_windows_package import pe_machine


def require(condition: object, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def registry_matches(rows: list[dict], version: str, destination: Path) -> bool:
    return (
        len(rows) == 1
        and rows[0]["DisplayVersion"] == version
        and Path(rows[0]["InstallLocation"].strip('"')).resolve() == destination.resolve()
    )


def require_hosted_work(work: Path, environment: dict[str, str]) -> None:
    require(
        environment.get("GITHUB_ACTIONS") == "true"
        and environment.get("RUNNER_ENVIRONMENT") == "github-hosted"
        and environment.get("RUNNER_OS") == "Windows",
        "Native installer acceptance is restricted to disposable GitHub-hosted Windows runners.",
    )
    temporary = Path(environment["RUNNER_TEMP"]).resolve()
    require(
        work.resolve().is_relative_to(temporary) and work.resolve() != temporary,
        "Acceptance directory must be strictly inside RUNNER_TEMP.",
    )
    require(not work.exists(), "Acceptance directory already exists; do not reuse it.")


def verify_assets(assets: Path, release: dict, arch: str, verifier: Path) -> tuple[Path, Path]:
    prefix = f"meowcal-sub-2-v{release['version']}-windows-{arch}"
    installer = assets / release["version"] / f"{prefix}-setup.exe"
    portable = installer.with_name(f"{prefix}-portable.zip")
    require(digest(installer) == release[arch]["installer"], "Installer differs from pinned build.")
    require(digest(portable) == release[arch]["portable"], "Portable differs from pinned build.")
    subprocess.run(
        [str(verifier), str(installer), str(installer) + ".sig"],
        check=True,
        capture_output=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    with zipfile.ZipFile(portable) as archive:
        metadata = json.loads(archive.read(f"{prefix}/release.json"))
        require(
            metadata["sourceCommit"] == release["commit"] and not metadata["sourceDirty"],
            "Package source differs from pinned commit.",
        )
        require(
            metadata["architecture"] == arch and metadata["version"] == release["version"],
            "Package architecture or version differs.",
        )
        require(
            os.environ["MEOWCAL_UPDATER_PUBLIC_KEY"].encode()
            in archive.read(f"{prefix}/Meowcal Sub 2.exe"),
            "Signature key is not embedded in the packaged shell.",
        )
    return installer, portable


def verify_installed(destination: Path, portable: Path, arch: str) -> dict:
    with zipfile.ZipFile(portable) as archive:
        prefix = archive.namelist()[0].split("/")[0] + "/"
        shell = archive.read(prefix + "Meowcal Sub 2.exe")
        marker = b"__TAURI_BUNDLE_TYPE_VAR_UNK"
        require(shell.count(marker) == 1, "Expected one portable bundle marker.")
        require(
            (destination / "meowcal-sub-2-shell.exe").read_bytes()
            == shell.replace(marker, b"__TAURI_BUNDLE_TYPE_VAR_NSS", 1),
            "Installed shell differs from signed package payload.",
        )
        count = 0
        for name in archive.namelist():
            relative = name.removeprefix(prefix)
            if name.endswith("/") or relative in {"Meowcal Sub 2.exe", "release.json"}:
                continue
            require(
                (destination / relative).read_bytes() == archive.read(name),
                f"Installed resource differs: {relative}",
            )
            count += 1
    require(
        pe_machine(destination / "meowcal-sub-2-shell.exe")
        == {"x64": 0x8664, "arm64": 0xAA64}[arch],
        "Installed shell architecture differs.",
    )
    return {
        "resourcesMatched": count,
        "shellSha256": digest(destination / "meowcal-sub-2-shell.exe"),
    }
