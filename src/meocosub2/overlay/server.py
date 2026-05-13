"""FastAPI server for the dashboard and subtitle overlay."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from meocosub2.config import AppConfig, overlay_style_payload
from meocosub2.capture import available_ocr_languages
from meocosub2.errors import SubtitleSourceError, TranslationError
from meocosub2.event_log import log_event
from meocosub2.languages import languages_payload
from meocosub2.models import SearchRequest
from meocosub2.overlay.controller import GuiController

STATIC_DIR = Path(__file__).parent / "static"
logger = logging.getLogger(__name__)


class SearchBody(BaseModel):
    title: str
    sourceLanguage: str | None = None
    targetLanguage: str | None = None
    clientEventId: str | None = None
    correlationId: str | None = None


class ClientLogBody(BaseModel):
    event: str
    level: str = "info"
    correlationId: str | None = None
    data: dict[str, object] = Field(default_factory=dict)


class PrepareSessionBody(BaseModel):
    mode: str
    matchId: str | int | None = None
    featureId: str | int | None = None
    sourceResultId: str | int | None = None
    sourceFileId: str | int | None = None
    targetResultId: str | int | None = None
    targetFileId: str | int | None = None


class StartSessionBody(BaseModel):
    sessionId: str | None = None


class OcrInstallBody(BaseModel):
    languageTag: str


class OverlayServer:
    def __init__(self, config: AppConfig, config_path: Path | None = None) -> None:
        self.app_connections: list[WebSocket] = []
        self.overlay_connections: list[WebSocket] = []
        self.controller = GuiController(
            config=config,
            app_event_emitter=self.broadcast_app_event,
            overlay_event_emitter=self.broadcast_overlay_event,
            config_path=config_path,
        )

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            yield
            await self.controller.shutdown()

        self.app = FastAPI(lifespan=lifespan)
        self.app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @self.app.get("/")
        async def index() -> FileResponse:
            return FileResponse(
                STATIC_DIR / "index.html",
                headers={"Cache-Control": "no-store, max-age=0"},
            )

        @self.app.get("/config")
        async def config_route() -> dict[str, object]:
            return overlay_style_payload(self.config)

        @self.app.get("/api/config")
        async def api_get_config() -> dict[str, object]:
            return await self.controller.get_config_payload()

        @self.app.get("/api/languages")
        async def api_get_languages() -> dict[str, object]:
            return languages_payload(set(available_ocr_languages()))

        @self.app.get("/api/foundry/status")
        async def api_get_foundry_status(probe: bool = False, autoStart: bool = False) -> dict[str, object]:
            return await self.controller.get_foundry_status_payload(probe=probe, auto_start=autoStart)

        @self.app.post("/api/foundry/prepare")
        async def api_prepare_foundry() -> dict[str, object]:
            return await self.controller.prepare_foundry_payload()

        @self.app.post("/api/ocr/install")
        async def api_install_ocr_language(body: OcrInstallBody) -> dict[str, object]:
            try:
                return await self.controller.install_ocr_language(body.languageTag)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        @self.app.put("/api/config")
        async def api_put_config(payload: dict[str, object]) -> dict[str, object]:
            return await self.controller.save_config_payload(payload)

        @self.app.get("/api/state")
        async def api_get_state() -> dict[str, object]:
            return self.controller.state_snapshot()

        @self.app.post("/api/log/client")
        async def api_log_client(body: ClientLogBody) -> dict[str, str]:
            log_event(
                body.event,
                layer="frontend",
                level=body.level,
                correlation_id=body.correlationId,
                **body.data,
            )
            return {"status": "logged"}

        @self.app.post("/api/search")
        async def api_search(body: SearchBody) -> dict[str, object]:
            try:
                return await self.controller.search(
                    SearchRequest(
                        title=body.title,
                        source_language=body.sourceLanguage or self.config.source_language,
                        target_language=body.targetLanguage or self.config.target_language,
                        correlation_id=body.correlationId or body.clientEventId,
                    )
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except SubtitleSourceError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        @self.app.post("/api/session/prepare")
        async def api_prepare_session(body: PrepareSessionBody) -> dict[str, object]:
            try:
                session = await self.controller.prepare_session(
                    mode=body.mode,
                    feature_id=body.matchId if body.matchId is not None else body.featureId,
                    source_file_id=body.sourceResultId if body.sourceResultId is not None else body.sourceFileId,
                    target_file_id=body.targetResultId if body.targetResultId is not None else body.targetFileId,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except SubtitleSourceError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            except TranslationError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            return {"session": session}

        @self.app.post("/api/session/start")
        async def api_start_session(body: StartSessionBody) -> dict[str, object]:
            try:
                result = await self.controller.start_session(body.sessionId)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return result

        @self.app.post("/api/session/stop")
        async def api_stop_session() -> dict[str, object]:
            try:
                return await self.controller.stop_session()
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @self.app.websocket("/ws/app")
        async def app_websocket_route(websocket: WebSocket) -> None:
            await self._app_socket(websocket)

    @property
    def config(self) -> AppConfig:
        return self.controller.config

    async def _app_socket(self, websocket: WebSocket) -> None:
        await websocket.accept()
        logger.debug("App WebSocket connected (total: %d)", len(self.app_connections) + 1)
        self.app_connections.append(websocket)
        await websocket.send_text(json.dumps({"type": "state", "state": self.controller.state_snapshot()}))
        await websocket.send_text(json.dumps({"type": "style", "style": overlay_style_payload(self.config)}))
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            if websocket in self.app_connections:
                self.app_connections.remove(websocket)
            logger.debug("App WebSocket disconnected (remaining: %d)", len(self.app_connections))

    async def broadcast(self, subtitle_text: str) -> None:
        await self.controller.broadcast_overlay_subtitle(subtitle_text)

    async def broadcast_app_event(self, event_type: str, payload: dict[str, object]) -> None:
        message = {"type": event_type, **payload}
        await self._broadcast(self.app_connections, message)

    async def broadcast_overlay_event(self, event_type: str, payload: dict[str, object]) -> None:
        if event_type == "subtitle":
            message = {"type": event_type, "text": str(payload.get("text", ""))}
        elif event_type == "style":
            message = {"type": event_type, "style": payload.get("style", {})}
        else:
            message = {"type": event_type, **payload}
        await self._broadcast(self.overlay_connections, message)

    async def _broadcast(self, connections: list[WebSocket], message: dict[str, object]) -> None:
        encoded = json.dumps(message)
        dead: list[WebSocket] = []
        for websocket in tuple(connections):
            try:
                await websocket.send_text(encoded)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            if websocket in connections:
                connections.remove(websocket)
