import asyncio
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from meocosub2.config import AppConfig
from meocosub2.overlay.server import OverlayServer


def make_server() -> OverlayServer:
    return OverlayServer(
        AppConfig(
            overlay_font_size=32,
            overlay_font_family="Test Font",
            overlay_text_color="#123456",
            overlay_bg_color="rgba(1,2,3,0.5)",
            overlay_position="top",
        )
    )


def test_index_served() -> None:
    server = make_server()
    with TestClient(server.app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "subtitle-text" in response.text


def test_config_returns_style_fields() -> None:
    server = make_server()
    with TestClient(server.app) as client:
        response = client.get("/config")
    assert response.json() == {
        "fontSize": 32,
        "fontFamily": "Test Font",
        "textColor": "#123456",
        "bgColor": "rgba(1,2,3,0.5)",
        "position": "top",
    }


def test_websocket_receives_broadcast() -> None:
    server = make_server()
    with TestClient(server.app) as client:
        with client.websocket_connect("/ws") as websocket:
            asyncio.run(server.broadcast("hello"))
            message = json.loads(websocket.receive_text())
    assert message == {"type": "subtitle", "text": "hello"}


def test_broadcast_prunes_dead_connections() -> None:
    server = make_server()
    good = SimpleNamespace(send_text=lambda text: None)

    class DeadSocket:
        async def send_text(self, text: str) -> None:
            raise RuntimeError("gone")

    async def good_send(text: str) -> None:
        return None

    good.send_text = good_send
    dead = DeadSocket()
    server.connections = [good, dead]
    asyncio.run(server.broadcast("hi"))
    assert server.connections == [good]
