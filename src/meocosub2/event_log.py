"""Structured cross-layer event logging for app diagnostics."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

MAX_EVENT_LOG_BYTES = 5 * 1024 * 1024
REDACTED = "[redacted]"
MAX_STRING_LENGTH = 500
SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "download_ref",
    "link",
    "password",
    "secret",
    "token",
)
RESERVED_KEYS = frozenset({"correlation_id", "event", "layer", "level", "ts", "ts_ms"})
URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")
CURRENT_CORRELATION_ID: ContextVar[str | None] = ContextVar(
    "meocosub2_correlation_id", default=None
)
# Two threads that both see a full log would otherwise both rename, and the
# second would replace the previous file with the first line of the new one.
_ROTATION_LOCK = threading.Lock()


def event_log_path() -> Path:
    override = os.environ.get("MEOCOSUB2_EVENT_LOG_PATH")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA", str(Path.home()))
    return Path(appdata) / "meowcal-sub-2" / "logs" / "meowcal-sub-2.events.jsonl"


def log_event(
    event: str,
    *,
    layer: str = "backend",
    level: str = "info",
    correlation_id: str | None = None,
    **fields: Any,
) -> None:
    correlation_id = correlation_id or CURRENT_CORRELATION_ID.get()
    record: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "ts_ms": round(time.time() * 1000),
        "layer": layer,
        "level": level,
        "event": event,
    }
    if correlation_id:
        record["correlation_id"] = correlation_id
    for key, value in fields.items():
        if key in RESERVED_KEYS:
            record.setdefault("data", {})[key] = _sanitize(value, key)
        else:
            record[key] = _sanitize(value, key)

    try:
        path = event_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_full(path)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:  # pragma: no cover - diagnostics must not break app flow
        logger.debug("Event log write failed: %s", exc)


@contextmanager
def event_span(
    event: str,
    *,
    layer: str = "backend",
    correlation_id: str | None = None,
    **fields: Any,
) -> Iterator[None]:
    start = time.perf_counter()
    log_event(f"{event}.start", layer=layer, correlation_id=correlation_id, **fields)
    try:
        yield
    except Exception as exc:
        log_event(
            f"{event}.error",
            layer=layer,
            level="error",
            correlation_id=correlation_id,
            duration_ms=_elapsed_ms(start),
            error_type=type(exc).__name__,
            error=str(exc),
            **fields,
        )
        raise
    else:
        log_event(
            f"{event}.done",
            layer=layer,
            correlation_id=correlation_id,
            duration_ms=_elapsed_ms(start),
            **fields,
        )


@contextmanager
def event_correlation(correlation_id: str | None) -> Iterator[None]:
    token: Token[str | None] | None = None
    if correlation_id:
        token = CURRENT_CORRELATION_ID.set(correlation_id)
    try:
        yield
    finally:
        if token is not None:
            CURRENT_CORRELATION_ID.reset(token)


def _rotate_if_full(path: Path) -> None:
    # The backend is the only writer that rotates; the shell and the launcher
    # append a few lifecycle events to whichever file is current. A rename that
    # meets another process's open handle fails, and the next event retries it.
    with _ROTATION_LOCK:
        try:
            if path.stat().st_size < MAX_EVENT_LOG_BYTES:
                return
            path.replace(path.with_name(path.name + ".1"))
        except FileNotFoundError:
            return
        except OSError as exc:
            logger.debug("Event log rotation deferred: %s", exc)


def _elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def _sanitize(value: Any, key: str = "") -> Any:
    if _is_sensitive_key(key):
        return REDACTED
    if isinstance(value, dict):
        return {str(k): _sanitize(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(item, key) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item, key) for item in value]
    if isinstance(value, str):
        value = URL_PATTERN.sub(lambda match: _redact_url(match.group(0)), value)
        return value if len(value) <= MAX_STRING_LENGTH else value[:MAX_STRING_LENGTH] + "..."
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.replace("-", "_").replace(" ", "_").casefold()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    query = [
        (key, REDACTED if _is_sensitive_key(key) else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
