"""CLI entry point for Meowcal-Sub-2."""

from __future__ import annotations

import asyncio
import logging
import os
import webbrowser
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

import pysubs2
import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from meocosub2 import __version__
from meocosub2.config import AppConfig, load_config
from meocosub2.opensubtitles.client import OpenSubtitlesClient
from meocosub2.overlay.server import OverlayServer
from meocosub2.subtitles import align_subtitles, load_subtitle_file
from meocosub2.sync import run_sync_loop
from meocosub2.translator import translate_lines

app = typer.Typer(help="Meowcal-Sub-2 - fetch, translate, and sync subtitles.")
console = Console()
logger = logging.getLogger(__name__)


def _log_dir() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home()))
    return Path(appdata) / "meowcal-sub-2" / "logs"


def _setup_logging() -> None:
    root = logging.getLogger()
    if any(isinstance(handler, TimedRotatingFileHandler) for handler in root.handlers):
        return

    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(
        log_dir / "meowcal-sub-2.log",
        when="D",
        backupCount=7,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"meowcal-sub-2 {__version__}")
        raise typer.Exit()


def _get_config() -> AppConfig:
    return load_config()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    _setup_logging()


def _require_api_key(config: AppConfig) -> None:
    if not config.opensubtitles_api_key:
        console.print("[red]OpenSubtitles API key is not configured.[/red]")
        raise typer.Exit(1)


def _best_result(results: list, language: str):
    matches = [result for result in results if result.language == language]
    if not matches:
        return None
    return max(matches, key=lambda result: (getattr(result, "match_score", 0.0), result.download_count))


def _write_translated_srt(lines: list, output_path: Path) -> None:
    subs = pysubs2.SSAFile()
    for line in lines:
        subs.events.append(
            pysubs2.SSAEvent(
                start=line.start_ms,
                end=line.end_ms,
                text=line.translated or line.text,
            )
        )
    subs.save(str(output_path))


@app.command()
def search(
    title: str = typer.Argument(..., help="Movie or show title"),
    source_lang: str = typer.Option("", "--source", "-s"),
    target_lang: str = typer.Option("", "--target", "-t"),
) -> None:
    config = _get_config()
    _require_api_key(config)
    source = source_lang or config.source_language
    target = target_lang or config.target_language

    async def _search() -> list:
        async with OpenSubtitlesClient(
            api_key=config.opensubtitles_api_key,
            enable_org_fallback=config.opensubtitles_enable_org_fallback,
        ) as client:
            return await client.search(title, languages=f"{source},{target}")

    results = asyncio.run(_search())
    if not results:
        console.print(f"[yellow]No subtitles found for {title}.[/yellow]")
        return

    table = Table(title=f"Results for '{title}'")
    table.add_column("Title")
    table.add_column("Lang")
    table.add_column("Downloads", justify="right")
    table.add_column("File ID", justify="right")
    for result in results[:20]:
        table.add_row(
            result.display_label(),
            result.language,
            str(result.download_count),
            str(result.file_id),
        )
    console.print(table)


@app.command()
def download(file_id: int = typer.Argument(..., help="OpenSubtitles file ID")) -> None:
    config = _get_config()
    _require_api_key(config)

    async def _download() -> Path:
        async with OpenSubtitlesClient(api_key=config.opensubtitles_api_key) as client:
            return await client.download(file_id)

    path = asyncio.run(_download())
    console.print(str(path))


@app.command()
def translate(
    srt_file: Path = typer.Argument(..., exists=True, readable=True, resolve_path=True),
    output_file: Optional[Path] = typer.Option(None, "--output", "-o", resolve_path=True),
) -> None:
    config = _get_config()
    lines = load_subtitle_file(srt_file)
    translated = asyncio.run(
        translate_lines(
            lines,
            config,
            progress_callback=lambda done, total: logger.info("Translated %s/%s lines", done, total),
        )
    )
    destination = output_file or srt_file.with_suffix(".translated.srt")
    _write_translated_srt(translated, destination)
    console.print(str(destination))


async def _start_overlay(pair, config: AppConfig) -> None:
    overlay = OverlayServer(config)
    server_config = uvicorn.Config(overlay.app, host="127.0.0.1", port=config.overlay_port, log_level="error")
    server = uvicorn.Server(server_config)
    overlay_url = f"http://127.0.0.1:{config.overlay_port}/overlay"
    webbrowser.open(overlay_url)
    await asyncio.gather(server.serve(), run_sync_loop(pair, config, overlay.broadcast))


async def _start_gui(config: AppConfig) -> None:
    overlay = OverlayServer(config)
    server_config = uvicorn.Config(overlay.app, host="127.0.0.1", port=config.overlay_port, log_level="error")
    server = uvicorn.Server(server_config)
    studio_url = f"http://127.0.0.1:{config.overlay_port}/"
    webbrowser.open(studio_url)
    await server.serve()


@app.command()
def start(
    source_subtitle: Path = typer.Argument(..., exists=True, readable=True, resolve_path=True),
    target_subtitle: Optional[Path] = typer.Option(None, "--target-file", resolve_path=True),
) -> None:
    config = _get_config()
    source_lines = load_subtitle_file(source_subtitle)
    target_lines = load_subtitle_file(target_subtitle) if target_subtitle else []
    for source_line, target_line in zip(source_lines, target_lines):
        source_line.translated = target_line.text
    pair = align_subtitles(source_lines, target_lines)
    asyncio.run(_start_overlay(pair, config))


@app.command()
def gui() -> None:
    config = _get_config()
    asyncio.run(_start_gui(config))


async def _run_flow(title: str, source_lang: str, target_lang: str, config: AppConfig) -> None:
    async with OpenSubtitlesClient(
        api_key=config.opensubtitles_api_key,
        enable_org_fallback=config.opensubtitles_enable_org_fallback,
    ) as client:
        results = await client.search(title, languages=f"{source_lang},{target_lang}")
        source_result = _best_result(results, source_lang)
        if source_result is None:
            raise typer.Exit(1)
        target_result = _best_result(results, target_lang)

        source_path = await client.download(source_result.file_id, source_result.file_name)
        target_path = None
        if target_result is not None:
            target_path = await client.download(target_result.file_id, target_result.file_name)

    source_lines = load_subtitle_file(source_path)
    target_lines = load_subtitle_file(target_path) if target_path else []

    if target_lines:
        for source_line, target_line in zip(source_lines, target_lines):
            source_line.translated = target_line.text
    else:
        await translate_lines(
            source_lines,
            config,
            progress_callback=lambda done, total: logger.info("Translated %s/%s lines", done, total),
        )

    pair = align_subtitles(source_lines, target_lines)
    await _start_overlay(pair, config)


@app.command()
def run(
    title: str = typer.Argument(..., help="Movie or show title"),
    source_lang: str = typer.Option("", "--source", "-s"),
    target_lang: str = typer.Option("", "--target", "-t"),
) -> None:
    config = _get_config()
    _require_api_key(config)
    asyncio.run(
        _run_flow(
            title,
            source_lang or config.source_language,
            target_lang or config.target_language,
            config,
        )
    )


if __name__ == "__main__":
    app()
