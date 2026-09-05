"""Engine manifest: which HY-MT artifacts this build installs and how it launches them.

`manifest.json` is the artifact set shipped by Meowcal Sub v1 (same URLs, sizes and
digests), so a machine that already installed the engine through v1 can be adopted
without downloading anything.
"""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

MANIFEST_PATH = Path(__file__).with_name("manifest.json")
ADRENO_RUNTIME_ID = "llama-b10155-opencl-adreno-arm64"


@dataclass(frozen=True)
class Artifact:
    file_name: str
    url: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class Executable:
    relative_path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class Runtime:
    id: str
    architecture: str
    gpu_layers: int
    launch_args: tuple[str, ...]
    install_directory: str
    archive: Artifact
    executable: Executable


@dataclass(frozen=True)
class Model:
    id: str
    install_directory: str
    artifact: Artifact


@dataclass(frozen=True)
class Embedding:
    """The model that matches a read to a subtitle line by meaning.

    Carries its own launch settings rather than sharing the translation model's:
    it runs on a second port, needs a fraction of the context, and is started in
    embedding mode with the pooling it was trained for.
    """

    id: str
    install_directory: str
    artifact: Artifact
    preferred_port: int
    context_size: int
    extra_args: tuple[str, ...]


@dataclass(frozen=True)
class Manifest:
    engine_version: str
    model: Model
    embedding: Embedding
    runtimes: tuple[Runtime, ...]
    host: str
    preferred_port: int
    context_size: int
    extra_args: tuple[str, ...]
    minimum_ram_bytes: int
    minimum_free_disk_bytes: int

    def runtime_for_host(self) -> Runtime:
        wanted = _host_architecture()
        for runtime in self.runtimes:
            if runtime.architecture == wanted:
                return runtime
        raise UnsupportedHost(f"No translation engine is published for {wanted}.")


class UnsupportedHost(RuntimeError):
    """The manifest ships no runtime for this machine's architecture."""


def _host_architecture() -> str:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "aarch64"
    if machine in {"amd64", "x86_64"}:
        return "x86_64"
    return machine


def _artifact(data: dict) -> Artifact:
    return Artifact(
        file_name=data["fileName"],
        url=data["url"],
        size_bytes=int(data["sizeBytes"]),
        sha256=data["sha256"],
    )


def _embedding(data: dict) -> Embedding:
    launch = data["launch"]
    return Embedding(
        id=data["id"],
        install_directory=data["installDirectory"],
        artifact=_artifact(data["artifact"]),
        preferred_port=int(launch["preferredPort"]),
        context_size=int(launch["contextSize"]),
        extra_args=tuple(launch["extraArgs"]),
    )


@lru_cache(maxsize=1)
def load_manifest() -> Manifest:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    launch = data["launch"]
    requirements = data["requirements"]
    return Manifest(
        engine_version=data["engineVersion"],
        model=Model(
            id=data["model"]["id"],
            install_directory=data["model"]["installDirectory"],
            artifact=_artifact(data["model"]["artifact"]),
        ),
        embedding=_embedding(data["embedding"]),
        runtimes=tuple(
            Runtime(
                id=runtime["id"],
                architecture=runtime["architecture"],
                gpu_layers=int(runtime.get("gpuLayers", 0)),
                launch_args=tuple(runtime.get("launchArgs", ())),
                install_directory=runtime["installDirectory"],
                archive=_artifact(runtime["archive"]),
                executable=Executable(
                    relative_path=runtime["executable"]["relativePath"],
                    size_bytes=int(runtime["executable"]["sizeBytes"]),
                    sha256=runtime["executable"]["sha256"],
                ),
            )
            for runtime in data["runtimes"]
        ),
        host=launch["host"],
        preferred_port=int(launch["preferredPort"]),
        context_size=int(launch["contextSize"]),
        extra_args=tuple(launch["extraArgs"]),
        minimum_ram_bytes=int(requirements["minimumRamBytes"]),
        minimum_free_disk_bytes=int(requirements["minimumFreeDiskBytes"]),
    )
