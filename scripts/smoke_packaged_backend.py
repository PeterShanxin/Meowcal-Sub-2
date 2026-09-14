"""Exercise an installed backend with an isolated profile and no developer Python paths."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def smoke(package: Path) -> None:
    python = package / "backend" / "python.exe"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="meowcal-package-smoke-") as temporary:
        profile = Path(temporary)
        config_dir = profile / "meowcal-sub-2"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text(f"[overlay]\nport = {port}\n", encoding="utf-8")
        environment = dict(os.environ)
        for key in ("PYTHONPATH", "PYTHONHOME", "MEOWCAL_PYTHON", "VIRTUAL_ENV"):
            environment.pop(key, None)
        environment.update(
            APPDATA=str(profile),
            LOCALAPPDATA=str(profile),
            MEOWCAL_CORE_EXE=str(package / "core" / "meowcal-core.exe"),
            PATH=os.environ.get("SYSTEMROOT", r"C:\Windows") + r"\System32",
        )
        with (profile / "backend.log").open("wb") as log:
            child = subprocess.Popen(
                [str(python), "-I", "-B", "-m", "meocosub2.cli", "serve"],
                cwd=profile,
                env=environment,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                deadline = time.monotonic() + 30
                runtime = config_dir / "runtime.json"
                while not runtime.is_file():
                    if child.poll() is not None or time.monotonic() > deadline:
                        log.flush()
                        raise RuntimeError((profile / "backend.log").read_text(errors="replace"))
                    time.sleep(0.1)
                token = json.loads(runtime.read_text(encoding="utf-8"))["token"]
                base = f"http://127.0.0.1:{port}"
                request = urllib.request.Request(base + "/", headers={"X-Meowcal-Token": token})
                with urllib.request.urlopen(request, timeout=10) as response:
                    html = response.read().decode()
                assets = re.findall(r'(?:src|href)="(/static/assets/[^"]+)"', html)
                if not assets:
                    raise RuntimeError("Packaged studio has no built assets.")
                for asset in assets:
                    request = urllib.request.Request(
                        base + asset, headers={"X-Meowcal-Token": token}
                    )
                    with urllib.request.urlopen(request, timeout=10) as response:
                        if response.status != 200 or not response.read():
                            raise RuntimeError(f"Missing studio asset: {asset}")
                try:
                    urllib.request.urlopen(base + "/api/config", timeout=10)
                except urllib.error.HTTPError as error:
                    if error.code != 401:
                        raise
                else:
                    raise RuntimeError("Packaged backend accepted an unauthenticated API request.")
                websocket_probe = (
                    "import json,sys; from websockets.sync.client import connect; "
                    "connection=connect(sys.argv[1], additional_headers="
                    "{'X-Meowcal-Token':sys.argv[2]}, open_timeout=5, close_timeout=5); "
                    "assert json.loads(connection.recv(timeout=5))['type']=='state'; "
                    "connection.close()"
                )
                subprocess.run(
                    [
                        str(python),
                        "-I",
                        "-B",
                        "-c",
                        websocket_probe,
                        f"ws://127.0.0.1:{port}/ws/app",
                        token,
                    ],
                    cwd=profile,
                    env=environment,
                    stdout=log,
                    stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=15,
                    check=True,
                )
                print(
                    "Packaged backend: isolated startup, studio assets, authentication and WebSocket passed."
                )
            finally:
                # No session or Core is started by this smoke; the backend is its only child.
                child.terminate()
                child.wait(timeout=10)


if __name__ == "__main__":
    smoke(Path(sys.argv[1]).resolve())
