"""Download and verify the managed HY-MT engine artifacts."""

from __future__ import annotations

import hashlib
import logging
import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path

import httpx

from meocosub2.engine.manifest import Artifact, Manifest, Runtime
from meocosub2.engine.paths import InstallPaths

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_S = 60.0
CHUNK_BYTES = 1 << 20

ProgressCallback = Callable[[str, int], None]


class EngineInstallError(RuntimeError):
    """An engine artifact could not be downloaded or failed verification."""


def _report(progress: ProgressCallback | None, message: str, percent: int) -> None:
    if progress is not None:
        progress(message, max(0, min(100, percent)))


def file_matches(path: Path, size_bytes: int, sha256: str) -> bool:
    try:
        if path.stat().st_size != size_bytes:
            return False
    except OSError:
        return False
    return _sha256(path) == sha256


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(
    url: str,
    destination: Path,
    expected_size: int,
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
            "GET", url, timeout=DOWNLOAD_TIMEOUT_S, follow_redirects=True
        ) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for chunk in response.iter_bytes(CHUNK_BYTES):
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if expected_size:
                        share = downloaded / expected_size
                        _report(
                            progress,
                            f"Downloading {label} ({downloaded // (1 << 20)} of "
                            f"{expected_size // (1 << 20)} MB)...",
                            percent_from + int((percent_to - percent_from) * share),
                        )
    except httpx.HTTPError as error:
        partial.unlink(missing_ok=True)
        raise EngineInstallError(f"Downloading the {label} failed: {error}") from error
    partial.replace(destination)


def _verify(path: Path, artifact: Artifact, label: str) -> None:
    if not file_matches(path, artifact.size_bytes, artifact.sha256):
        path.unlink(missing_ok=True)
        raise EngineInstallError(f"The downloaded {label} failed its integrity check.")


def install(
    paths: InstallPaths,
    manifest: Manifest,
    runtime: Runtime,
    progress: ProgressCallback | None = None,
) -> InstallPaths:
    """Make `paths` a complete engine install, downloading whatever is missing."""
    _check_disk_space(paths, manifest)

    if not _executable_ready(paths, runtime):
        if not file_matches(
            paths.runtime_archive, runtime.archive.size_bytes, runtime.archive.sha256
        ):
            _report(progress, "Downloading the translation runtime...", 2)
            _download(
                runtime.archive.url,
                paths.runtime_archive,
                runtime.archive.size_bytes,
                "translation runtime",
                progress,
                2,
                10,
            )
            _verify(paths.runtime_archive, runtime.archive, "translation runtime")
        _report(progress, "Installing the translation runtime...", 11)
        _extract(paths, runtime)

    if not _model_ready(paths, manifest):
        _report(progress, "Downloading the translation model...", 12)
        _download(
            manifest.model.artifact.url,
            paths.model,
            manifest.model.artifact.size_bytes,
            "translation model",
            progress,
            12,
            94,
        )
        _report(progress, "Verifying the translation model...", 95)
        _verify(paths.model, manifest.model.artifact, "translation model")
        paths.runtime_archive.unlink(missing_ok=True)

    if not paths.embedding_is_complete(manifest):
        # A fortieth of the translation model, so it gets a sliver of the bar.
        _report(progress, "Downloading the subtitle matching model...", 96)
        _download(
            manifest.embedding.artifact.url,
            paths.embedding_model,
            manifest.embedding.artifact.size_bytes,
            "subtitle matching model",
            progress,
            96,
            99,
        )
        _verify(paths.embedding_model, manifest.embedding.artifact, "subtitle matching model")

    _report(progress, "Translation engine installed.", 100)
    return paths


def _executable_ready(paths: InstallPaths, runtime: Runtime) -> bool:
    return file_matches(paths.executable, runtime.executable.size_bytes, runtime.executable.sha256)


def _model_ready(paths: InstallPaths, manifest: Manifest) -> bool:
    artifact = manifest.model.artifact
    return file_matches(paths.model, artifact.size_bytes, artifact.sha256)


def _extract(paths: InstallPaths, runtime: Runtime) -> None:
    staging = paths.runtime_dir.with_name(paths.runtime_dir.name + ".candidate")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(paths.runtime_archive) as archive:
            archive.extractall(staging)
    except (OSError, zipfile.BadZipFile) as error:
        shutil.rmtree(staging, ignore_errors=True)
        raise EngineInstallError(f"The translation runtime archive is unusable: {error}") from error

    candidate = staging / runtime.executable.relative_path
    if not file_matches(candidate, runtime.executable.size_bytes, runtime.executable.sha256):
        shutil.rmtree(staging, ignore_errors=True)
        raise EngineInstallError("The extracted translation runtime failed its integrity check.")

    shutil.rmtree(paths.runtime_dir, ignore_errors=True)
    paths.runtime_dir.parent.mkdir(parents=True, exist_ok=True)
    staging.replace(paths.runtime_dir)


def _check_disk_space(paths: InstallPaths, manifest: Manifest) -> None:
    root = paths.root
    probe = root
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError:
        return
    if free < manifest.minimum_free_disk_bytes:
        needed = manifest.minimum_free_disk_bytes // (1 << 30)
        raise EngineInstallError(
            f"Installing the translation engine needs about {needed} GB free on "
            f"{probe.drive or probe}."
        )
