"""Typed binary-framed client for the version-pinned Meowcal Core process."""

from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import threading
from collections import deque
from collections.abc import Callable, Iterable
from pathlib import Path
from time import monotonic
from typing import Any

from meocosub2.core_process import (
    attach_process_to_lifetime,
    close_process_job,
    core_profile,
    core_storage_override,
    drain_stderr,
    ended_message,
    legacy_engine_roots,
    terminate_process,
)
from meocosub2.core_process import resolve_core_executable as resolve_core_executable
from meocosub2.core_protocol import CORE_CAPABILITIES as CORE_CAPABILITIES
from meocosub2.core_protocol import (
    CORE_VERSION,
    FRAME_BYTES,
    PROGRESS_CHARS,
    CoreClientError,
    CoreProtocolError,
    CoreTimeoutError,
    decode_error,
    hello_params,
    settle_core_task,
    validate_hello,
    validate_payload,
    write_request,
)
from meocosub2.core_protocol import CoreError as CoreError

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

ProgressCallback = Callable[[str], None]


class CoreClient:
    """One owned Core subprocess with serialized request/response traffic."""

    def __init__(
        self,
        executable: Path,
        *,
        client: str = "sub2",
        profile: str | None = None,
        storage_root: Path | None = None,
        legacy_roots: Iterable[Path] | None = None,
        expected_version: str = CORE_VERSION,
    ) -> None:
        self._executable = executable.resolve()
        self._client = client
        self._profile = profile or core_profile()
        self._storage_root = storage_root.resolve() if storage_root else core_storage_override()
        roots = legacy_engine_roots(self._profile) if legacy_roots is None else legacy_roots
        self._legacy_roots = tuple(Path(root).resolve() for root in roots)
        self._expected_version = expected_version
        self._request_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._next_id = 1
        self._next_token = 1
        self._active_token: int | None = None
        self._generation = 0
        self._hello: dict[str, Any] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=12)

    @property
    def hello_result(self) -> dict[str, Any] | None:
        return dict(self._hello) if self._hello is not None else None

    def request_sync(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout_s: float,
        progress: ProgressCallback | None = None,
        payload: bytes = b"",
    ) -> dict[str, Any]:
        return self._request_sync(
            method,
            params,
            timeout_s=timeout_s,
            progress=progress,
            payload=payload,
            token=self._request_token(),
            cancelled=threading.Event(),
        )

    def _request_sync(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout_s: float,
        progress: ProgressCallback | None,
        payload: bytes,
        token: int,
        cancelled: threading.Event,
        externally_timed: bool = False,
    ) -> dict[str, Any]:
        validate_payload(method, params, payload)
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        deadline = monotonic() + timeout_s
        while True:
            if cancelled.is_set():
                raise CoreClientError(f"Core {method} was cancelled")
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise CoreTimeoutError("CLIENT_TIMEOUT", f"Core {method} exceeded {timeout_s:.3g}s")
            if self._request_lock.acquire(timeout=min(0.05, remaining)):
                break
        timed_out = threading.Event()

        def expire() -> None:
            timed_out.set()
            self._abort_if_active(token)

        timer = (
            None if externally_timed else threading.Timer(max(0, deadline - monotonic()), expire)
        )
        if timer is not None:
            timer.daemon = True
        try:
            with self._state_lock:
                self._active_token = token
            if cancelled.is_set():
                raise CoreClientError(f"Core {method} was cancelled")
            if timer is not None:
                timer.start()
            if timed_out.is_set():
                raise CoreTimeoutError("CLIENT_TIMEOUT", f"Core {method} exceeded {timeout_s:.3g}s")
            process, started = self._ensure_started(cancelled, timed_out)
            if cancelled.is_set():
                if started:
                    self._discard(process)
                raise CoreClientError(f"Core {method} was cancelled")
            if timed_out.is_set():
                self._discard(process)
                raise CoreTimeoutError("CLIENT_TIMEOUT", f"Core {method} exceeded {timeout_s:.3g}s")
            result = self._exchange(process, method, params, progress, payload)
            if not isinstance(result, dict):
                self._discard(process)
                raise CoreProtocolError(f"Core {method} result must be an object")
        except (OSError, ValueError, CoreProtocolError) as error:
            if timed_out.is_set():
                raise CoreTimeoutError(
                    "CLIENT_TIMEOUT", f"Core {method} exceeded {timeout_s:.3g}s"
                ) from error
            raise
        finally:
            if timer is not None:
                timer.cancel()
            with self._state_lock:
                if self._active_token == token:
                    self._active_token = None
            self._request_lock.release()
        if timed_out.is_set():
            raise CoreTimeoutError("CLIENT_TIMEOUT", f"Core {method} exceeded {timeout_s:.3g}s")
        return result

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout_s: float,
        progress: ProgressCallback | None = None,
        payload: bytes = b"",
    ) -> dict[str, Any]:
        token = self._request_token()
        cancelled = threading.Event()
        task = asyncio.create_task(
            asyncio.to_thread(
                self._request_sync,
                method,
                params,
                timeout_s=timeout_s,
                progress=progress,
                payload=payload,
                token=token,
                cancelled=cancelled,
                # Async OCR's outer deadline aborts and drains its owned process.
                externally_timed=method == "ocrRecognizeBgra",
            )
        )
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=timeout_s)
        except CoreTimeoutError:
            raise
        except TimeoutError as error:
            cancelled.set()
            self._abort_if_active(token)
            await settle_core_task(task)
            raise CoreTimeoutError(
                "CLIENT_TIMEOUT", f"Core {method} exceeded {timeout_s:.3g}s"
            ) from error
        except asyncio.CancelledError:
            cancelled.set()
            if method == "complete":
                with self._state_lock:
                    active = self._active_token == token
                if active:
                    asyncio.create_task(settle_core_task(task))
                else:
                    await settle_core_task(task)
                raise
            self._abort_if_active(token)
            await settle_core_task(task)
            raise

    def _request_token(self) -> int:
        with self._state_lock:
            token = self._next_token
            self._next_token += 1
            return token

    @property
    def process_generation(self) -> int | None:
        with self._state_lock:
            process = self._process
            return self._generation if process is not None and process.poll() is None else None

    def _abort_if_active(self, token: int) -> None:
        with self._state_lock:
            if self._active_token != token:
                return
            process = self._process
            self._process = None
            self._hello = None
        if process is not None:
            terminate_process(process)

    def close_sync(self) -> None:
        with self._state_lock:
            process = self._process
        if process is None:
            return
        try:
            self.request_sync("shutdown", {}, timeout_s=10.0)
        except CoreClientError:
            self.abort()
            return
        self._discard(process, terminate=False)

    async def close(self) -> None:
        await asyncio.to_thread(self.close_sync)

    def abort(self) -> None:
        with self._state_lock:
            process = self._process
            if process is not None:
                self._process = None
                self._hello = None
        if process is not None:
            terminate_process(process)

    def _ensure_started(
        self, *stop_events: threading.Event
    ) -> tuple[subprocess.Popen[bytes], bool]:
        with self._state_lock:
            process = self._process
            if process is not None and process.poll() is None:
                return process, False
            if process is not None:
                self._process = None
            self._hello = None
            self._stderr_tail.clear()
        if process is not None:
            terminate_process(process)
        if any(event.is_set() for event in stop_events):
            raise CoreClientError("Core start was cancelled")
        try:
            process = subprocess.Popen(
                [str(self._executable)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                creationflags=CREATE_NO_WINDOW,
            )
        except OSError as error:
            raise CoreClientError(f"Meowcal Core could not start: {error}") from error
        if process.stdout is not None:
            process.stdout = io.BufferedReader(process.stdout)
        if process.stderr is not None:
            process.stderr = io.BufferedReader(process.stderr)
        with self._state_lock:
            self._process = process
            self._generation += 1
        if any(event.is_set() for event in stop_events):
            self._discard(process)
            raise CoreClientError("Core start was cancelled")
        try:
            attach_process_to_lifetime(process)
        except OSError as error:
            self._discard(process)
            raise CoreClientError(
                f"Meowcal Core could not be tied to the app lifetime: {error}"
            ) from error
        if process.stderr is not None:
            threading.Thread(
                target=drain_stderr,
                args=(process, self._stderr_tail, PROGRESS_CHARS),
                name="meowcal-core-stderr",
                daemon=True,
            ).start()
        try:
            hello = self._exchange(
                process,
                "hello",
                hello_params(
                    self._client,
                    self._profile,
                    self._expected_version,
                    self._legacy_roots,
                    self._storage_root,
                ),
                None,
            )
            validate_hello(hello, self._expected_version)
        except Exception:
            self._discard(process)
            raise
        self._hello = hello
        return process, True

    def _exchange(
        self,
        process: subprocess.Popen[bytes],
        method: str,
        params: dict[str, Any],
        progress: ProgressCallback | None,
        payload: bytes = b"",
    ) -> Any:
        request_id = self._next_id
        self._next_id += 1
        if process.stdin is None or process.stdout is None:
            raise CoreProtocolError("Core standard streams are unavailable")
        try:
            write_request(process.stdin, request_id, method, params, payload)
            while True:
                line = process.stdout.readline(FRAME_BYTES + 1)
                if not line:
                    raise CoreProtocolError(ended_message(process, self._stderr_tail))
                if not line.endswith(b"\n") or len(line) > FRAME_BYTES:
                    raise CoreProtocolError("Core returned an oversized or incomplete frame")
                try:
                    response = json.loads(line.decode("utf-8"))
                except ValueError as error:
                    raise CoreProtocolError("Core returned invalid JSON") from error
                if not isinstance(response, dict) or response.get("id") != request_id:
                    raise CoreProtocolError("Core returned an unexpected response id")
                if response.get("event") == "progress":
                    message = response.get("message")
                    if not isinstance(message, str) or len(message) > PROGRESS_CHARS:
                        raise CoreProtocolError("Core returned invalid progress")
                    if progress is not None:
                        progress(message)
                    continue
                if "error" in response:
                    error = decode_error(response["error"])
                    if error.code == "OCR_PROCESS_UNUSABLE":
                        self._discard(process)
                    raise error
                if "result" not in response:
                    raise CoreProtocolError("Core response has no result")
                return response["result"]
        except (OSError, ValueError, CoreProtocolError, CoreTimeoutError):
            self._discard(process)
            raise

    def _discard(self, process: subprocess.Popen[bytes], *, terminate: bool = True) -> None:
        with self._state_lock:
            if self._process is process:
                self._process = None
                self._hello = None
        if terminate:
            terminate_process(process)
        else:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                terminate_process(process)
                return
            close_process_job(process)
