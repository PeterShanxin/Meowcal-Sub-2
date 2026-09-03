"""Where the managed HY-MT engine lives on disk."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from meocosub2.engine.manifest import Manifest, Runtime

# Meowcal Sub v1's engine cache. v2 ships the same artifact manifest, so a machine
# that already installed the engine through v1 is used as-is instead of downloading
# 1.1 GB again. v2 never writes into this tree.
V1_ENGINE_ROOT = "com.meowcal.sub/meowcal-sub"
OWN_ENGINE_ROOT = "com.meowcal.sub2/engine"


@dataclass(frozen=True)
class InstallPaths:
    root: Path
    runtime_dir: Path
    runtime_archive: Path
    executable: Path
    model_dir: Path
    model: Path
    adopted: bool = False

    def is_complete(self, manifest: Manifest, runtime: Runtime) -> bool:
        return _has_size(self.executable, runtime.executable.size_bytes) and _has_size(
            self.model, manifest.model.artifact.size_bytes
        )


def _has_size(path: Path, expected: int) -> bool:
    try:
        return path.stat().st_size == expected
    except OSError:
        return False


def _local_app_data() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def _from_root(root: Path, manifest: Manifest, runtime: Runtime, adopted: bool) -> InstallPaths:
    runtime_dir = root / "runtime" / runtime.install_directory
    model_dir = root / "models" / manifest.model.install_directory
    return InstallPaths(
        root=root,
        runtime_dir=runtime_dir,
        runtime_archive=root / "runtime" / runtime.archive.file_name,
        executable=runtime_dir / runtime.executable.relative_path,
        model_dir=model_dir,
        model=model_dir / manifest.model.artifact.file_name,
        adopted=adopted,
    )


def own_paths(manifest: Manifest, runtime: Runtime) -> InstallPaths:
    return _from_root(_local_app_data() / OWN_ENGINE_ROOT, manifest, runtime, adopted=False)


def resolve_paths(manifest: Manifest, runtime: Runtime) -> InstallPaths:
    """The engine install to use: this app's own, or a complete v1 install to adopt."""
    mine = own_paths(manifest, runtime)
    if mine.is_complete(manifest, runtime):
        return mine
    inherited = _from_root(_local_app_data() / V1_ENGINE_ROOT, manifest, runtime, adopted=True)
    if inherited.is_complete(manifest, runtime):
        return inherited
    return mine
