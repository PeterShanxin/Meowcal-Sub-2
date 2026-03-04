"""FastAPI overlay server and WebSocket broadcaster."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from meocosub2.config import AppConfig

STATIC_DIR = Path(__file__).parent / "static"


class OverlayServer:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.connections: list[WebSocket] = []
        self.app = FastAPI()
        self.app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @self.app.get("/")
        async def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

        @self.app.get("/config")
        async def config_route() -> dict[str, object]:
            return {
                "fontSize": self.config.overlay_font_size,
                "fontFamily": self.config.overlay_font_family,
                "textColor": self.config.overlay_text_color,
                "bgColor": self.config.overlay_bg_color,
                "position": self.config.overlay_position,
            }

        @self.app.websocket("/ws")
        async def websocket_route(websocket: WebSocket) -> None:
            await websocket.accept()
            self.connections.append(websocket)
            try:
                while True:
                    await websocket.receive_text()
            except Exception:
                if websocket in self.connections:
                    self.connections.remove(websocket)

    async def broadcast(self, subtitle_text: str) -> None:
        message = json.dumps({"type": "subtitle", "text": subtitle_text})
        dead: list[WebSocket] = []
        for websocket in tuple(self.connections):
            try:
                await websocket.send_text(message)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            if websocket in self.connections:
                self.connections.remove(websocket)
