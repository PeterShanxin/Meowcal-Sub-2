from fastapi.testclient import TestClient

from meocosub2.auth import TOKEN_HEADER
from meocosub2.overlay.server import OverlayServer

TEST_TOKEN = "test-run-token"


def studio_client(server: OverlayServer) -> TestClient:
    """A client that carries this run's token, like the studio page does."""
    return TestClient(server.app, headers={TOKEN_HEADER: TEST_TOKEN})
