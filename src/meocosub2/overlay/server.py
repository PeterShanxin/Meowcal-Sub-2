"""FastAPI server for the dashboard and subtitle overlay."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from meocosub2.auth import TOKEN_HEADER, TOKEN_QUERY, token_matches
from meocosub2.capture import available_ocr_languages, capture_region_jpeg
from meocosub2.config import AppConfig, overlay_style_payload
from meocosub2.errors import SubtitleSourceError, TranslationError
from meocosub2.event_log import log_event
from meocosub2.languages import languages_payload
from meocosub2.models import SearchRequest
from meocosub2.overlay.controller import GuiController
from meocosub2.overlay.subtitle_editor import editor_router

STATIC_DIR = Path(__file__).parent / "static"
logger = logging.getLogger(__name__)


class SearchBody(BaseModel):
    title: str
    sourceLanguage: str | None = None
    targetLanguage: str | None = None
    clientEventId: str | None = None
    correlationId: str | None = None


class HydrateEpisodeBody(BaseModel):
    workId: str
    title: str
    season: int
    episode: int
    clientEventId: str | None = None
    correlationId: str | None = None


class HydrateSeasonBody(BaseModel):
    workId: str
    title: str
    season: int
    clientEventId: str | None = None
    correlationId: str | None = None


class ClientLogBody(BaseModel):
    event: str
    level: Literal["debug", "info", "warning", "error"] = "info"
    correlationId: str | None = None
    data: dict[str, object] = Field(default_factory=dict)


class InspectSourceBody(BaseModel):
    sourceResultId: str | int
    matchId: str | int | None = None


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
    def __init__(
        self,
        config: AppConfig,
        config_path: Path | None = None,
        *,
        access_token: str,
    ) -> None:
        self.app_connections: list[WebSocket] = []
        self._access_token = access_token
        self._allowed_origins = {
            f"http://127.0.0.1:{config.overlay_port}",
            f"http://localhost:{config.overlay_port}",
        }
        self.controller = GuiController(
            config=config,
            app_event_emitter=self.broadcast_app_event,
            config_path=config_path,
        )

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            yield
            await self.controller.shutdown()

        self.app = FastAPI(lifespan=lifespan)
        self.app.include_router(editor_router(self.controller))
        self.app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @self.app.middleware("http")
        async def authenticate(request: Request, call_next):
            # The bundle under /static is public code with no state in it; every
            # route that reads or changes app state is behind the run token.
            if request.scope["path"].startswith("/static/"):
                return await call_next(request)
            origin = request.headers.get("origin")
            if origin is not None and origin not in self._allowed_origins:
                return JSONResponse({"detail": "Forbidden origin"}, status_code=403)
            if not self._authorized(
                request.headers.get(TOKEN_HEADER), request.query_params.get(TOKEN_QUERY)
            ):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            return await call_next(request)

        @self.app.get("/")
        async def index() -> HTMLResponse:
            return HTMLResponse(
                self._page_html("index.html"),
                headers={"Cache-Control": "no-store, max-age=0"},
            )

        @self.app.get("/overlay")
        async def overlay_page() -> HTMLResponse:
            """The subtitle plate the shell floats beside the capture region."""
            return HTMLResponse(
                self._page_html("overlay.html"),
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

        @self.app.get("/api/engine/status")
        async def api_get_engine_status() -> dict[str, object]:
            return await self.controller.get_engine_status_payload()

        @self.app.post("/api/engine/install")
        async def api_install_engine() -> dict[str, object]:
            return await self.controller.install_engine_payload()

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

        @self.app.get("/api/capture/screen")
        async def api_capture_screen(x: int, y: int, width: int, height: int) -> dict[str, object]:
            """A still of the screen for the capture selector's backdrop.

            The selector floats over whatever the user is watching, and a player
            underneath a full-screen window is free to stop painting its video -
            so the region gets drawn on a frame taken just before the selector
            appears rather than on the live desktop.
            """
            jpeg = await asyncio.to_thread(capture_region_jpeg, (x, y, width, height))
            encoded = base64.b64encode(jpeg).decode("ascii")
            return {"dataUrl": f"data:image/jpeg;base64,{encoded}"}

        @self.app.post("/api/log/client")
        async def api_log_client(body: ClientLogBody) -> dict[str, str]:
            log_event(
                body.event,
                layer="frontend",
                level=body.level,
                correlation_id=body.correlationId,
                data=body.data,
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

        @self.app.post("/api/search/episode")
        async def api_hydrate_episode(body: HydrateEpisodeBody) -> dict[str, object]:
            try:
                return await self.controller.hydrate_episode(
                    work_id=body.workId,
                    title=body.title,
                    season=body.season,
                    episode=body.episode,
                    correlation_id=body.correlationId or body.clientEventId,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except SubtitleSourceError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        @self.app.post("/api/search/season")
        async def api_hydrate_season(body: HydrateSeasonBody) -> dict[str, object]:
            try:
                return await self.controller.hydrate_season(
                    work_id=body.workId,
                    title=body.title,
                    season=body.season,
                    correlation_id=body.correlationId or body.clientEventId,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except SubtitleSourceError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        @self.app.post("/api/source/inspect")
        async def api_inspect_source(body: InspectSourceBody) -> dict[str, object]:
            try:
                return await self.controller.inspect_source(
                    source_file_id=str(body.sourceResultId),
                    feature_id=str(body.matchId) if body.matchId is not None else None,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except SubtitleSourceError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        @self.app.post("/api/session/prepare")
        async def api_prepare_session(body: PrepareSessionBody) -> dict[str, object]:
            try:
                session = await self.controller.prepare_session(
                    mode=body.mode,
                    feature_id=body.matchId if body.matchId is not None else body.featureId,
                    source_file_id=body.sourceResultId
                    if body.sourceResultId is not None
                    else body.sourceFileId,
                    target_file_id=body.targetResultId
                    if body.targetResultId is not None
                    else body.targetFileId,
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
            origin = websocket.headers.get("origin")
            if origin is not None and origin not in self._allowed_origins:
                await websocket.close(code=1008)
                return
            if not self._authorized(
                websocket.headers.get(TOKEN_HEADER), websocket.query_params.get(TOKEN_QUERY)
            ):
                await websocket.close(code=1008)
                return
            await self._app_socket(websocket)

    @property
    def config(self) -> AppConfig:
        return self.controller.config

    def _authorized(self, header_token: str | None, query_token: str | None) -> bool:
        return token_matches(self._access_token, header_token) or token_matches(
            self._access_token, query_token
        )

    def _page_html(self, file_name: str) -> str:
        """A served page with this run's token, handed only to callers that already have it."""
        markup = (STATIC_DIR / file_name).read_text(encoding="utf-8")
        bootstrap = (
            "<script>window.__MEOWCAL__=" + json.dumps({"token": self._access_token}) + ";</script>"
        )
        return markup.replace("</head>", f"{bootstrap}</head>", 1)

    async def _app_socket(self, websocket: WebSocket) -> None:
        await websocket.accept()
        logger.debug("App WebSocket connected (total: %d)", len(self.app_connections) + 1)
        self.app_connections.append(websocket)
        await websocket.send_text(
            json.dumps({"type": "state", "state": self.controller.state_snapshot()})
        )
        await websocket.send_text(
            json.dumps({"type": "style", "style": overlay_style_payload(self.config)})
        )
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            if websocket in self.app_connections:
                self.app_connections.remove(websocket)
            logger.debug("App WebSocket disconnected (remaining: %d)", len(self.app_connections))

    async def broadcast_app_event(self, event_type: str, payload: dict[str, object]) -> None:
        message = {"type": event_type, **payload}
        await self._broadcast(self.app_connections, message)

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
