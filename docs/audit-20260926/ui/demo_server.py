"""Serve the real studio against synthetic subtitle providers.

The audit drives the studio end to end without provider credentials or network
access: SubDL's search and download are replaced with a fixed catalog of
invented titles and generated SRT files, and the translation engine reports
that it still needs its one-time setup, which is what a fresh install shows.
Everything else - the FastAPI server, controller, aggregator and React bundle -
is the code under test.

    python docs/audit-20260926/ui/demo_server.py [--port 8765]
        [--scenario normal|setup|first-launch]

Prints its temporary APPDATA and token URL. Normal and first-launch use a
synthetic SubDL key; setup has no source credentials. No installed config or
provider credentials are read. Stop it with Ctrl+C to remove its files.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from meocosub2 import cli, config, engine  # noqa: E402
from meocosub2.subtitle_sources import subdl  # noqa: E402
from meocosub2.subtitle_sources.types import (  # noqa: E402
    ProviderSearchCatalog,
    ProviderSubtitleMatch,
    ProviderSubtitleResult,
)

SEARCH_DELAY_S = float(os.environ.get("DEMO_SEARCH_DELAY_S", "0.8"))
EN_LINES = [
    "Where did you put the lantern?",
    "It was on the table a minute ago.",
    "Then someone moved it.",
    "Nobody else has been in here.",
    "Look again. By the window.",
    "Found it. It's still warm.",
]
ZH_LINES = [
    "你把灯笼放哪儿了？",
    "刚才还在桌上。",
    "那就是有人动过了。",
    "没有别人进来过。",
    "再找找，窗边。",
    "找到了，还是热的。",
]


def _srt(lines: list[str]) -> str:
    blocks = []
    for index, text in enumerate(lines):
        start, end = 2 + index * 3, 4 + index * 3
        blocks.append(f"{index + 1}\n00:00:{start:02d},000 --> 00:00:{end:02d},500\n{text}\n")
    return "\n".join(blocks)


def _match(match_id: str, title: str, media_type: str, **extra: object) -> ProviderSubtitleMatch:
    return ProviderSubtitleMatch(
        id=match_id,
        provider="subdl",
        provider_label="SubDL",
        title=title,
        year=extra.pop("year", 2021),  # type: ignore[arg-type]
        imdb_id=None,
        tmdb_id=None,
        media_type=media_type,
        subtitles_count=6,
        match_score=0.9,
        **extra,  # type: ignore[arg-type]
    )


def _results(match: ProviderSubtitleMatch, stem: str) -> list[ProviderSubtitleResult]:
    out = []
    for language, releases in (
        ("en", ("WEB-DL.1080p", "BluRay.720p", "HDTV.x264")),
        ("zh", ("WEB-DL.1080p.chs", "BluRay.chs&eng")),
    ):
        for rank, release in enumerate(releases):
            out.append(
                ProviderSubtitleResult(
                    id=f"{match.id}-{language}-{rank}",
                    match_id=match.id,
                    provider="subdl",
                    provider_label="SubDL",
                    title=match.title,
                    year=match.year,
                    imdb_id=None,
                    media_type=match.media_type,
                    language=language,
                    download_count=4200 - rank * 900,
                    file_name=f"{stem}.{release}.{language}.srt",
                    season=match.season,
                    episode=match.episode,
                    parent_title=match.parent_title,
                    match_score=0.9,
                )
            )
    return out


def _catalog(query: str) -> ProviderSearchCatalog:
    if "nothing" in query.lower():
        return ProviderSearchCatalog(matches=[], results=[])
    movie = _match("m-lanterns", "Paper Lanterns", "movie")
    matches = [movie]
    results = _results(movie, "Paper.Lanterns.2021")
    for episode in (1, 2, 3):
        ep = _match(
            f"e-harbor-1-{episode}",
            f"Episode {episode}",
            "episode",
            season=1,
            episode=episode,
            parent_title="Harbor Lights",
            year=2023,
        )
        matches.append(ep)
        results += _results(ep, f"Harbor.Lights.S01E0{episode}")
    return ProviderSearchCatalog(matches=matches, results=results)


async def _search_catalog(self, query: str, languages: str) -> ProviderSearchCatalog:
    await asyncio.sleep(SEARCH_DELAY_S)
    if "offline" in query.lower():
        raise RuntimeError("SubDL did not answer (synthetic outage).")
    return _catalog(query)


async def _download(self, result: ProviderSubtitleResult) -> Path:
    await asyncio.sleep(0.3)
    files = config.default_config_path().parent / "demo-subs"
    files.mkdir(parents=True, exist_ok=True)
    path = files / result.file_name
    path.write_text(_srt(ZH_LINES if result.language == "zh" else EN_LINES), encoding="utf-8")
    return path


def _needs_setup() -> engine.EngineStatus:
    return engine.EngineStatus(
        "needsSetup", "Local translation needs a one-time 1.1 GB download before it can run."
    )


async def _not_installed(*_args: object, **_kwargs: object) -> str:
    raise engine.EngineInstallError("Local translation is not installed.")


subdl.SubdlProvider.search_catalog = _search_catalog  # type: ignore[method-assign]
subdl.SubdlProvider.download = _download  # type: ignore[method-assign]
engine.status = _needs_setup
engine.ensure_ready = _not_installed
engine.ensure_embedding_ready = _not_installed

if __name__ == "__main__":
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
    parser = argparse.ArgumentParser(description="Serve the Studio with synthetic subtitle data.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--scenario", choices=("normal", "setup", "first-launch"), default="normal")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    with tempfile.TemporaryDirectory(prefix="meowcal-studio-demo-") as appdata:
        previous_appdata = os.environ.get("APPDATA")
        previous_event_log = os.environ.get("MEOCOSUB2_EVENT_LOG_PATH")
        os.environ["APPDATA"] = appdata
        os.environ.pop("MEOCOSUB2_EVENT_LOG_PATH", None)
        try:
            print(f"Demo APPDATA: {appdata}", flush=True)
            config.save_config(
                config.AppConfig(
                    opensubtitles_enabled=False,
                    subdl_enabled=args.scenario != "setup",
                    subdl_api_key="synthetic-demo-key" if args.scenario != "setup" else "",
                    assrt_enabled=False,
                    tmdb_merge_enabled=False,
                    capture_region=[0, 0, 0, 0]
                    if args.scenario == "first-launch"
                    else [0, 0, 100, 100],
                    overlay_port=args.port,
                )
            )
            with suppress(KeyboardInterrupt):
                cli.serve()
        finally:
            if previous_appdata is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = previous_appdata
            if previous_event_log is not None:
                os.environ["MEOCOSUB2_EVENT_LOG_PATH"] = previous_event_log
