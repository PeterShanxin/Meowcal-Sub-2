"""Return a failure before the development shell can attach to another listener."""

from __future__ import annotations

import socket
import sys

from meocosub2.config import load_config


def check_port(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            print(f"Studio port {port} is unavailable.", file=sys.stderr)
            return False
    return True


if __name__ == "__main__":
    raise SystemExit(0 if check_port(load_config().overlay_port) else 1)
