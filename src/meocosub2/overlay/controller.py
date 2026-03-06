"""GUI session controller for the local web dashboard."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from meocosub2.config import AppConfig, config_to_payload, overlay_style_payload, save_config
from meocosub2.models import AppProgress, AppStateSnapshot, PreparedSession, SearchRequest, SubtitlePair
from meocosub2.opensubtitles.client import OpenSubtitlesClient
from meocosub2.subtitles import align_subtitles, load_subtitle_file
from meocosub2.sync import run_sync_loop
from meocosub2.translator import translate_lines


def search_result_payload(result: Any) -> dict[str, object]:
    return {
        "id": result.id,
        "title": result.title,
        "year": result.year,
        "imdbId": result.imdb_id,
        "mediaType": result.media_type,
        "season": result.season,
        "episode": result.episode,
        "language": result.language,
        "downloadCount": result.download_count,
        "fileId": result.file_id,
        "fileName": result.file_name,
        "displayLabel": result.display_label(),
    }


class GuiController:
    def __init__(
        self,
        config: AppConfig,
        app_event_emitter,
        overlay_event_emitter,
        config_path: Path | None = None,
    ) -> None:
        self.config = config
        self._emit_app_event = app_event_emitter
        self._emit_overlay_event = overlay_event_emitter
        self._config_path = config_path
        self._lock = asyncio.Lock()
        self._sync_task: asyncio.Task[None] | None = None
        self._prepared_pair: SubtitlePair | None = None
        self._runtime_port = config.overlay_port
        self._state = AppStateSnapshot(
            source_language=config.source_language,
            target_language=config.target_language,
            overlay_url=f"http://127.0.0.1:{self._runtime_port}/overlay",
        )

    def state_snapshot(self) -> dict[str, object]:
        snapshot = asdict(self._state)
        snapshot["config"] = config_to_payload(self.config)
        return snapshot

    async def emit_initial_events(self) -> None:
        await self._emit_app_state()
        await self._emit_overlay_event("style", {"style": overlay_style_payload(self.config)})
        if self._state.last_subtitle:
            await self._emit_overlay_event("subtitle", {"text": self._state.last_subtitle})

    async def get_config_payload(self) -> dict[str, object]:
        return config_to_payload(self.config)

    async def save_config_payload(self, payload: dict[str, object]) -> dict[str, object]:
        from meocosub2.config import config_from_payload

        new_config = config_from_payload(payload, fallback=self.config)
        save_config(new_config, self._config_path)
        self.config = new_config
        self._state.source_language = new_config.source_language
        self._state.target_language = new_config.target_language
        await self._emit_app_state()
        await self._emit_app_event("style", {"style": overlay_style_payload(self.config)})
        await self._emit_overlay_event("style", {"style": overlay_style_payload(self.config)})
        return config_to_payload(self.config)

    async def search(self, request: SearchRequest) -> list[dict[str, object]]:
        async with self._lock:
            self._state.status = "searching"
            self._state.title = request.title
            self._state.source_language = request.source_language
            self._state.target_language = request.target_language
            self._state.error_message = ""
            self._state.progress = AppProgress(stage="search", message="Searching OpenSubtitles...")
        await self._emit_app_state()
        await self._emit_app_progress()

        api_key = self.config.opensubtitles_api_key
        if not api_key:
            await self._set_error("OpenSubtitles API key is not configured.")
            raise ValueError("OpenSubtitles API key is not configured.")

        try:
            async with OpenSubtitlesClient(api_key=api_key) as client:
                results = await client.search(
                    request.title,
                    languages=f"{request.source_language},{request.target_language}",
                )
        except Exception as exc:
            await self._set_error(str(exc))
            raise

        payload = [search_result_payload(result) for result in results]
        async with self._lock:
            self._state.status = "idle"
            self._state.search_results = payload
            self._state.selected_source_file_id = None
            self._state.selected_target_file_id = None
            self._state.prepared_session = None
            self._state.progress = AppProgress()
        await self._emit_app_state()
        return payload

    async def prepare_session(self, source_file_id: int, target_file_id: int | None = None) -> dict[str, object]:
        if self._sync_task and not self._sync_task.done():
            await self._set_error("Stop the active session before preparing another one.")
            raise RuntimeError("A session is already running.")

        source_result = self._find_search_result(source_file_id)
        if source_result is None:
            raise ValueError("Selected source subtitle was not found in the current search results.")
        target_result = self._find_search_result(target_file_id) if target_file_id else None
        if target_file_id is not None and target_result is None:
            raise ValueError("Selected target subtitle was not found in the current search results.")

        async with self._lock:
            self._state.status = "preparing"
            self._state.selected_source_file_id = source_file_id
            self._state.selected_target_file_id = target_file_id
            self._state.error_message = ""
            self._state.progress = AppProgress(stage="download", message="Downloading subtitle files...", current=0, total=2)
        await self._emit_app_state()
        await self._emit_app_progress()

        try:
            async with OpenSubtitlesClient(api_key=self.config.opensubtitles_api_key) as client:
                source_path = await client.download(
                    source_file_id,
                    str(source_result.get("fileName") or f"{source_file_id}.srt"),
                )
                await self._set_progress("download", "Downloaded source subtitles.", 1, 2)
                target_path: Path | None = None
                if target_result is not None:
                    target_path = await client.download(
                        int(target_result["fileId"]),
                        str(target_result.get("fileName") or f"{target_result['fileId']}.srt"),
                    )
                await self._set_progress("download", "Downloaded subtitle files.", 2, 2)

            source_lines = load_subtitle_file(source_path)
            target_lines = load_subtitle_file(target_path) if target_path else []

            used_translation = False
            if target_lines:
                for source_line, target_line in zip(source_lines, target_lines):
                    source_line.translated = target_line.text
            else:
                used_translation = True
                await self._set_progress("translation", "Translating subtitles...", 0, len(source_lines))
                await translate_lines(
                    source_lines,
                    self.config,
                    progress_callback=lambda done, total: self._set_progress(
                        "translation",
                        "Translating subtitles...",
                        done,
                        total,
                    ),
                )
        except Exception as exc:
            await self._set_error(str(exc))
            raise

        pair = align_subtitles(source_lines, target_lines)
        session = PreparedSession(
            session_id=uuid4().hex[:8],
            title=self._state.title,
            source_language=self._state.source_language,
            target_language=self._state.target_language,
            source_file_id=source_file_id,
            source_file_name=str(source_result.get("fileName") or ""),
            source_path=str(source_path),
            source_line_count=len(source_lines),
            target_file_id=int(target_result["fileId"]) if target_result is not None else None,
            target_file_name=str(target_result.get("fileName") or "") if target_result is not None else None,
            target_path=str(target_path) if target_path is not None else None,
            target_line_count=len(target_lines),
            translated_line_count=sum(1 for line in source_lines if line.translated),
            used_translation=used_translation,
        )

        async with self._lock:
            self._prepared_pair = pair
            self._state.prepared_session = session
            self._state.status = "idle"
            self._state.progress = AppProgress(stage="ready", message="Session prepared.", current=1, total=1)
        await self._emit_app_state()
        await self._emit_app_progress()
        return asdict(session)

    async def start_session(self, session_id: str | None = None) -> dict[str, object]:
        if self._prepared_pair is None or self._state.prepared_session is None:
            raise ValueError("Prepare a session before starting sync.")
        if session_id and session_id != self._state.prepared_session.session_id:
            raise ValueError("Prepared session does not match the requested session ID.")
        if self._sync_task and not self._sync_task.done():
            raise RuntimeError("A session is already running.")

        async with self._lock:
            self._state.status = "running"
            self._state.error_message = ""
            self._state.progress = AppProgress(stage="sync", message="Sync loop is running.", current=1, total=1)
        await self._emit_app_state()
        await self._emit_app_progress()

        self._sync_task = asyncio.create_task(self._run_sync_loop(self._prepared_pair, self.config))
        return {"status": self._state.status}

    async def stop_session(self) -> dict[str, object]:
        task = self._sync_task
        if task is None or task.done():
            async with self._lock:
                self._state.status = "idle"
                self._state.last_subtitle = ""
                self._state.progress = AppProgress()
            await self._emit_app_state()
            await self._emit_app_event("subtitle", {"text": ""})
            await self._emit_overlay_event("subtitle", {"text": ""})
            return {"status": self._state.status}

        async with self._lock:
            self._state.status = "stopping"
            self._state.progress = AppProgress(stage="stopping", message="Stopping session...", current=0, total=1)
        await self._emit_app_state()
        await self._emit_app_progress()

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            self._sync_task = None

        async with self._lock:
            self._state.status = "idle"
            self._state.last_subtitle = ""
            self._state.progress = AppProgress()
        await self._emit_app_state()
        await self._emit_app_event("subtitle", {"text": ""})
        await self._emit_overlay_event("subtitle", {"text": ""})
        return {"status": self._state.status}

    async def broadcast_overlay_subtitle(self, subtitle_text: str) -> None:
        async with self._lock:
            self._state.last_subtitle = subtitle_text
        await self._emit_app_event("subtitle", {"text": subtitle_text})
        await self._emit_overlay_event("subtitle", {"text": subtitle_text})

    async def shutdown(self) -> None:
        task = self._sync_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run_sync_loop(self, pair: SubtitlePair, config: AppConfig) -> None:
        try:
            await run_sync_loop(pair, config, self.broadcast_overlay_subtitle)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive safety
            await self._set_error(str(exc))
        finally:
            if self._sync_task is asyncio.current_task():
                self._sync_task = None

    def _find_search_result(self, file_id: int | None) -> dict[str, object] | None:
        if file_id is None:
            return None
        for item in self._state.search_results:
            if int(item.get("fileId", -1)) == file_id:
                return item
        return None

    async def _set_progress(self, stage: str, message: str, current: int, total: int) -> None:
        async with self._lock:
            self._state.progress = AppProgress(stage=stage, message=message, current=current, total=total)
        await self._emit_app_progress()

    async def _set_error(self, message: str) -> None:
        async with self._lock:
            self._state.status = "error"
            self._state.error_message = message
            self._state.progress = AppProgress()
        await self._emit_app_state()
        await self._emit_app_event("error", {"message": message})

    async def _emit_app_state(self) -> None:
        await self._emit_app_event("state", {"state": self.state_snapshot()})

    async def _emit_app_progress(self) -> None:
        await self._emit_app_event("progress", {"progress": asdict(self._state.progress)})
