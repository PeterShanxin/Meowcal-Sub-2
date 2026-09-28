"""Drive the built studio through the paths a viewer takes, with synthetic providers."""

import asyncio
import contextlib
import re
import socket
import threading
import time
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from meocosub2 import engine
from meocosub2.config import AppConfig
from meocosub2.overlay.server import OverlayServer
from meocosub2.subtitle_sources.subdl import SubdlProvider
from meocosub2.subtitle_sources.types import (
    AggregatedEpisode,
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


def test_episode_finds_more_files_when_title_search_has_both_languages(search_server, monkeypatch):
    search_server.controller._state.source_language = "zh"
    search_server.controller._state.target_language = "en"
    search_server.controller.config.source_language = "zh"
    search_server.controller.config.target_language = "en"
    exact_queries = []

    async def catalog(self, query, languages):
        episode = _match("ep-1", "Episode 1", "episode", season=1, episode=1, parent_title="Harbor")
        if query == "Harbor S01E01":
            exact_queries.append(query)
            return ProviderSearchCatalog(
                matches=[episode],
                results=[
                    replace(_result(episode, "Harbor.S01E01.other-release.en.srt"), id="en-other")
                ],
            )
        return ProviderSearchCatalog(
            matches=[episode],
            results=[
                _result(episode, "Harbor.S01E01.en.srt"),
                _result(episode, "Harbor.S01E01.zh.srt", "zh"),
            ],
        )

    monkeypatch.setattr(SubdlProvider, "search_catalog", catalog)
    with _studio(search_server, 1280, 900) as page:
        _search(page, "Harbor")
        page.get_by_text("Harbor", exact=True).click()
        card = page.locator(".work-card").filter(has_text="Harbor")
        card.locator(".work-nested").get_by_text("Season 1", exact=True).click()
        card.locator(".work-nested").get_by_text("S01E01", exact=False).click()
        expect(page.get_by_text("Harbor.S01E01.zh.srt")).to_be_visible()
        page.get_by_role("button", name=re.compile(r"^Target \d+$")).click()
        expect(page.get_by_text("Harbor.S01E01.en.srt")).to_be_visible()
        expect(page.get_by_text("Harbor.S01E01.other-release.en.srt")).to_be_visible()
        page.get_by_role("button", name=re.compile(r"^Titles \d+$")).click()
        card.locator(".work-nested").get_by_text("S01E01", exact=False).click()
        assert exact_queries == ["Harbor S01E01"]


def test_populated_episode_waits_for_season_sweep_before_exact_language_lookup(
    search_server, monkeypatch
):
    search_server.controller._state.source_language = "zh"
    search_server.controller._state.target_language = "en"
    search_server.controller.config.source_language = "zh"
    search_server.controller.config.target_language = "en"
    season_started = threading.Event()
    release_season = threading.Event()
    exact_queries = []
    queries = []

    async def catalog(self, query, languages):
        queries.append(query)
        if query == "Harbor S01":
            season_started.set()
            assert await asyncio.to_thread(release_season.wait, 10)
            return await _catalog(self, query, languages)
        if query == "Harbor S01E01":
            exact_queries.append(query)
            episode = _match(
                "ep-1", "Episode 1", "episode", season=1, episode=1, parent_title="Harbor"
            )
            return ProviderSearchCatalog(
                matches=[episode], results=[_result(episode, "Harbor.S01E01.zh.srt", "zh")]
            )
        return await _catalog(self, query, languages)

    aggregate = search_server.controller._aggregator.search_catalog

    async def add_skeleton(query, languages, **kwargs):
        result = await aggregate(query, languages, **kwargs)
        if query == "Harbor":
            for work in result.works:
                if work.title == "Harbor":
                    work.seasons[0].episodes.append(
                        AggregatedEpisode(1, 3, "Episode 3", "skeleton:1:3")
                    )
        return result

    monkeypatch.setattr(SubdlProvider, "search_catalog", catalog)
    monkeypatch.setattr(search_server.controller._aggregator, "search_catalog", add_skeleton)
    try:
        with _studio(search_server, 1280, 900) as page:
            _search(page, "Harbor")
            page.get_by_text("Harbor", exact=True).click()
            card = page.locator(".work-card").filter(has_text="Harbor")
            card.locator(".work-nested").get_by_text("Season 1", exact=True).click()
            assert season_started.wait(5), queries
            card.locator(".work-nested").get_by_text("Season 1", exact=True).click()
            card.locator(".work-nested").get_by_text("Season 1", exact=True).click()
            card.locator(".work-nested").get_by_text("S01E01", exact=False).click()
            assert exact_queries == []
            release_season.set()
            expect(page.get_by_text("Harbor.S01E01.zh.srt")).to_be_visible()
            assert exact_queries == ["Harbor S01E01"]
    finally:
        release_season.set()


def test_older_episode_lookup_does_not_replace_newer_selection(search_server, monkeypatch):
    search_server.controller._state.source_language = "zh"
    search_server.controller._state.target_language = "en"
    search_server.controller.config.source_language = "zh"
    search_server.controller.config.target_language = "en"
    first_started = threading.Event()
    release_first = threading.Event()
    queries = []

    async def catalog(self, query, languages):
        queries.append(query)
        if query == "Harbor S01E01":
            first_started.set()
            assert await asyncio.to_thread(release_first.wait, 10)
        if query in {"Harbor S01E01", "Harbor S01E02"}:
            episode_no = int(query[-2:])
            episode = _match(
                f"ep-{episode_no}",
                f"Episode {episode_no}",
                "episode",
                season=1,
                episode=episode_no,
                parent_title="Harbor",
            )
            return ProviderSearchCatalog(
                matches=[episode],
                results=[_result(episode, f"Harbor.S01E{episode_no:02d}.zh.srt", "zh")],
            )
        return await _catalog(self, query, languages)

    monkeypatch.setattr(SubdlProvider, "search_catalog", catalog)
    try:
        with _studio(search_server, 1280, 900) as page:
            _search(page, "Harbor")
            page.get_by_text("Harbor", exact=True).click()
            card = page.locator(".work-card").filter(has_text="Harbor")
            card.locator(".work-nested").get_by_text("Season 1", exact=True).click()
            card.locator(".work-nested").get_by_text("S01E01", exact=False).click()
            assert first_started.wait(5), queries
            card.locator(".work-nested").get_by_text("S01E02", exact=False).click()
            expect(page.get_by_text("Harbor.S01E02.zh.srt")).to_be_visible()
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/search/episode")
                    and response.request.post_data_json["episode"] == 1
                )
            ):
                release_first.set()
            page.wait_for_timeout(200)
            expect(page.get_by_text("Harbor.S01E02.zh.srt")).to_be_visible()
            expect(page.get_by_text("Harbor.S01E01.zh.srt")).to_have_count(0)
    finally:
        release_first.set()


def test_reselecting_busy_episode_uses_its_pending_lookup(search_server, monkeypatch):
    search_server.controller._state.source_language = "zh"
    search_server.controller._state.target_language = "en"
    search_server.controller.config.source_language = "zh"
    search_server.controller.config.target_language = "en"
    started = threading.Event()
    release = threading.Event()
    exact_queries = []

    async def catalog(self, query, languages):
        if query == "Harbor S01E01":
            exact_queries.append(query)
            started.set()
            assert await asyncio.to_thread(release.wait, 10)
            episode = _match(
                "ep-1", "Episode 1", "episode", season=1, episode=1, parent_title="Harbor"
            )
            return ProviderSearchCatalog(
                matches=[episode], results=[_result(episode, "Harbor.S01E01.zh.srt", "zh")]
            )
        return await _catalog(self, query, languages)

    monkeypatch.setattr(SubdlProvider, "search_catalog", catalog)
    try:
        with _studio(search_server, 1280, 900) as page:
            search = _search(page, "Harbor")
            page.get_by_text("Harbor", exact=True).click()
            card = page.locator(".work-card").filter(has_text="Harbor")
            card.locator(".work-nested").get_by_text("Season 1", exact=True).click()
            card.locator(".work-nested").get_by_text("S01E01", exact=False).click()
            assert started.wait(5)
            search.focus()
            for _ in range(3):
                search.press("ArrowDown")
            search.press("Enter")
            release.set()
            expect(page.get_by_text("Harbor.S01E01.zh.srt")).to_be_visible()
            assert exact_queries == ["Harbor S01E01"]
    finally:
        release.set()


@pytest.mark.parametrize("lookup", ["episode", "season"])
def test_old_lookup_does_not_keep_new_search_shimmering(search_server, monkeypatch, lookup):
    started = threading.Event()
    release = threading.Event()
    held_query = "Harbor S01" if lookup == "season" else "Harbor S01E01"

    async def catalog(self, query, languages):
        if query == held_query:
            started.set()
            assert await asyncio.to_thread(release.wait, 10)
        return await _catalog(self, query, languages)

    monkeypatch.setattr(SubdlProvider, "search_catalog", catalog)
    if lookup == "season":
        aggregate = search_server.controller._aggregator.search_catalog

        async def add_skeleton(query, languages, **kwargs):
            result = await aggregate(query, languages, **kwargs)
            if query == "Harbor":
                for work in result.works:
                    if work.title == "Harbor":
                        work.seasons[0].episodes.append(
                            AggregatedEpisode(1, 3, "Episode 3", "skeleton:1:3")
                        )
            return result

        monkeypatch.setattr(search_server.controller._aggregator, "search_catalog", add_skeleton)
    try:
        with _studio(search_server, 1280, 900) as page:
            _search(page, "Harbor")
            page.get_by_text("Harbor", exact=True).click()
            card = page.locator(".work-card").filter(has_text="Harbor")
            card.locator(".work-nested").get_by_text("Season 1", exact=True).click()
            if lookup == "episode":
                card.locator(".work-nested").get_by_text("S01E01", exact=False).click()
            assert started.wait(5)
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/api/search")
                    and response.request.post_data_json["title"] == "nothing"
                )
            ):
                _search(page, "nothing")
            with page.expect_response(
                lambda response: (
                    response.url.endswith(f"/api/search/{lookup}")
                    and response.request.post_data_json["season"] == 1
                )
            ):
                release.set()
            expect(page.locator(".search-shimmer")).to_have_count(0)
            expect(page.get_by_text("No titles found for “nothing”")).to_be_visible()
            assert search_server.controller._state.search_results == []
    finally:
        release.set()


def test_episode_lookup_waits_for_progressive_title_search(search_server, monkeypatch):
    search_server.controller._state.source_language = "zh"
    search_server.controller._state.target_language = "en"
    search_server.controller.config.source_language = "zh"
    search_server.controller.config.target_language = "en"
    slow_started = threading.Event()
    release_slow = threading.Event()
    exact_queries = []

    class SlowProvider:
        provider_code = "slow"
        provider_label = "Slow"

        async def search_catalog(self, query, languages):
            if query == "Harbor":
                slow_started.set()
                assert await asyncio.to_thread(release_slow.wait, 10)
            return ProviderSearchCatalog(matches=[], results=[])

    async def catalog(self, query, languages):
        if query == "Harbor S01E01":
            exact_queries.append(query)
            episode = _match(
                "ep-1", "Episode 1", "episode", season=1, episode=1, parent_title="Harbor"
            )
            return ProviderSearchCatalog(
                matches=[episode], results=[_result(episode, "Harbor.S01E01.zh.srt", "zh")]
            )
        return await _catalog(self, query, languages)

    search_server.controller._aggregator.providers = (
        *search_server.controller._aggregator.providers,
        SlowProvider(),
    )
    monkeypatch.setattr(SubdlProvider, "search_catalog", catalog)
    try:
        with _studio(search_server, 1280, 900) as page:
            _search(page, "Harbor")
            assert slow_started.wait(5)
            page.get_by_text("Harbor", exact=True).click()
            card = page.locator(".work-card").filter(has_text="Harbor")
            card.locator(".work-nested").get_by_text("Season 1", exact=True).click()
            card.locator(".work-nested").get_by_text("S01E01", exact=False).click()
            assert exact_queries == []
            release_slow.set()
            expect(page.get_by_text("Harbor.S01E01.zh.srt")).to_be_visible()
            assert exact_queries == ["Harbor S01E01"]
    finally:
        release_slow.set()


def test_a_search_that_finds_nothing_says_so(search_server):
    with _studio(search_server, 1280, 900) as page:
        _search(page, "nothing")
        expect(page.get_by_text("No titles found for “nothing”")).to_be_visible()


@pytest.mark.parametrize("tab", ["source", "target"])
def test_up_arrow_with_more_subtitles_than_titles(search_server, monkeypatch, tab):
    async def catalog(self, query, languages):
        movie = _match("movie", "Paper Lanterns", "movie")
        return ProviderSearchCatalog(
            matches=[movie],
            results=[
                replace(
                    _result(movie, f"Paper.{n}.{language}.srt", language),
                    id=f"movie-{language}-{n}",
                )
                for language in ("en", "zh")
                for n in range(5)
            ],
        )

    monkeypatch.setattr(SubdlProvider, "search_catalog", catalog)
    with _studio(search_server, 1280, 900) as page:
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        search = _search(page, "Paper")
        page.get_by_text("Paper Lanterns", exact=True).click()
        language = "en"
        if tab == "target":
            page.get_by_text("Paper.0.en.srt", exact=True).click()
            language = "zh"
        page.get_by_text(f"Paper.4.{language}.srt", exact=True).wait_for()
        search.focus()
        for _ in range(4):
            search.press("ArrowDown")
        search.press("ArrowUp")
        focused = page.locator('[data-cursor-row="2"]')
        expect(focused).to_have_css("background-color", "rgba(242, 199, 143, 0.12)")
        assert errors == []


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
        expect(page.get_by_role("dialog", name="Edit subtitles · Optional")).to_be_visible()


def test_tab_moves_on_from_the_palette_after_its_last_tab(tmp_path):
    with _studio(_prepared_server(tmp_path), 1280, 900) as page:
        search = page.locator('input[data-palette="true"]')
        search.focus()
        search.press("Tab")
        search.press("Tab")
        assert page.evaluate("document.activeElement.dataset.palette") == "true"
        search.press("Tab")
        # The palette retries its own focus for a moment after it appears; none
        # of those retries may take focus back from where Tab moved it.
        page.wait_for_timeout(1200)
        assert page.evaluate("document.activeElement.dataset.palette") is None
