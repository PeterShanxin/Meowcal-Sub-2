"""Drive the built studio through the paths a viewer takes, with synthetic providers."""

import contextlib
import socket
import threading
import time
from unittest.mock import AsyncMock

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from meocosub2 import engine
from meocosub2.config import AppConfig
from meocosub2.overlay.server import OverlayServer
from meocosub2.subtitle_sources.subdl import SubdlProvider
from meocosub2.subtitle_sources.types import (
    ProviderSearchCatalog,
    ProviderSubtitleMatch,
    ProviderSubtitleResult,
)
from tests.conftest import TEST_TOKEN
from tests.test_subtitle_editor import editor_server


def _match(match_id, title, media_type, **extra):
    return ProviderSubtitleMatch(
        match_id, "subdl", "SubDL", title, 2021, None, None, media_type, **extra
    )


def _result(match, file_name, language="en"):
    return ProviderSubtitleResult(
        f"{match.id}-{language}",
        match.id,
        "subdl",
        "SubDL",
        match.title,
        match.year,
        None,
        match.media_type,
        language,
        100,
        file_name,
        season=match.season,
        episode=match.episode,
        parent_title=match.parent_title,
    )


async def _catalog(self, query, languages):
    if query == "nothing":
        return ProviderSearchCatalog(matches=[], results=[])
    movie = _match("movie", "Paper Lanterns", "movie")
    episodes = [
        _match(f"ep-{n}", f"Episode {n}", "episode", season=1, episode=n, parent_title="Harbor")
        for n in (1, 2)
    ]
    return ProviderSearchCatalog(
        matches=[movie, *episodes],
        results=[
            _result(movie, "Paper.Lanterns.2021.WEB-DL.1080p.en.srt"),
            _result(movie, "Paper.Lanterns.2021.WEB-DL.1080p.zh.srt", "zh"),
            *(_result(ep, f"Harbor.S01E0{ep.episode}.en.srt") for ep in episodes),
        ],
    )


@contextlib.contextmanager
def _studio(app, width, height):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        app._allowed_origins = {f"http://127.0.0.1:{port}"}
        server = uvicorn.Server(uvicorn.Config(app.app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert server.started
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.set_default_timeout(7000)
                    page.route(
                        "https://fonts.googleapis.com/**",
                        lambda route: route.fulfill(status=200, content_type="text/css", body=""),
                    )
                    page.goto(f"http://127.0.0.1:{port}/?token={TEST_TOKEN}")
                    yield page
                finally:
                    browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)


@pytest.fixture(autouse=True)
def no_engine(monkeypatch):
    monkeypatch.setattr(
        "meocosub2.overlay.controller.engine.status",
        lambda: engine.EngineStatus("needsSetup", "Local translation needs setup."),
    )
    monkeypatch.setattr("meocosub2.overlay.controller.engine.ensure_ready", AsyncMock())


@pytest.fixture
def search_server(tmp_path, monkeypatch):
    async def download(self, result):
        path = tmp_path / result.file_name
        path.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
        return path

    monkeypatch.setattr(SubdlProvider, "search_catalog", _catalog)
    monkeypatch.setattr(SubdlProvider, "download", download)
    return OverlayServer(
        AppConfig(subdl_api_key="key", opensubtitles_enabled=False, capture_region=[0, 0, 9, 9]),
        tmp_path / "config.toml",
        access_token=TEST_TOKEN,
    )


def _prepared_server(tmp_path):
    server = editor_server(tmp_path)
    # Without a source credential the studio shows its setup card instead.
    server.controller.config.subdl_api_key = "key"
    return server


def _search(page, title):
    search = page.locator('input[data-palette="true"]')
    search.fill(title)
    search.press("Enter")
    return search


def test_keyboard_reaches_an_episode_in_the_wide_title_grid(search_server):
    with _studio(search_server, 1280, 900) as page:
        search = _search(page, "Harbor")
        expect(page.locator(".work-row")).to_have_count(2)
        for key in ("ArrowDown", "Enter", "ArrowDown", "Enter", "ArrowDown", "Enter"):
            search.press(key)
        expect(page.get_by_text("Harbor.S01E01.en.srt")).to_be_visible()


def test_a_search_that_finds_nothing_says_so(search_server):
    with _studio(search_server, 1280, 900) as page:
        _search(page, "nothing")
        expect(page.get_by_text("No titles found for “nothing”")).to_be_visible()


def test_a_narrow_window_keeps_the_prepared_session_usable(search_server):
    with _studio(search_server, 390, 844) as page:
        _search(page, "Paper")
        page.get_by_text("Paper Lanterns").click()
        page.get_by_text("Paper.Lanterns.2021.WEB-DL.1080p.en.srt").click()
        page.get_by_text("Paper.Lanterns.2021.WEB-DL.1080p.zh.srt").click()
        start = page.get_by_role("button", name="Start OCR and sync")
        expect(start).to_be_enabled()
        box = start.bounding_box()
        assert box is not None and box["x"] + box["width"] <= 390
        page.get_by_role("button", name="Edit subtitles", exact=True).click()
        expect(page.get_by_role("dialog", name="Review before sync")).to_be_visible()


def test_tab_moves_on_from_the_palette_after_its_last_tab(tmp_path):
    with _studio(_prepared_server(tmp_path), 1280, 900) as page:
        search = page.locator('input[data-palette="true"]')
        search.focus()
        search.press("Tab")
        search.press("Tab")
        assert page.evaluate("document.activeElement.dataset.palette") == "true"
        search.press("Tab")
        assert page.evaluate("document.activeElement.dataset.palette") is None
