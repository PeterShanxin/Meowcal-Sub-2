import asyncio
import io
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
    CoreError,
    CoreProtocolError,
    CoreTimeoutError,
)


class FakeOutput(io.RawIOBase):
    def __init__(self, process) -> None:
        self.process = process
        self.lines: queue.Queue[bytes] = queue.Queue()

    def readline(self, size=-1) -> bytes:
        line = self.lines.get(timeout=5)
        if 0 < size < len(line):
            self.lines.put(line[size:])
            return line[:size]
        if self.process.exit_after_read:
            self.process.alive = False
        return line

    def readable(self):
        return True

    def readinto(self, buffer):
        data = self.readline(len(buffer))
        buffer[: len(data)] = data
        return len(data)

    def close(self) -> None:
        super().close()


class EmptyStderr(io.RawIOBase):
    def __init__(self) -> None:
        super().__init__()

    def readline(self, size=-1) -> bytes:
        return b""

    def readable(self):
        return True

    def readinto(self, buffer):
        data = self.readline(len(buffer))
        buffer[: len(data)] = data
        return len(data)

    def close(self) -> None:
        super().close()


class FakeInput(io.RawIOBase):
    def __init__(self, process) -> None:
        self.process = process
        self.pending = bytearray()
        self.frame = None

    def write(self, frame: bytes) -> int:
        if self.process.block_write:
            self.process.write_released.wait(timeout=5)
            if not self.process.alive:
                raise BrokenPipeError("process ended")
        self.pending.extend(frame)
        if self.frame is None and b"\n" in self.pending:
            header, self.pending = self.pending.split(b"\n", 1)
            self.frame = json.loads(header)
        if self.frame is not None and len(self.pending) == self.frame["payloadBytes"]:
            received, self.frame = self.frame, None
            self.pending.clear()
            self.process.receive(received)
        return len(frame)

    def close(self) -> None:
        super().close()


class FakeProcess:
    def __init__(self, storage_root: Path, handler, version: str = "0.1.0") -> None:
        self.pid = 42
        self.alive = True
        self.exit_after_read = False
        self.block_write = False
        self.write_released = threading.Event()
        self.storage_root = storage_root
        self.handler = handler
        self.version = version
        self.frames: list[dict] = []
        self.stdout = FakeOutput(self)
        self.output = self.stdout
        self.stderr = EmptyStderr()
        self.stdin = FakeInput(self)

    def receive(self, frame: dict) -> None:
        self.frames.append(frame)
        if frame["method"] == "hello":
            self.send(
                frame["id"],
                result={
                    "version": self.version,
                    "api": 1,
                    "capabilities": sorted(CORE_CAPABILITIES),
                    "model": "HY-MT1.5-1.8B-Q4_K_M",
                    "storageRoot": str(self.storage_root),
                },
            )
            return
        self.handler(self, frame)

    def send(self, request_id: int, **body) -> None:
        self.output.lines.put((json.dumps({"id": request_id, **body}) + "\n").encode())

    def poll(self):
        return None if self.alive else 0

    def terminate(self) -> None:
        if self.alive:
            self.alive = False
            self.write_released.set()
            self.output.lines.put(b"")

    kill = terminate

    def wait(self, timeout=None) -> int:
        self.alive = False
        return 0


@pytest.fixture
def client_factory(monkeypatch, tmp_path: Path):
    processes: list[FakeProcess] = []

    def make(handler, version: str = "0.1.0", metadata_version: str | None = None):
        executable = tmp_path / "fake-core.exe"
        executable.touch()
        if metadata_version is not None:
            (tmp_path / "meowcal-core.json").write_text(
                json.dumps({"coreVersion": metadata_version, "apiVersion": 1}),
                encoding="utf-8",
            )

        def spawn(*args, **kwargs):
            process = FakeProcess(tmp_path.resolve(), handler, version=version)
            processes.append(process)
            return process

        monkeypatch.setattr(core_client.subprocess, "Popen", spawn)
        monkeypatch.setattr(core_client, "attach_process_to_lifetime", lambda process: None)
        monkeypatch.setattr(core_client, "close_process_job", lambda process: None)
        return CoreClient(executable, legacy_roots=[]), processes

    return make


def test_pinned_metadata_drives_the_real_consumer_handshake(client_factory) -> None:
    client, processes = client_factory(
        lambda process, frame: process.send(frame["id"], result={"installed": True}),
        version="0.1.1",
        metadata_version="0.1.1",
    )

    assert client.request_sync("status", {}, timeout_s=1) == {"installed": True}
    assert processes[0].frames[0]["params"]["expectedVersion"] == "0.1.1"


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
    assert processes[0].frames[1] == {
        "id": 2,
        "api": 1,
        "method": "status",
        "params": {},
        "payloadBytes": 0,
    }


def test_core_timeout_is_typed_and_discards_the_process(client_factory) -> None:
    def handler(process, frame):
        process.send(frame["id"], error={"code": "OCR_TIMEOUT", "message": "late"})

    client, processes = client_factory(handler)
    with pytest.raises(CoreTimeoutError) as caught:
        client.request_sync("ocrRecognizeBgra", ocr_params(), payload=bytes(8), timeout_s=1)
    assert caught.value.code == "OCR_TIMEOUT"
    assert not processes[0].alive
    assert client.hello_result is None


def test_local_timeout_kills_and_reaps_the_owned_process(client_factory) -> None:
    client, processes = client_factory(lambda process, frame: None)
    with pytest.raises(CoreTimeoutError) as caught:
        client.request_sync("ready", {}, timeout_s=0.03)
    assert caught.value.code == "CLIENT_TIMEOUT"
    assert not processes[0].alive


def test_unusable_native_process_is_discarded_before_recovery(client_factory) -> None:
    failed = False

    def handler(process, frame):
        nonlocal failed
        if not failed:
            failed = True
            process.send(
                frame["id"], error={"code": "OCR_PROCESS_UNUSABLE", "message": "lost callback"}
            )
        else:
            process.send(frame["id"], result={"recovered": True})

    client, processes = client_factory(handler)
    with pytest.raises(CoreError) as caught:
        client.request_sync("ocrRecognizeBgra", ocr_params(), payload=bytes(8), timeout_s=1)
    assert caught.value.code == "OCR_PROCESS_UNUSABLE"
    assert not processes[0].alive
    assert client.hello_result is None
    assert client.request_sync("status", {}, timeout_s=1) == {"recovered": True}
    assert len(processes) == 2


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
        process.output.lines.put(b"{" + b"x" * core_client.FRAME_BYTES)

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


@pytest.fixture
def pipe_client(monkeypatch, tmp_path):
    script = tmp_path / "core_fixture.py"
    script.write_text(
        """import json, sys, time
from pathlib import Path
stream = sys.stdin.buffer
while True:
    line = stream.readline()
    if not line:
        break
    request = json.loads(line)
    method = request['method']
    if method == 'hello':
        caps = json.loads(sys.argv[2])
        if sys.argv[3] == 'legacy':
            caps[caps.index('ocrRecognizeBgra')] = 'ocrRecognize'
        result = dict(version='0.1.0', api=1, capabilities=caps,
                      model='test', storageRoot=sys.argv[1])
    elif method == 'ocrRecognizeBgra':
        if sys.argv[3] == 'stall':
            Path(sys.argv[1], "header-read").touch()
            time.sleep(30)
        body = stream.read(request['payloadBytes'])
        if sys.argv[3] == 'stall-response':
            time.sleep(30)
        result = dict(length=len(body), checksum=sum(body))
    else:
        result = dict(installed=True)
    print(json.dumps(dict(id=request['id'], result=result)), flush=True)
    if method == 'shutdown':
        break
""",
        encoding="utf-8",
    )
    spawn = subprocess.Popen
    clients = []

    def make(mode="echo"):
        def start(*args, **kwargs):
            return spawn(
                [
                    sys.executable,
                    "-u",
                    str(script),
                    str(tmp_path),
                    json.dumps(sorted(CORE_CAPABILITIES)),
                    mode,
                ],
                **kwargs,
            )

        monkeypatch.setattr(core_client.subprocess, "Popen", start)
        client = CoreClient(script, legacy_roots=[])
        clients.append(client)
        return client

    make.marker = tmp_path / "header-read"
    yield make
    for client in clients:
        client.abort()


def ocr_params(width=2, height=1):
    return dict(language="en-US", width=width, height=height, stride=width * 4, timeoutMs=1000)


def test_binary_pipe_preserves_newlines_and_next_control_frame(pipe_client):
    client = pipe_client()
    pixels = bytes([0, 10, 13, 255, 123, 34, 0, 255])
    result = client.request_sync("ocrRecognizeBgra", ocr_params(), payload=pixels, timeout_s=3)
    assert result == {"length": len(pixels), "checksum": sum(pixels)}
    assert client.request_sync("status", {}, timeout_s=3) == {"installed": True}


def test_legacy_ocr_capability_fails_before_pixels_are_sent(pipe_client):
    client = pipe_client("legacy")
    with pytest.raises(CoreProtocolError, match="pinned contract"):
        client.request_sync("ocrRecognizeBgra", ocr_params(), payload=bytes(8), timeout_s=3)
    assert client.process_generation is None


@pytest.mark.asyncio
async def test_cancellation_unblocks_real_binary_body_write_and_restarts(pipe_client):
    client = pipe_client("stall")
    task = asyncio.create_task(
        client.request(
            "ocrRecognizeBgra",
            ocr_params(4096, 1024),
            payload=bytes(16 * 1024 * 1024),
            timeout_s=5,
        )
    )

    async def wait_for_header():
        while not pipe_client.marker.exists():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait_for_header(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 3)
    assert client.process_generation is None
    assert await client.request("status", {}, timeout_s=3) == {"installed": True}


def test_deadline_unblocks_real_binary_body_write(pipe_client):
    client = pipe_client("stall")
    with pytest.raises(CoreTimeoutError):
        client.request_sync(
            "ocrRecognizeBgra",
            ocr_params(4096, 1024),
            payload=bytes(16 * 1024 * 1024),
            timeout_s=0.3,
        )
    assert client.process_generation is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["stall", "stall-response"])
async def test_async_ocr_deadline_stops_blocked_io_without_a_timer_thread(
    pipe_client, monkeypatch, mode
):
    client = pipe_client(mode)
    await client.request("status", {}, timeout_s=3)
    owned = client._process
    width, height = (4096, 1024) if mode == "stall" else (2, 1)

    def unexpected_timer(*args, **kwargs):
        raise AssertionError("Async OCR must use its existing event-loop deadline")

    with monkeypatch.context() as patch:
        patch.setattr(core_client.threading, "Timer", unexpected_timer)
        with pytest.raises(CoreTimeoutError):
            await asyncio.wait_for(
                client.request(
                    "ocrRecognizeBgra",
                    ocr_params(width, height),
                    payload=bytes(width * height * 4),
                    timeout_s=0.3,
                ),
                timeout=3,
            )
    assert client.process_generation is None
    assert owned.poll() is not None
    assert await client.request("status", {}, timeout_s=3) == {"installed": True}


@pytest.mark.parametrize(
    "params,payload",
    [
        (ocr_params(), bytes(7)),
        ({**ocr_params(), "stride": 9}, bytes(9)),
        ({**ocr_params(), "timeoutMs": 30001}, bytes(8)),
        ({**ocr_params(), "width": True}, bytes(8)),
        ({**ocr_params(), "bgraBase64": "AA=="}, bytes(8)),
    ],
)
def test_invalid_binary_layout_is_rejected_before_launch(client_factory, params, payload):
    client, processes = client_factory(lambda process, frame: None)
    with pytest.raises(CoreProtocolError, match="packed BGRA"):
        client.request_sync("ocrRecognizeBgra", params, payload=payload, timeout_s=1)
    assert processes == []


def test_short_writes_send_exactly_one_header_and_body(client_factory, monkeypatch):
    client, processes = client_factory(lambda process, frame: process.send(frame["id"], result={}))
    client.request_sync("status", {}, timeout_s=1)
    process = processes[0]
    transmitted = bytearray()

    def short_write(part):
        count = min(3, len(part))
        transmitted.extend(part[:count])
        if b"\n" in transmitted:
            header, body = transmitted.split(b"\n", 1)
            request = json.loads(header)
            if len(body) == request["payloadBytes"]:
                process.send(request["id"], result={"text": "ok"})
        return count

    monkeypatch.setattr(process.stdin, "write", short_write)
    pixels = b"\n\r\x00\xff" * 2
    assert client.request_sync("ocrRecognizeBgra", ocr_params(), payload=pixels, timeout_s=1) == {
        "text": "ok"
    }
    header, body = transmitted.split(b"\n", 1)
    assert json.loads(header)["payloadBytes"] == len(pixels)
    assert body == pixels


def test_failed_partial_write_discards_transport_before_recovery(client_factory, monkeypatch):
    client, processes = client_factory(lambda process, frame: process.send(frame["id"], result={}))
    client.request_sync("status", {}, timeout_s=1)
    calls = 0

    def broken_write(part):
        nonlocal calls
        calls += 1
        if calls == 1:
            return 2
        raise BrokenPipeError("partial header")

    monkeypatch.setattr(processes[0].stdin, "write", broken_write)
    with pytest.raises(BrokenPipeError):
        client.request_sync("ocrRecognizeBgra", ocr_params(), payload=bytes(8), timeout_s=1)
    assert not processes[0].alive
    assert client.request_sync("status", {}, timeout_s=1) == {}
    assert len(processes) == 2


@pytest.mark.parametrize("response", [b"not json\n", b'{"id":999,"result":{}}\n', b"\xff\n"])
def test_malformed_binary_response_closes_before_recovery(client_factory, response):
    attempts = 0

    def handler(process, frame):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            process.output.lines.put(response)
        else:
            process.send(frame["id"], result={})

    client, processes = client_factory(handler)
    with pytest.raises(CoreProtocolError):
        client.request_sync("status", {}, timeout_s=1)
    assert not processes[0].alive
    assert client.request_sync("status", {}, timeout_s=1) == {}
    assert len(processes) == 2


@pytest.mark.skipif(os.name != "nt", reason="Windows job objects are platform-specific")
def test_concurrent_cleanup_closes_job_handle_once(mocker):
    import ctypes
    from types import SimpleNamespace

    from meocosub2.core_process import close_process_job

    entered, release = threading.Event(), threading.Event()
    kernel = mocker.Mock()

    def close_handle(handle):
        entered.set()
        assert release.wait(1)
        return True

    kernel.CloseHandle.side_effect = close_handle
    mocker.patch.object(ctypes, "WinDLL", return_value=kernel)
    process = SimpleNamespace(_meowcal_core_job=123)
    cleanup = threading.Thread(target=close_process_job, args=(process,))
    cleanup.start()
    try:
        assert entered.wait(1)
        close_process_job(process)
    finally:
        release.set()
        cleanup.join(1)
    kernel.CloseHandle.assert_called_once_with(123)
