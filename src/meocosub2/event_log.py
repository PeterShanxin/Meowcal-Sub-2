"""Structured cross-layer event logging for app diagnostics."""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

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
    record: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "ts_ms": round(time.time() * 1000),
        "layer": layer,
        "level": level,
        "event": event,
    }
    if correlation_id:
        record["correlation_id"] = correlation_id
    record.update({key: _sanitize(value, key) for key, value in fields.items()})

    try:
        path = event_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
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
        return value if len(value) <= MAX_STRING_LENGTH else value[:MAX_STRING_LENGTH] + "..."
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.replace("-", "_").replace(" ", "_").casefold()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)
