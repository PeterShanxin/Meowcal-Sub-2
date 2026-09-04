"""Playwright smoke check for the served dashboard path.

This verifies the local web UI that both the browser and Tauri shell consume.
It does not assert native WebView2 rendering behavior.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from meocosub2.auth import read_runtime  # noqa: E402

from playwright.sync_api import Error, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_ORIGIN = "http://127.0.0.1:8765"
# Served without the run token, so it answers before the studio page will.
READY_URL = f"{DASHBOARD_ORIGIN}/static/selector.js"
SERVER_TIMEOUT_S = 30
ALLOW_REUSE_ENV = "MEOWCAL_SMOKE_REUSE_EXISTING"
PLAYWRIGHT_INSTALL_HINT = "python -m playwright install chromium"
SMOKE_SUBDL_API_KEY = "dashboard-smoke-subdl-key"


def _python_command() -> list[str]:
    venv_python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return [str(venv_python)]
    return [sys.executable]


def _wait_for_server(url: str, timeout_s: int) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for dashboard at {url}")


def _server_is_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return False


def _allow_existing_server() -> bool:
    return os.environ.get(ALLOW_REUSE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _prepare_smoke_config(env: dict[str, str]) -> tempfile.TemporaryDirectory[str]:
    appdata_dir = tempfile.TemporaryDirectory(prefix="meowcal-dashboard-smoke-")
    config_dir = Path(appdata_dir.name) / "meowcal-sub-2"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(
        "\n".join(
            [
                "[subtitle_sources.subdl]",
                "enabled = true",
                f'api_key = "{SMOKE_SUBDL_API_KEY}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    env["APPDATA"] = appdata_dir.name
    return appdata_dir


def _studio_url(appdata: str) -> str:
    runtime = read_runtime(Path(appdata) / "meowcal-sub-2" / "runtime.json")
    token = str(runtime.get("token") or "")
    if not token:
        raise RuntimeError("The backend did not publish a Studio token to its runtime file.")
    return f"{DASHBOARD_ORIGIN}/?token={token}"


def main() -> int:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    smoke_appdata = _prepare_smoke_config(env)
    process: subprocess.Popen[str] | None = None
    try:
        # A reused server published its token under the real profile, not the
        # throwaway one prepared for a server this script starts itself.
        studio_appdata = env["APPDATA"]
        if _server_is_ready(READY_URL):
            studio_appdata = os.environ.get("APPDATA", "")
            if not _allow_existing_server():
                raise RuntimeError(
                    "Dashboard smoke refused to reuse an existing server on 127.0.0.1:8765 because "
                    "that can validate stale code. Stop the running dashboard first, or set "
                    f"{ALLOW_REUSE_ENV}=1 to opt into reusing it."
                )
        else:
            process = subprocess.Popen(
                [*_python_command(), "-m", "meocosub2.cli", "serve"],
                cwd=REPO_ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        _wait_for_server(READY_URL, SERVER_TIMEOUT_S)
        console_errors: list[str] = []
        page_errors: list[str] = []

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Error as exc:
                raise RuntimeError(
                    "Playwright Chromium is not installed. "
                    f"Run `{PLAYWRIGHT_INSTALL_HINT}` once before using the smoke script."
                ) from exc
            page = browser.new_page()
            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type == "error"
                else None,
            )
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.goto(_studio_url(studio_appdata), wait_until="domcontentloaded")
            # Command-palette redesign: wait for the React root, then for the
            # palette input to mount. Legacy DOM IDs (#app-shell, #hero-title-main,
            # #search-form, #results-flow, #session-view-title) are gone.
            page.wait_for_selector("#root")
            page.wait_for_selector("input[data-palette=\"true\"]", timeout=15000)

            browser.close()

        relevant_console_errors = [
            message for message in console_errors if "favicon" not in message.lower()
        ]
        if page_errors or relevant_console_errors:
            raise RuntimeError(
                "Dashboard smoke saw runtime errors.\n"
                f"Page errors: {page_errors}\n"
                f"Console errors: {relevant_console_errors}"
            )

        print("Dashboard smoke passed.")
        return 0
    finally:
        if process is not None:
            _terminate_process(process)
            with contextlib.suppress(Exception):
                stdout = process.stdout.read() if process.stdout else ""
                stderr = process.stderr.read() if process.stderr else ""
                if stdout.strip():
                    print(stdout)
                if stderr.strip():
                    print(stderr, file=sys.stderr)
        smoke_appdata.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
