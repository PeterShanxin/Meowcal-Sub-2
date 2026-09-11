"""Download and verify Sub2's independent BGE runtime and model."""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path

import httpx

from meocosub2.engine.manifest import Artifact, Manifest, Runtime
from meocosub2.engine.paths import InstallPaths

DOWNLOAD_TIMEOUT_S = 60.0
CHUNK_BYTES = 1 << 20
ProgressCallback = Callable[[str, int], None]


class EngineInstallError(RuntimeError):
    """A BGE artifact could not be downloaded or failed verification."""


def _report(progress: ProgressCallback | None, message: str, percent: int) -> None:
    if progress is not None:
        progress(message, max(0, min(100, percent)))


def file_matches(path: Path, size_bytes: int, sha256: str) -> bool:
    try:
        if path.stat().st_size != size_bytes:
            return False
    except OSError:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest() == sha256


def _download(
    artifact: Artifact,
    destination: Path,
    label: str,
    progress: ProgressCallback | None,
    percent_from: int,
    percent_to: int,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.unlink(missing_ok=True)
    downloaded = 0
    try:
        with httpx.stream(
            "GET", artifact.url, timeout=DOWNLOAD_TIMEOUT_S, follow_redirects=True
        ) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for chunk in response.iter_bytes(CHUNK_BYTES):
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if artifact.size_bytes:
                        share = downloaded / artifact.size_bytes
                        _report(
                            progress,
                            f"Downloading {label}...",
                            percent_from + int((percent_to - percent_from) * share),
                        )
    except httpx.HTTPError as error:
        partial.unlink(missing_ok=True)
        raise EngineInstallError(f"Downloading the {label} failed: {error}") from error
    partial.replace(destination)
    if not file_matches(destination, artifact.size_bytes, artifact.sha256):
        destination.unlink(missing_ok=True)
        raise EngineInstallError(f"The downloaded {label} failed its integrity check.")


def install_embedding(
    paths: InstallPaths,
    manifest: Manifest,
    runtime: Runtime,
    progress: ProgressCallback | None = None,
) -> None:
    """Install the private BGE server tree without borrowing Core's runtime."""
    _check_disk_space(paths, manifest)
    if not file_matches(paths.executable, runtime.executable.size_bytes, runtime.executable.sha256):
        if not file_matches(
            paths.runtime_archive, runtime.archive.size_bytes, runtime.archive.sha256
        ):
            _download(runtime.archive, paths.runtime_archive, "matching runtime", progress, 0, 35)
        _report(progress, "Installing the subtitle matching runtime...", 36)
        _extract(paths, runtime)

    artifact = manifest.embedding.artifact
    if not file_matches(paths.embedding_model, artifact.size_bytes, artifact.sha256):
        _download(artifact, paths.embedding_model, "subtitle matching model", progress, 37, 99)
    _report(progress, "Subtitle matching model installed.", 100)


def _extract(paths: InstallPaths, runtime: Runtime) -> None:
    staging = paths.runtime_dir.with_name(paths.runtime_dir.name + ".candidate")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(paths.runtime_archive) as archive:
            archive.extractall(staging)
    except (OSError, zipfile.BadZipFile) as error:
        shutil.rmtree(staging, ignore_errors=True)
        raise EngineInstallError(f"The matching runtime archive is unusable: {error}") from error

    candidate = staging / runtime.executable.relative_path
    if not file_matches(candidate, runtime.executable.size_bytes, runtime.executable.sha256):
        shutil.rmtree(staging, ignore_errors=True)
        raise EngineInstallError("The extracted matching runtime failed its integrity check.")
    shutil.rmtree(paths.runtime_dir, ignore_errors=True)
    paths.runtime_dir.parent.mkdir(parents=True, exist_ok=True)
    staging.replace(paths.runtime_dir)


def _check_disk_space(paths: InstallPaths, manifest: Manifest) -> None:
    probe = paths.root
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError:
        return
    if free < manifest.minimum_free_disk_bytes:
        needed = manifest.minimum_free_disk_bytes // (1 << 20)
        raise EngineInstallError(
            f"Installing subtitle matching needs about {needed} MB free on {probe.drive or probe}."
        )
