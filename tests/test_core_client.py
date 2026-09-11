import asyncio
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from meocosub2 import core_client
from meocosub2.core_client import (
    CORE_CAPABILITIES,
    CoreClient,
    CoreProtocolError,
    CoreTimeoutError,
)


class FakeOutput:
    def __init__(self, process) -> None:
        self.process = process
        self.lines: queue.Queue[str] = queue.Queue()
        self.closed = False

    def readline(self, size=-1) -> str:
        line = self.lines.get(timeout=5)
        if 0 < size < len(line):
            self.lines.put(line[size:])
            return line[:size]
        if self.process.exit_after_read:
            self.process.alive = False
        return line

    def close(self) -> None:
        self.closed = True


class EmptyStderr:
    def __init__(self) -> None:
        self.closed = False

    def readline(self, size=-1) -> str:
        return ""

    def close(self) -> None:
        self.closed = True


class FakeInput:
    def __init__(self, process) -> None:
        self.process = process
        self.closed = False

    def write(self, frame: str) -> int:
        if self.process.block_write:
            self.process.write_released.wait(timeout=5)
            if not self.process.alive:
                raise BrokenPipeError("process ended")
        self.process.receive(json.loads(frame))
        return len(frame)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self, storage_root: Path, handler) -> None:
        self.pid = 42
        self.alive = True
        self.exit_after_read = False
        self.block_write = False
        self.write_released = threading.Event()
        self.storage_root = storage_root
        self.handler = handler
        self.frames: list[dict] = []
        self.stdout = FakeOutput(self)
        self.stderr = EmptyStderr()
        self.stdin = FakeInput(self)

    def receive(self, frame: dict) -> None:
        self.frames.append(frame)
        if frame["method"] == "hello":
            self.send(
                frame["id"],
                result={
                    "version": "0.1.0",
                    "api": 1,
                    "capabilities": sorted(CORE_CAPABILITIES),
                    "model": "HY-MT1.5-1.8B-Q4_K_M",
                    "storageRoot": str(self.storage_root),
                },
            )
            return
        self.handler(self, frame)

    def send(self, request_id: int, **body) -> None:
        self.stdout.lines.put(json.dumps({"id": request_id, **body}) + "\n")

    def poll(self):
        return None if self.alive else 0

    def terminate(self) -> None:
        if self.alive:
            self.alive = False
            self.write_released.set()
            self.stdout.lines.put("")

    kill = terminate

    def wait(self, timeout=None) -> int:
        self.alive = False
        return 0


@pytest.fixture
def client_factory(monkeypatch, tmp_path: Path):
    processes: list[FakeProcess] = []

    def make(handler):
        def spawn(*args, **kwargs):
            process = FakeProcess(tmp_path.resolve(), handler)
            processes.append(process)
            return process

        monkeypatch.setattr(core_client.subprocess, "Popen", spawn)
        monkeypatch.setattr(core_client, "attach_process_to_lifetime", lambda process: None)
        monkeypatch.setattr(core_client, "close_process_job", lambda process: None)
        return CoreClient(Path("fake-core.exe"), legacy_roots=[]), processes

    return make


def test_handshake_progress_and_result_follow_the_pinned_jsonl_contract(client_factory) -> None:
    progress: list[str] = []

    def handler(process, frame):
        process.send(frame["id"], event="progress", message="Checking 40%")
        process.send(frame["id"], result={"installed": True})

    client, processes = client_factory(handler)
    assert client.request_sync("status", {}, timeout_s=1, progress=progress.append) == {
        "installed": True
    }
    assert progress == ["Checking 40%"]
    assert processes[0].frames[0]["method"] == "hello"
    assert processes[0].frames[0]["params"]["expectedVersion"] == "0.1.0"
    assert processes[0].frames[1] == {"id": 2, "api": 1, "method": "status", "params": {}}


def test_core_timeout_is_typed_and_discards_the_process(client_factory) -> None:
    def handler(process, frame):
        process.send(frame["id"], error={"code": "OCR_TIMEOUT", "message": "late"})

    client, processes = client_factory(handler)
    with pytest.raises(CoreTimeoutError) as caught:
        client.request_sync("ocrRecognize", {}, timeout_s=1)
    assert caught.value.code == "OCR_TIMEOUT"
    assert not processes[0].alive
    assert client.hello_result is None


def test_local_timeout_kills_and_reaps_the_owned_process(client_factory) -> None:
    client, processes = client_factory(lambda process, frame: None)
    with pytest.raises(CoreTimeoutError) as caught:
        client.request_sync("ready", {}, timeout_s=0.03)
    assert caught.value.code == "CLIENT_TIMEOUT"
    assert not processes[0].alive


def test_local_timeout_unblocks_a_full_stdin_pipe(client_factory) -> None:
    def handler(process, frame):
        process.send(frame["id"], result={"installed": True})

    client, processes = client_factory(handler)
    client.request_sync("status", {}, timeout_s=1)
    processes[0].block_write = True
    with pytest.raises(CoreTimeoutError):
        client.request_sync("ready", {}, timeout_s=0.03)
    assert not processes[0].alive


def test_waiting_for_the_serial_request_slot_does_not_abort_its_owner(client_factory) -> None:
    entered = threading.Event()

    def handler(process, frame):
        entered.set()

    client, processes = client_factory(handler)
    result: list[dict] = []
    worker = threading.Thread(
        target=lambda: result.append(client.request_sync("ready", {}, timeout_s=1))
    )
    worker.start()
    assert entered.wait(timeout=1)
    with pytest.raises(CoreTimeoutError):
        client.request_sync("status", {}, timeout_s=0.02)
    assert processes[0].alive
    processes[0].send(2, result={"managedConfig": {"port": 1}})
    worker.join(timeout=1)
    assert result == [{"managedConfig": {"port": 1}}]


@pytest.mark.asyncio
async def test_async_queue_timeout_does_not_abort_the_active_request(client_factory) -> None:
    entered = threading.Event()

    def handler(process, frame):
        entered.set()

    client, processes = client_factory(handler)
    active = asyncio.create_task(client.request("install", {}, timeout_s=1))
    assert await asyncio.to_thread(entered.wait, 1)
    with pytest.raises(CoreTimeoutError):
        await client.request("status", {}, timeout_s=0.03)
    assert processes[0].alive
    assert [frame["method"] for frame in processes[0].frames] == ["hello", "install"]
    processes[0].send(2, result={"installed": True})
    assert await active == {"installed": True}


@pytest.mark.asyncio
async def test_cancelling_a_queued_request_never_starts_or_aborts_it(client_factory) -> None:
    entered = threading.Event()

    def handler(process, frame):
        entered.set()

    client, processes = client_factory(handler)
    active = asyncio.create_task(client.request("install", {}, timeout_s=1))
    assert await asyncio.to_thread(entered.wait, 1)
    queued = asyncio.create_task(client.request("status", {}, timeout_s=1))
    await asyncio.sleep(0.02)
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    assert processes[0].alive
    assert [frame["method"] for frame in processes[0].frames] == ["hello", "install"]
    processes[0].send(2, result={"installed": True})
    assert await active == {"installed": True}


@pytest.mark.asyncio
async def test_cancelling_active_completion_drains_and_reuses_the_process(client_factory) -> None:
    started = threading.Event()
    completions = 0

    def handler(process, frame):
        nonlocal completions
        completions += 1
        if completions == 1:
            started.set()
        else:
            process.send(frame["id"], result={"choices": []})

    client, processes = client_factory(handler)
    cancelled = asyncio.create_task(client.request("complete", {}, timeout_s=1))
    assert await asyncio.to_thread(started.wait, 1)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert processes[0].alive
    processes[0].send(2, result={"choices": []})
    assert await client.request("complete", {}, timeout_s=1) == {"choices": []}
    assert len(processes) == 1
    assert [frame["method"] for frame in processes[0].frames] == [
        "hello",
        "complete",
        "complete",
    ]


@pytest.mark.asyncio
async def test_cancelling_during_spawn_discards_before_the_handshake(
    client_factory, monkeypatch
) -> None:
    client, processes = client_factory(lambda process, frame: None)
    spawn = core_client.subprocess.Popen
    entered = threading.Event()
    release = threading.Event()

    def delayed_spawn(*args, **kwargs):
        entered.set()
        release.wait(timeout=1)
        return spawn(*args, **kwargs)

    monkeypatch.setattr(core_client.subprocess, "Popen", delayed_spawn)
    request = asyncio.create_task(client.request("status", {}, timeout_s=1))
    assert await asyncio.to_thread(entered.wait, 1)
    request.cancel()
    await asyncio.sleep(0.02)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert len(processes) == 1
    assert processes[0].frames == []
    assert not processes[0].alive


def test_restart_cleans_an_already_exited_process_before_replacing_it(
    client_factory, monkeypatch
) -> None:
    def handler(process, frame):
        process.send(frame["id"], result={"installed": True})

    client, processes = client_factory(handler)
    client.request_sync("status", {}, timeout_s=1)
    stale = processes[0]
    stale.alive = False
    cleaned: list[FakeProcess] = []
    terminate = core_client.terminate_process

    def record_cleanup(process):
        cleaned.append(process)
        terminate(process)

    monkeypatch.setattr(core_client, "terminate_process", record_cleanup)
    client.request_sync("status", {}, timeout_s=1)
    assert cleaned == [stale]
    assert stale.stdin.closed and stale.stdout.closed and stale.stderr.closed
    assert len(processes) == 2


def test_oversized_or_unterminated_response_fails_closed(client_factory) -> None:
    def handler(process, frame):
        process.stdout.lines.put("{" + "x" * core_client.FRAME_BYTES)

    client, processes = client_factory(handler)
    with pytest.raises(CoreProtocolError, match="oversized"):
        client.request_sync("status", {}, timeout_s=1)
    assert not processes[0].alive


@pytest.mark.skipif(
    not Path(os.environ.get("MEOWCAL_CORE_EXE", "missing")).is_file(),
    reason="a real pinned Core executable was not supplied",
)
def test_real_core_process_handshake_and_status(tmp_path: Path) -> None:
    client = CoreClient(
        Path(os.environ["MEOWCAL_CORE_EXE"]),
        profile="development",
        storage_root=tmp_path,
        legacy_roots=[],
    )
    try:
        result = client.request_sync("status", {}, timeout_s=15)
        assert isinstance(result.get("installed"), bool)
        assert client.hello_result["version"] == "0.1.0"
    finally:
        client.close_sync()


@pytest.mark.skipif(os.name != "nt", reason="Windows job objects are platform-specific")
def test_windows_job_owned_child_is_killed_and_reaped() -> None:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        core_client.attach_process_to_lifetime(process)
        core_client.close_process_job(process)
        process.wait(timeout=3)
        assert not hasattr(process, "_meowcal_core_job")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
