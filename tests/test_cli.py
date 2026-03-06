from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from meocosub2.cli import _best_result, _run_flow, _setup_logging, app
from meocosub2.config import AppConfig
from meocosub2.models import SubtitleLine
from meocosub2.opensubtitles.types import SearchResult

runner = CliRunner()


def test_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("search", "download", "translate", "start", "run", "gui"):
        assert command in result.output


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_search_requires_title() -> None:
    result = runner.invoke(app, ["search"])
    assert result.exit_code != 0


def test_search_command_shows_results(mocker) -> None:
    mocker.patch("meocosub2.cli._get_config", return_value=AppConfig(opensubtitles_api_key="key"))

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def search(self, title, languages):
            return [
                SearchResult(
                    id="1",
                    title="Inception",
                    year=2010,
                    imdb_id="tt1375666",
                    media_type="movie",
                    season=None,
                    episode=None,
                    language="en",
                    download_count=100,
                    file_id=42,
                    file_name="Inception.en.srt",
                )
            ]

    mocker.patch("meocosub2.cli.OpenSubtitlesClient", return_value=FakeClient())
    result = runner.invoke(app, ["search", "Inception"])
    assert result.exit_code == 0
    assert "Inception" in result.output


def test_best_result_prefers_match_score_over_download_count() -> None:
    low_rank = SearchResult(
        id="1",
        title="Fake Tattoos",
        year=2017,
        imdb_id="tt0000001",
        media_type="movie",
        season=None,
        episode=None,
        language="en",
        download_count=10000,
        file_id=1,
        file_name="fake.srt",
        match_score=20,
    )
    exact_match = SearchResult(
        id="2",
        title="The Heroic Spirit Incident",
        year=2024,
        imdb_id="tt34742962",
        media_type="episode",
        season=1,
        episode=1,
        language="en",
        download_count=500,
        file_id=2,
        file_name="fate.srt",
        parent_title="Fate/strange Fake",
        match_score=260,
    )

    selected = _best_result([low_rank, exact_match], "en")

    assert selected == exact_match


def test_download_command_prints_downloaded_path(mocker, tmp_path: Path) -> None:
    mocker.patch("meocosub2.cli._get_config", return_value=AppConfig(opensubtitles_api_key="key"))

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def download(self, file_id):
            return tmp_path / f"{file_id}.srt"

    mocker.patch("meocosub2.cli.OpenSubtitlesClient", return_value=FakeClient())
    result = runner.invoke(app, ["download", "42"])
    assert result.exit_code == 0
    assert "42.srt" in result.output


def test_translate_command_writes_output(mocker, tmp_path: Path) -> None:
    input_file = tmp_path / "sample.srt"
    input_file.write_text("stub", encoding="utf-8")
    lines = [SubtitleLine(index=0, start_ms=0, end_ms=1000, text="Hello", translated="你好")]
    mocker.patch("meocosub2.cli._get_config", return_value=AppConfig(foundry_model="model"))
    mocker.patch("meocosub2.cli.load_subtitle_file", return_value=lines)
    mocker.patch("meocosub2.cli.translate_lines", new=mocker.AsyncMock(return_value=lines))
    write_translated = mocker.patch("meocosub2.cli._write_translated_srt")
    result = runner.invoke(app, ["translate", str(input_file)])
    assert result.exit_code == 0
    write_translated.assert_called_once()


@pytest.mark.asyncio
async def test_run_flow_picks_best_by_download_count_and_translates_when_target_missing(mocker, tmp_path: Path) -> None:
    config = AppConfig(opensubtitles_api_key="key", foundry_model="model")
    source_file = tmp_path / "source.srt"
    source_file.write_text("source", encoding="utf-8")
    results = [
        SearchResult("1", "Movie", 2024, None, "movie", None, None, "en", 10, 1, "low.srt"),
        SearchResult("2", "Movie", 2024, None, "movie", None, None, "en", 100, 2, "best.srt"),
    ]

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def search(self, title, languages):
            return results

        async def download(self, file_id, file_name=None):
            assert file_id == 2
            return source_file

    translated_lines = [SubtitleLine(index=0, start_ms=0, end_ms=1000, text="Hello", translated="你好")]
    mocker.patch("meocosub2.cli.OpenSubtitlesClient", return_value=FakeClient())
    mocker.patch("meocosub2.cli.load_subtitle_file", return_value=[SubtitleLine(index=0, start_ms=0, end_ms=1000, text="Hello")])
    translate = mocker.patch("meocosub2.cli.translate_lines", new=mocker.AsyncMock(return_value=translated_lines))
    start_overlay = mocker.patch("meocosub2.cli._start_overlay", new=mocker.AsyncMock())
    await _run_flow("Movie", "en", "zht", config)
    translate.assert_awaited_once()
    start_overlay.assert_awaited_once()


def test_setup_logging_creates_rotating_handler(tmp_path: Path, mocker) -> None:
    mocker.patch("meocosub2.cli._log_dir", return_value=tmp_path)
    root = __import__("logging").getLogger()
    old_handlers = list(root.handlers)
    for handler in old_handlers:
        root.removeHandler(handler)
    try:
        _setup_logging()
        assert any(getattr(handler, "backupCount", None) == 7 for handler in root.handlers)
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in old_handlers:
            root.addHandler(handler)


def test_gui_command_starts_dashboard_server(mocker) -> None:
    start_gui = mocker.patch("meocosub2.cli._start_gui", new=mocker.AsyncMock())
    mocker.patch("meocosub2.cli._get_config", return_value=AppConfig())
    result = runner.invoke(app, ["gui"])
    assert result.exit_code == 0
    start_gui.assert_awaited_once()
