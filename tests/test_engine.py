import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from meocosub2 import engine
from meocosub2.core_client import CoreError
from meocosub2.engine import install as install_module
from meocosub2.engine import runtime as runtime_module
from meocosub2.engine.manifest import load_manifest
from meocosub2.engine.paths import InstallPaths, own_paths
from meocosub2.engine.runtime import LaunchPlan, embedding_plan, launch_arguments, worker_threads


@pytest.fixture
def manifest():
    return load_manifest()


def test_manifest_contains_only_the_independent_bge_workload(manifest) -> None:
    raw = json.loads(Path(engine.__file__).with_name("manifest.json").read_text(encoding="utf-8"))
    assert "model" not in raw
    assert "HY-MT" not in json.dumps(raw)
    assert manifest.embedding.artifact.size_bytes == 26_472_640
    assert manifest.runtime_for_host().executable.relative_path == "llama-server.exe"


def test_matching_model_has_its_own_runtime_tree(manifest, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths = own_paths(manifest, manifest.runtime_for_host())
    assert paths.root == tmp_path / "com.meowcal.sub2" / "engine"
    assert paths.executable.is_relative_to(paths.root)
    assert paths.embedding_model.is_relative_to(paths.root)


def a_plan(**overrides) -> LaunchPlan:
    fields = {
        "executable": Path("llama-server.exe"),
        "model": Path("embedding.gguf"),
        "alias": "test-model",
        "host": "127.0.0.1",
        "preferred_port": 11437,
        "context_size": 512,
        "extra_args": ("--embedding", "--pooling", "cls"),
    }
    return LaunchPlan(**{**fields, **overrides})


def test_matching_launch_is_cpu_cls_embedding(manifest) -> None:
    runtime = manifest.runtime_for_host()
    arguments = launch_arguments(embedding_plan(own_paths(manifest, runtime), manifest), 12345)
    assert arguments[arguments.index("--port") + 1] == "12345"
    assert arguments[arguments.index("-ngl") + 1] == "0"
    assert arguments[arguments.index("--pooling") + 1] == "cls"
    assert "--embedding" in arguments


class FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.terminated = False

    def poll(self):
        return 1 if self.terminated else None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True

    def wait(self, timeout=None) -> int:
        return 0


def test_starting_a_matcher_stops_the_one_it_replaces(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "llama-server.exe"
    model = tmp_path / "embedding.gguf"
    executable.write_bytes(b"x")
    model.write_bytes(b"x")
    paths = InstallPaths(tmp_path, tmp_path, tmp_path / "runtime.zip", executable, tmp_path, model)
    spawned: list[FakeProcess] = []
    monkeypatch.setattr(
        runtime_module.subprocess,
        "Popen",
        lambda *args, **kwargs: spawned.append(FakeProcess(len(spawned))) or spawned[-1],
    )
    monkeypatch.setattr(runtime_module, "attach_process_to_lifetime", lambda process: None)
    monkeypatch.setattr(runtime_module, "close_process_job", lambda process: None)
    try:
        runtime_module._start(a_plan(executable=executable, model=model), paths)
        runtime_module._start(a_plan(executable=executable, model=model), paths)
        assert spawned[0].terminated
        assert not spawned[1].terminated
    finally:
        runtime_module.shutdown()


@pytest.mark.parametrize(
    "failure", [OSError("terminate failed"), subprocess.TimeoutExpired("matcher", 3)]
)
def test_failed_matcher_attachment_kills_and_reaps_child(tmp_path, monkeypatch, failure):
    executable = tmp_path / "llama-server.exe"
    model = tmp_path / "embedding.gguf"
    executable.write_bytes(b"x")
    model.write_bytes(b"x")
    paths = InstallPaths(tmp_path, tmp_path, tmp_path / "runtime.zip", executable, tmp_path, model)
    child = MagicMock()
    child.poll.return_value = None
    child.stdin = child.stdout = child.stderr = None
    if isinstance(failure, OSError):
        child.terminate.side_effect = failure
        child.wait.return_value = 0
    else:
        child.wait.side_effect = [failure, 0]
    monkeypatch.setattr(runtime_module.subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(runtime_module, "_owned", None)
    monkeypatch.setattr(
        runtime_module, "attach_process_to_lifetime", MagicMock(side_effect=OSError("job refused"))
    )
    with pytest.raises(runtime_module.EngineStartError, match="ownership failed"):
        runtime_module._start(a_plan(executable=executable, model=model), paths)
    child.kill.assert_called_once()
    assert child.wait.call_args.kwargs == {"timeout": 3}
    assert runtime_module._owned is None


def test_matching_runtime_leaves_cores_for_capture_and_ocr() -> None:
    assert worker_threads(12) == 8
    assert worker_threads(4) == 4
    assert worker_threads(1) == 4


def test_same_size_corruption_is_not_a_complete_bge_install(
    tmp_path: Path, manifest, monkeypatch
) -> None:
    runtime = manifest.runtime_for_host()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    paths = own_paths(manifest, runtime)
    paths.executable.parent.mkdir(parents=True)
    paths.embedding_model.parent.mkdir(parents=True)
    paths.executable.write_bytes(b"x" * runtime.executable.size_bytes)
    paths.embedding_model.write_bytes(b"x" * manifest.embedding.artifact.size_bytes)
    assert not paths.embedding_is_complete(manifest, runtime)


def test_a_truncated_artifact_fails_verification(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"short")
    assert not install_module.file_matches(artifact, 999, "0" * 64)


class FakeCore:
    def __init__(self) -> None:
        self.hello_result = {"model": "HY-MT1.5-1.8B-Q4_K_M"}
        self.process_generation = 1
        self.installed = False
        self.sync_calls: list[str] = []
        self.async_calls: list[tuple[str, dict]] = []

    def request_sync(self, method, params, *, timeout_s, progress=None):
        self.sync_calls.append(method)
        if method == "status":
            return {
                "installed": self.installed,
                "ready": False,
                "model": self.hello_result["model"],
            }
        self.installed = True
        return {"installed": True, "ready": False, "model": self.hello_result["model"]}

    async def request(self, method, params, *, timeout_s):
        self.async_calls.append((method, params))
        if method == "ready":
            if self.process_generation is None:
                self.process_generation = 2
            return {"managedConfig": {"port": 54321}}
        return {"choices": [{"message": {"content": "Okay."}}]}


def test_status_does_not_start_or_install_the_model(monkeypatch) -> None:
    fake = FakeCore()
    monkeypatch.setattr(engine, "_core", lambda: fake)
    monkeypatch.setattr(engine, "_install_job", None)
    result = engine.status()
    assert result.phase == "needsSetup"
    assert fake.sync_calls == ["status"]


@pytest.mark.asyncio
async def test_ready_and_complete_use_core_with_the_pinned_model(monkeypatch) -> None:
    fake = FakeCore()
    monkeypatch.setattr(engine, "_core", lambda: fake)
    monkeypatch.setattr(engine, "_ready_generation", None)
    monkeypatch.setattr(engine, "_ready_endpoint", None)
    assert await engine.ensure_ready() == "http://127.0.0.1:54321"
    response = await engine.complete({"messages": [], "model": "wrong"}, 5.0)
    assert response["choices"][0]["message"]["content"] == "Okay."
    assert fake.async_calls[1][0] == "complete"
    request = fake.async_calls[1][1]
    assert request["request"]["model"] == "HY-MT1.5-1.8B-Q4_K_M"
    assert request["timeoutMs"] == 5000


@pytest.mark.asyncio
async def test_unverified_legacy_assets_keep_the_existing_setup_error(monkeypatch) -> None:
    fake = FakeCore()

    async def unverified(*args, **kwargs):
        raise CoreError("CORE_ASSETS_UNVERIFIED", "Run Install/Repair from Settings.")

    fake.request = unverified
    monkeypatch.setattr(engine, "_core", lambda: fake)
    monkeypatch.setattr(engine, "_ready_generation", None)
    monkeypatch.setattr(engine, "_ready_endpoint", None)
    monkeypatch.setattr(engine, "_repair_error", "")
    with pytest.raises(engine.EngineInstallError, match="Install/Repair"):
        await engine.ensure_ready()
    assert engine.status().message == engine.REPAIR_REQUIRED_MESSAGE


@pytest.mark.asyncio
async def test_completions_do_not_repeat_ready_for_the_same_process(monkeypatch) -> None:
    fake = FakeCore()
    monkeypatch.setattr(engine, "_core", lambda: fake)
    monkeypatch.setattr(engine, "_ready_generation", None)
    monkeypatch.setattr(engine, "_ready_endpoint", None)
    await engine.ensure_ready()
    await engine.complete({"messages": []}, 1)
    assert await engine.complete({"messages": []}, 1) == {
        "choices": [{"message": {"content": "Okay."}}]
    }
    assert [method for method, _ in fake.async_calls] == ["ready", "complete", "complete"]


@pytest.mark.asyncio
async def test_new_core_generation_is_made_ready_before_completion(monkeypatch) -> None:
    fake = FakeCore()
    monkeypatch.setattr(engine, "_core", lambda: fake)
    monkeypatch.setattr(engine, "_ready_generation", None)
    monkeypatch.setattr(engine, "_ready_endpoint", None)
    await engine.ensure_ready()
    fake.process_generation = None
    await engine.complete({"messages": []}, 1)
    assert [method for method, _ in fake.async_calls] == ["ready", "ready", "complete"]
    assert fake.process_generation == 2


def test_failed_asset_verification_unlocks_install_repair(monkeypatch) -> None:
    fake = FakeCore()
    fake.sync_calls = []
    monkeypatch.setattr(engine, "_core", lambda: fake)
    monkeypatch.setattr(engine, "_install_job", None)
    monkeypatch.setattr(engine, "_repair_error", "Run Install/Repair from Settings.")
    assert engine.status().phase == "failed"
    installing = engine.install_engine()
    assert installing.phase == "installing"
    assert engine._install_job.thread is not None
    engine._install_job.thread.join(timeout=1)
    assert "install" in fake.sync_calls
    assert engine.status().phase == "idle"


@pytest.mark.asyncio
async def test_repair_invalidates_ready_state_until_core_is_started_again(monkeypatch) -> None:
    fake = FakeCore()
    monkeypatch.setattr(engine, "_core", lambda: fake)
    monkeypatch.setattr(engine, "_install_job", None)
    monkeypatch.setattr(engine, "_repair_error", "")
    monkeypatch.setattr(engine, "_ready_generation", None)
    monkeypatch.setattr(engine, "_ready_endpoint", None)

    await engine.ensure_ready()
    engine._repair_error = engine.REPAIR_REQUIRED_MESSAGE
    assert engine.install_engine().phase == "installing"
    assert engine._install_job is not None
    assert engine._install_job.thread is not None
    engine._install_job.thread.join(timeout=1)

    await engine.ensure_ready()
    assert [method for method, _ in fake.async_calls] == ["ready", "ready"]


@pytest.mark.asyncio
async def test_successful_ready_clears_a_completed_install_error(monkeypatch) -> None:
    fake = FakeCore()
    stale_job = engine._InstallJob(error="Previous install failed.", done=True)
    monkeypatch.setattr(engine, "_core", lambda: fake)
    monkeypatch.setattr(engine, "_install_job", stale_job)
    monkeypatch.setattr(engine, "_repair_error", "")
    monkeypatch.setattr(engine, "_ready_generation", None)
    monkeypatch.setattr(engine, "_ready_endpoint", None)

    await engine.ensure_ready()

    assert stale_job.error == ""


@pytest.mark.asyncio
async def test_missing_bge_install_downloads_private_runtime_and_model(
    manifest, monkeypatch
) -> None:
    runtime = manifest.runtime_for_host()
    paths = own_paths(manifest, runtime)
    monkeypatch.setattr(engine, "own_paths", lambda *_: paths)
    monkeypatch.setattr(InstallPaths, "embedding_is_complete", lambda *_: False)
    installed = MagicMock()
    monkeypatch.setattr(engine.embedding_install, "install_embedding", installed)
    monkeypatch.setattr(
        engine.embedding_runtime,
        "ensure_embedding_ready",
        AsyncMock(return_value="http://127.0.0.1:11437"),
    )
    assert await engine.ensure_embedding_ready() == "http://127.0.0.1:11437"
    installed.assert_called_once_with(paths, manifest, runtime)


def test_backend_shutdown_closes_translation_ocr_and_bge(monkeypatch) -> None:
    class ClosableCore:
        closed = False

        def close_sync(self):
            self.closed = True

    core = ClosableCore()
    monkeypatch.setattr(engine, "_client", core)
    bge_shutdown = MagicMock()
    monkeypatch.setattr(engine.embedding_runtime, "shutdown", bge_shutdown)
    from meocosub2 import native_ocr

    ocr_shutdown = MagicMock()
    monkeypatch.setattr(native_ocr, "shutdown", ocr_shutdown)
    engine.shutdown()
    assert core.closed
    bge_shutdown.assert_called_once_with()
    ocr_shutdown.assert_called_once_with()
