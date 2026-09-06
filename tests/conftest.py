import pytest
from fastapi.testclient import TestClient

from meocosub2.auth import TOKEN_HEADER
from meocosub2.overlay.server import OverlayServer

TEST_TOKEN = "test-run-token"


@pytest.fixture(autouse=True)
def isolated_event_log(tmp_path, monkeypatch):
    """Keep test runs out of the installed app's diagnostics.

    Without this every run appends to the same file the desktop app writes, so a
    real failure is buried among events no user ever produced.
    """
    monkeypatch.setenv("MEOCOSUB2_EVENT_LOG_PATH", str(tmp_path / "meowcal-sub-2.events.jsonl"))


def studio_client(server: OverlayServer) -> TestClient:
    """A client that carries this run's token, like the studio page does."""
    return TestClient(server.app, headers={TOKEN_HEADER: TEST_TOKEN})
