"""Pinned artifacts for Sub2's independent BGE subtitle matcher."""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

MANIFEST_PATH = Path(__file__).with_name("manifest.json")


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
    install_directory: str
    archive: Artifact
    executable: Executable


@dataclass(frozen=True)
class Embedding:
    id: str
    install_directory: str
    artifact: Artifact
    preferred_port: int
    context_size: int
    extra_args: tuple[str, ...]


@dataclass(frozen=True)
class Manifest:
    embedding: Embedding
    runtimes: tuple[Runtime, ...]
    host: str
    minimum_free_disk_bytes: int

    def runtime_for_host(self) -> Runtime:
        wanted = _host_architecture()
        for runtime in self.runtimes:
            if runtime.architecture == wanted:
                return runtime
        raise UnsupportedHost(f"No subtitle matching runtime is published for {wanted}.")


class UnsupportedHost(RuntimeError):
    """The BGE manifest ships no runtime for this machine's architecture."""


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


@lru_cache(maxsize=1)
def load_manifest() -> Manifest:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    embedding = data["embedding"]
    launch = embedding["launch"]
    return Manifest(
        embedding=Embedding(
            id=embedding["id"],
            install_directory=embedding["installDirectory"],
            artifact=_artifact(embedding["artifact"]),
            preferred_port=int(launch["preferredPort"]),
            context_size=int(launch["contextSize"]),
            extra_args=tuple(launch["extraArgs"]),
        ),
        runtimes=tuple(
            Runtime(
                id=runtime["id"],
                architecture=runtime["architecture"],
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
        host=data["host"],
        minimum_free_disk_bytes=int(data["minimumFreeDiskBytes"]),
    )
