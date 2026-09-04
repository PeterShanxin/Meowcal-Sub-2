from dataclasses import replace
from pathlib import Path

import pytest

from meocosub2.engine import install as install_module
from meocosub2.engine.install import EngineInstallError
from meocosub2.engine.manifest import load_manifest
from meocosub2.engine.paths import InstallPaths, resolve_paths
from meocosub2.engine.runtime import (
    gpu_launch_supported,
    launch_arguments,
    select_loopback_port,
    worker_threads,
)


@pytest.fixture
def manifest():
    return load_manifest()


def test_the_manifest_publishes_a_runtime_for_this_host(manifest) -> None:
    runtime = manifest.runtime_for_host()
    assert runtime.executable.relative_path == "llama-server.exe"
    assert manifest.model.artifact.size_bytes > 0


def test_the_launch_line_pins_the_model_port_and_context(manifest) -> None:
    runtime = manifest.runtime_for_host()
    paths = resolve_paths(manifest, runtime)
    arguments = launch_arguments(paths, manifest, runtime, 12345, 99, ("--no-kv-offload",))
    assert arguments[:2] == ["-m", str(paths.model)]
    assert arguments[arguments.index("--port") + 1] == "12345"
    assert arguments[arguments.index("-c") + 1] == str(manifest.context_size)
    assert arguments[arguments.index("-ngl") + 1] == "99"
    assert arguments[-1] == "--no-kv-offload"
    assert "--threads" in arguments


def test_a_cpu_launch_asks_for_no_gpu_layers(manifest) -> None:
    runtime = manifest.runtime_for_host()
    paths = resolve_paths(manifest, runtime)
    arguments = launch_arguments(paths, manifest, runtime, 1, 0, ())
    assert arguments[arguments.index("-ngl") + 1] == "0"
    assert "--no-kv-offload" not in arguments


def test_the_engine_leaves_cores_for_capture_and_ocr() -> None:
    assert worker_threads(12) == 8
    assert worker_threads(4) == 4
    assert worker_threads(1) == 4


def test_the_gpu_policy_is_refused_when_the_runtime_asks_for_no_layers(manifest) -> None:
    runtime = manifest.runtime_for_host()
    cpu_only = replace(runtime, gpu_layers=0)
    assert not gpu_launch_supported(cpu_only)


def test_a_loopback_port_is_always_available() -> None:
    assert 1 <= select_loopback_port(0) <= 65535


def test_an_incomplete_install_is_not_reported_as_complete(tmp_path: Path, manifest) -> None:
    runtime = manifest.runtime_for_host()
    paths = InstallPaths(
        root=tmp_path,
        runtime_dir=tmp_path / "runtime",
        runtime_archive=tmp_path / "runtime.zip",
        executable=tmp_path / "runtime" / "llama-server.exe",
        model_dir=tmp_path / "models",
        model=tmp_path / "models" / "model.gguf",
    )
    assert not paths.is_complete(manifest, runtime)


def test_a_truncated_artifact_fails_verification(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"short")
    assert not install_module.file_matches(artifact, 999, "0" * 64)


def test_a_full_disk_is_reported_before_any_download(tmp_path: Path, manifest, monkeypatch) -> None:
    monkeypatch.setattr(
        install_module.shutil, "disk_usage", lambda _: type("Usage", (), {"free": 1})()
    )
    runtime = manifest.runtime_for_host()
    paths = InstallPaths(
        root=tmp_path,
        runtime_dir=tmp_path / "runtime",
        runtime_archive=tmp_path / "runtime.zip",
        executable=tmp_path / "runtime" / "llama-server.exe",
        model_dir=tmp_path / "models",
        model=tmp_path / "models" / "model.gguf",
    )
    with pytest.raises(EngineInstallError, match="free"):
        install_module.install(paths, manifest, runtime)


def test_a_second_install_request_reports_the_one_in_flight(monkeypatch) -> None:
    import threading

    from meocosub2 import engine

    started = threading.Event()
    release = threading.Event()

    def slow_install(*_args, **_kwargs):
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(install_module, "install", slow_install)
    monkeypatch.setattr(
        engine, "resolve_paths", lambda *_: type("Paths", (), {"is_complete": lambda *_: False})()
    )
    monkeypatch.setattr(engine, "_install_job", None)
    try:
        engine.install_engine()
        assert started.wait(timeout=5)
        # Would deadlock if the second request re-entered the install lock.
        assert engine.install_engine().phase == "installing"
    finally:
        release.set()
        monkeypatch.setattr(engine, "_install_job", None)
