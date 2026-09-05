from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from meocosub2 import engine
from meocosub2.engine import install as install_module
from meocosub2.engine import paths as paths_module
from meocosub2.engine.install import EngineInstallError
from meocosub2.engine.manifest import load_manifest
from meocosub2.engine.paths import InstallPaths, resolve_paths
from meocosub2.engine.runtime import (
    LaunchPlan,
    embedding_plan,
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


def a_plan(**overrides) -> LaunchPlan:
    """A launch plan spelled out, so the argument builder is tested on its own.

    Which runtime `runtime_for_host` picks depends on the machine running the
    tests, and its GPU policy with it.
    """
    fields = {
        "role": "translation",
        "executable": Path("llama-server.exe"),
        "model": Path("model.gguf"),
        "alias": "test-model",
        "host": "127.0.0.1",
        "preferred_port": 11436,
        "context_size": 2048,
        "extra_args": ("--jinja",),
        "log_stem": "test-server",
    }
    return LaunchPlan(**{**fields, **overrides})


def test_the_launch_line_pins_the_model_port_and_context() -> None:
    plan = a_plan(gpu_layers=99, policy_args=("--no-kv-offload",))
    arguments = launch_arguments(plan, 12345)
    assert arguments[:2] == ["-m", str(plan.model)]
    assert arguments[arguments.index("--port") + 1] == "12345"
    assert arguments[arguments.index("-c") + 1] == "2048"
    assert arguments[arguments.index("-ngl") + 1] == "99"
    assert arguments[-1] == "--no-kv-offload"
    assert "--threads" in arguments


def test_a_cpu_launch_asks_for_no_gpu_layers() -> None:
    arguments = launch_arguments(a_plan(), 1)
    assert arguments[arguments.index("-ngl") + 1] == "0"
    assert "--no-kv-offload" not in arguments


def test_the_matching_model_launches_in_embedding_mode_with_its_trained_pooling(
    manifest,
) -> None:
    """bge is trained with CLS pooling; mean-pooling it degrades every score."""
    runtime = manifest.runtime_for_host()
    plan = embedding_plan(resolve_paths(manifest, runtime), manifest)
    arguments = launch_arguments(plan, 11437)
    assert "--embedding" in arguments
    assert arguments[arguments.index("--pooling") + 1] == "cls"
    # Never offloaded, and pointed at its own model rather than the translator's.
    assert arguments[arguments.index("-ngl") + 1] == "0"
    assert arguments[1].endswith(manifest.embedding.artifact.file_name)


def test_the_matching_model_is_not_required_for_a_v1_install_to_be_adopted(
    manifest, monkeypatch
) -> None:
    """A v1 engine tree predates this model, so demanding it would reject them all.

    `is_complete` is what decides whether to adopt a v1 install instead of
    downloading 1.1 GB again.
    """
    runtime = manifest.runtime_for_host()
    paths = resolve_paths(manifest, runtime)
    # A tree carrying the runtime and the translation model, and nothing else.
    monkeypatch.setattr(paths_module, "_has_size", lambda path, size: path != paths.embedding_model)

    assert paths.is_complete(manifest, runtime)
    assert not paths.embedding_is_complete(manifest)


@pytest.mark.asyncio
async def test_a_session_fetches_the_matching_model_an_adopted_install_never_had(
    manifest, monkeypatch
) -> None:
    """The gap the adoption rule above leaves open.

    An adopted v1 tree reports itself complete, so Settings has nothing left to
    offer and no other path would ever download this. A session that needs it
    and finds it missing measured as a session with matching switched off.
    """
    runtime = manifest.runtime_for_host()
    paths = resolve_paths(manifest, runtime)
    monkeypatch.setattr(paths_module, "_has_size", lambda path, size: path != paths.embedding_model)
    fetched: list[Path] = []
    monkeypatch.setattr(
        engine.install_module,
        "install_embedding",
        lambda paths, manifest: fetched.append(paths.embedding_model),
    )
    monkeypatch.setattr(
        engine.runtime_module,
        "ensure_embedding_ready",
        AsyncMock(return_value="http://127.0.0.1:11437"),
    )

    assert await engine.ensure_embedding_ready() == "http://127.0.0.1:11437"
    assert fetched == [paths.embedding_model]


def test_the_matching_model_lives_in_our_own_tree_even_when_v1_is_adopted(
    manifest,
) -> None:
    """v2 never writes into a v1 install, so its model cannot be stored there."""
    runtime = manifest.runtime_for_host()
    v1_root = Path("C:/somewhere/com.meowcal.sub/meowcal-sub")
    adopted = paths_module._from_root(v1_root, manifest, runtime, adopted=True)

    assert adopted.model.is_relative_to(v1_root)
    assert not adopted.embedding_model.is_relative_to(v1_root)


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
        embedding_model_dir=tmp_path / "models" / "embedding",
        embedding_model=tmp_path / "models" / "embedding" / "embedding.gguf",
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
        embedding_model_dir=tmp_path / "models" / "embedding",
        embedding_model=tmp_path / "models" / "embedding" / "embedding.gguf",
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
