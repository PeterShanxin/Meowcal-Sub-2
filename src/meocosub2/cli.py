"""CLI entry point for Meowcal-Sub-2."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

import typer
import uvicorn
from rich.console import Console

from meocosub2 import __version__, auth, engine
from meocosub2.config import AppConfig, load_config
from meocosub2.event_log import log_event
from meocosub2.overlay.server import OverlayServer

app = typer.Typer(help="Meowcal-Sub-2 - the Meowcal Studio backend.")
console = Console()
logger = logging.getLogger(__name__)


def _log_dir() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home()))
    return Path(appdata) / "meowcal-sub-2" / "logs"


def _setup_logging(verbose: bool = True) -> None:
    root = logging.getLogger()
    if any(isinstance(handler, TimedRotatingFileHandler) for handler in root.handlers):
        return

    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_format = "%(asctime)s %(levelname)s %(name)s: %(message)s"

    file_handler = TimedRotatingFileHandler(
        log_dir / "meowcal-sub-2.log",
        when="D",
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(log_format))
    file_handler.setLevel(logging.DEBUG)
    root.addHandler(file_handler)

    if _has_console():
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(log_format))
        console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
        root.addHandler(console_handler)

    root.setLevel(logging.DEBUG)

    # Keep noisy third-party loggers quiet even in verbose mode
    for noisy in ("httpx", "httpcore", "asyncio", "watchfiles"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _has_console() -> bool:
    """Return True when stderr is attached to a real console or pipe."""
    import sys
    try:
        return sys.stderr is not None and sys.stderr.fileno() >= 0
    except Exception:
        return False


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"meowcal-sub-2 {__version__}")
        raise typer.Exit()


def _get_config() -> AppConfig:
    return load_config()


def _ensure_websocket_runtime() -> None:
    if importlib.util.find_spec("websockets") or importlib.util.find_spec("wsproto"):
        return
    console.print("[red]A websocket runtime dependency is missing. Install the project dependencies again.[/red]")
    raise typer.Exit(1)


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
    ),
    verbose: bool = typer.Option(
        True,
        "--verbose/--quiet",
        "-v/-q",
        help="Enable verbose console logging (on by default).",
    ),
) -> None:
    _setup_logging(verbose=verbose)


async def _serve_studio(config: AppConfig) -> None:
    _ensure_websocket_runtime()
    token = auth.generate_token()
    overlay = OverlayServer(config, access_token=token)
    auth.publish_runtime(token, config.overlay_port)
    console.print(f"Meowcal Studio: http://127.0.0.1:{config.overlay_port}/?token={token}")
    server = uvicorn.Server(
        uvicorn.Config(overlay.app, host="127.0.0.1", port=config.overlay_port, log_level="error")
    )
    try:
        await server.serve()
    finally:
        engine.shutdown()
        auth.clear_runtime()


@app.command()
def serve() -> None:
    """Run the Studio backend that the desktop shell talks to."""
    config = _get_config()
    log_event("backend.serve.start", layer="backend", port=config.overlay_port)
    asyncio.run(_serve_studio(config))


if __name__ == "__main__":
    app()
