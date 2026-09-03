import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from typer.testing import CliRunner

from meocosub2.cli import _setup_logging, app

runner = CliRunner()


def test_help_lists_the_serve_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.output


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_setup_logging_writes_to_the_app_log_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    root = logging.getLogger()
    existing = list(root.handlers)
    root.handlers = []
    try:
        _setup_logging(verbose=False)
        handlers = [h for h in root.handlers if isinstance(h, TimedRotatingFileHandler)]
        assert handlers
        assert Path(handlers[0].baseFilename).parent == tmp_path / "meowcal-sub-2" / "logs"
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers = existing
