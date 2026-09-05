"""Per-run authentication for the local Studio HTTP and WebSocket surface.

Loopback is not a trust boundary: any process on the machine, and any web page the
user opens, can reach 127.0.0.1. Every privileged route therefore requires a
high-entropy token that is generated per run and written to a file in the user's
profile, so a remote page cannot read it and an unauthenticated caller gets
nothing back.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path

TOKEN_HEADER = "x-meowcal-token"
TOKEN_QUERY = "token"
_TOKEN_BYTES = 32


def runtime_file_path() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home()))
    return Path(appdata) / "meowcal-sub-2" / "runtime.json"


def generate_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def publish_runtime(token: str, port: int, path: Path | None = None) -> Path:
    """Write the token and port where this app's own shell can find them."""
    target = path or runtime_file_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"token": token, "port": port}, indent=2), encoding="utf-8"
    )
    # Windows profile directories are already per-user; a failed chmod there
    # must not stop the app from starting.
    with suppress(OSError):
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return target


def clear_runtime(path: Path | None = None) -> None:
    (path or runtime_file_path()).unlink(missing_ok=True)


def read_runtime(path: Path | None = None) -> dict[str, object]:
    target = path or runtime_file_path()
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def token_matches(expected: str, presented: str | None) -> bool:
    return bool(presented) and secrets.compare_digest(expected, presented or "")
