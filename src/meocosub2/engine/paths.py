"""Private storage paths for Sub2's BGE runtime and model."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from meocosub2.engine.manifest import Manifest, Runtime

OWN_ENGINE_ROOT = "com.meowcal.sub2/engine"


@dataclass(frozen=True)
class InstallPaths:
    root: Path
    runtime_dir: Path
    runtime_archive: Path
    executable: Path
    embedding_model_dir: Path
    embedding_model: Path

    def embedding_is_complete(self, manifest: Manifest, runtime: Runtime) -> bool:
        return _matches(
            self.executable, runtime.executable.size_bytes, runtime.executable.sha256
        ) and _matches(
            self.embedding_model,
            manifest.embedding.artifact.size_bytes,
            manifest.embedding.artifact.sha256,
        )


def _matches(path: Path, expected_size: int, expected_sha256: str) -> bool:
    try:
        if path.stat().st_size != expected_size:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest() == expected_sha256
    except OSError:
        return False


def _local_app_data() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def own_paths(manifest: Manifest, runtime: Runtime) -> InstallPaths:
    root = _local_app_data() / OWN_ENGINE_ROOT
    runtime_dir = root / "runtime" / runtime.install_directory
    model_dir = root / "models" / manifest.embedding.install_directory
    return InstallPaths(
        root=root,
        runtime_dir=runtime_dir,
        runtime_archive=root / "runtime" / runtime.archive.file_name,
        executable=runtime_dir / runtime.executable.relative_path,
        embedding_model_dir=model_dir,
        embedding_model=model_dir / manifest.embedding.artifact.file_name,
    )
