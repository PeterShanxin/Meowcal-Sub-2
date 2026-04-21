"""GUI session controller for the local web dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

from meocosub2.capture import available_ocr_languages, resolve_ocr_language
from meocosub2.config import AppConfig, config_to_payload, overlay_style_payload, save_config
from meocosub2.errors import SubtitleSourceError, TranslationError
from meocosub2.foundry import foundry_status, make_foundry_ready
from meocosub2.languages import language_label, normalize_ocr_language, source_language_mode
from meocosub2.models import AppProgress, AppStateSnapshot, PreparedRuntime, PreparedSession, SearchRequest
from meocosub2.subtitle_sources import AggregatedSearchCatalog, AggregatedSubtitleResult, AggregatedTitleMatch, SubtitleSearchAggregator
from meocosub2.subtitles import align_subtitles, assign_target_translations, load_subtitle_file
from meocosub2.sync import run_ocr_fallback_loop, run_sync_loop
from meocosub2.translator import translate_lines


def search_result_payload(result: AggregatedSubtitleResult) -> dict[str, object]:
    return {
        "id": result.result_id,
        "resultId": result.result_id,
        "matchId": result.match_id,
        "provider": result.provider,
        "providerLabel": result.provider_label,
        "title": result.title,
        "year": result.year,
        "imdbId": result.imdb_id,
        "mediaType": result.media_type,
        "season": result.season,
        "episode": result.episode,
        "parentTitle": result.parent_title,
        "language": result.language,
        "downloadCount": result.download_count,
        "fileName": result.file_name,
        "matchScore": result.match_score,
        "providerRank": result.provider_rank,
        "displayLabel": result.display_label(),
        "languageLabel": language_label(result.language),
    }


def search_match_payload(match: AggregatedTitleMatch) -> dict[str, object]:
    return {
        "id": match.id,
        "matchId": match.id,
        "title": match.title,
        "year": match.year,
        "imdbId": match.imdb_id,
        "tmdbId": match.tmdb_id,
        "mediaType": match.media_type,
        "season": match.season,
        "episode": match.episode,
        "parentTitle": match.parent_title,
        "subtitlesCount": match.subtitles_count,
        "matchScore": match.match_score,
        "providerCount": match.provider_count,
        "providers": list(match.providers),
        "providerLabels": list(match.provider_labels),
        "displayLabel": match.display_label(),
    }


OCR_CAPABILITY_TAGS: dict[str, tuple[str, ...]] = {
    "en-US": ("en-US",),
    "zh-CN": ("zh-CN", "zh-Hans", "zh-Hans-CN"),
    "zh-TW": ("zh-TW", "zh-Hant", "zh-Hant-TW"),
    "ja-JP": ("ja-JP", "ja"),
    "ko-KR": ("ko-KR", "ko"),
    "es-ES": ("es-ES", "es"),
    "fr-FR": ("fr-FR", "fr"),
    "de-DE": ("de-DE", "de"),
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
        self._prepared_runtime: PreparedRuntime | None = None
        self._runtime_port = config.overlay_port
        self._aggregator = SubtitleSearchAggregator(config)
        self._search_catalog: AggregatedSearchCatalog | None = None
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

    async def get_foundry_status_payload(self, probe: bool = False, auto_start: bool = False) -> dict[str, object]:
        logger.debug("get_foundry_status_payload(probe=%s, auto_start=%s)", probe, auto_start)
        status = await asyncio.to_thread(foundry_status, self.config, probe, auto_start)
        logger.info("Foundry status: phase=%s notes=%s", status.phase, status.notes)
        return asdict(status)

    async def prepare_foundry_payload(self) -> dict[str, object]:
        status = await asyncio.to_thread(make_foundry_ready, self.config)
        return asdict(status)

    async def install_ocr_language(self, language_tag: str) -> dict[str, object]:
        normalized = normalize_ocr_language(language_tag)
        capability_tags = OCR_CAPABILITY_TAGS.get(normalized)
        if capability_tags is None:
            raise ValueError(f"Unsupported OCR language: {language_tag}")

        before_languages = {normalize_ocr_language(code) for code in available_ocr_languages()}
        result_path = Path(tempfile.gettempdir()) / f"meowcal-sub2-ocr-install-{uuid4().hex}.json"
        pattern_list = ", ".join(f"'{tag}'" for tag in capability_tags)
        escaped_result_path = str(result_path).replace("'", "''")
        escaped_label = normalized.replace("'", "''")
        inner_script = (
            f"$patterns = @({pattern_list}); "
            f"Write-Host 'Installing OCR language pack: {escaped_label}...' -ForegroundColor Cyan; "
            "$caps = @(); "
            "foreach ($pattern in $patterns) { "
            "  $caps += Get-WindowsCapability -Online | Where-Object { $_.Name -Like \"Language.OCR*$pattern*\" }; "
            "} "
            "$caps = @($caps | Sort-Object Name -Unique); "
            "$supported = ($caps.Count -gt 0); "
            "if ($supported) { "
            "  $pending = @($caps | Where-Object { $_.State -ne 'Installed' }); "
            "  if ($pending.Count -gt 0) { $pending | Add-WindowsCapability -Online | Out-Null }; "
            "  $caps = @(); "
            "  foreach ($pattern in $patterns) { "
            "    $caps += Get-WindowsCapability -Online | Where-Object { $_.Name -Like \"Language.OCR*$pattern*\" }; "
            "  } "
            "  $caps = @($caps | Sort-Object Name -Unique); "
            "  $installed = (@($caps | Where-Object { $_.State -eq 'Installed' }).Count -gt 0); "
            "  $message = if ($installed) { 'OCR language pack is installed.' } else { 'OCR capability install completed, but Windows still does not report it as installed.' }; "
            "} else { "
            "  $installed = $false; "
            "  $message = 'OCR language pack is not available on this system.'; "
            "} "
            "$payload = @{ supported = $supported; installed = $installed; message = $message; capabilities = @($caps | ForEach-Object { @{ name = $_.Name; state = $_.State } }) }; "
            f"$payload | ConvertTo-Json -Compress | Set-Content -LiteralPath '{escaped_result_path}';"
        )

        outer_args = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -Command "
            + inner_script.replace("'", "''")
            + "'",
        ]

        await asyncio.to_thread(
            subprocess.run,
            outer_args,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
        payload: dict[str, object] = {
            "requested": normalized,
            "supported": False,
            "installed": False,
            "message": f"{normalized} OCR pack is not available on this system.",
            "capabilities": [],
        }
        try:
            if result_path.exists():
                payload.update(json.loads(result_path.read_text(encoding="utf-8")))
        finally:
            result_path.unlink(missing_ok=True)

        after_languages = {normalize_ocr_language(code) for code in available_ocr_languages()}
        payload["availableLanguages"] = sorted(after_languages)
        payload["installed"] = normalized in after_languages
        payload["changed"] = normalized not in before_languages and payload["installed"]
        if payload["installed"]:
            payload["message"] = "OCR language pack is installed."
        elif payload.get("supported"):
            payload["message"] = (
                "Windows finished the install flow, but the OCR language still is not available. "
                "Restart Windows or install the full language pack, or switch the source language."
            )
        return payload

    async def save_config_payload(self, payload: dict[str, object]) -> dict[str, object]:
        logger.info("Saving config")
        from meocosub2.config import config_from_payload

        new_config = config_from_payload(payload, fallback=self.config)
        save_config(new_config, self._config_path)
        self.config = new_config
        self._aggregator = SubtitleSearchAggregator(new_config)
        self._search_catalog = None
        self._state.source_language = new_config.source_language
        self._state.target_language = new_config.target_language
        await self._emit_app_state()
        await self._emit_app_event("style", {"style": overlay_style_payload(self.config)})
        await self._emit_overlay_event("style", {"style": overlay_style_payload(self.config)})
        return config_to_payload(self.config)

    async def search(self, request: SearchRequest) -> dict[str, object]:
        logger.info("Search: title=%r source=%s target=%s", request.title, request.source_language, request.target_language)
        async with self._lock:
            self._state.status = "searching"
            self._state.title = request.title
            self._state.source_language = request.source_language
            self._state.target_language = request.target_language
            self._state.error_message = ""
            self._state.warning_message = ""
            self._state.progress = AppProgress(stage="search", message="Searching subtitle sources...")
        await self._emit_app_state()
        await self._emit_app_progress()

        languages = _expand_search_languages(request.source_language, request.target_language)
        try:
            catalog = await self._aggregator.search_catalog(request.title, languages)
        except Exception as exc:
            await self._set_error(str(exc))
            raise

        payload = [search_result_payload(result) for result in catalog.results]
        matches = [search_match_payload(match) for match in catalog.matches]
        async with self._lock:
            self._search_catalog = catalog
            self._state.status = "idle"
            self._state.search_results = payload
            self._state.search_matches = matches
            self._state.selected_feature_id = matches[0]["id"] if matches else None
            self._state.selected_source_file_id = None
            self._state.selected_target_file_id = None
            self._state.prepared_session = None
            self._state.progress = AppProgress()
            self._state.warning_message = "; ".join(catalog.warnings[:3]) if catalog.warnings else ""
            self._prepared_runtime = None
        await self._emit_app_state()
        return {"results": payload, "matches": matches, "warnings": catalog.warnings}

    async def prepare_session(
        self,
        mode: str,
        feature_id: str | None = None,
        source_file_id: str | None = None,
        target_file_id: str | None = None,
    ) -> dict[str, object]:
        logger.info(
            "Prepare session: mode=%s feature_id=%s source_file_id=%s target_file_id=%s",
            mode,
            feature_id,
            source_file_id,
            target_file_id,
        )
        if self._sync_task and not self._sync_task.done():
            await self._set_error("Stop the active session before preparing another one.")
            raise RuntimeError("A session is already running.")
        if mode not in {"subtitle_pair", "ocr_fallback"}:
            raise ValueError(f"Unsupported session mode: {mode}")
        if mode == "ocr_fallback":
            return await self._prepare_ocr_fallback_session(feature_id or self._state.selected_feature_id, target_file_id)
        if source_file_id is None:
            raise ValueError("Select a source subtitle before preparing a subtitle-pair session.")
        return await self._prepare_subtitle_pair_session(feature_id, source_file_id, target_file_id)

    async def _prepare_subtitle_pair_session(
        self,
        feature_id: str | None,
        source_file_id: str,
        target_file_id: str | None,
    ) -> dict[str, object]:
        source_result = self._find_search_result(source_file_id)
        if source_result is None:
            raise ValueError("Selected source subtitle was not found in the current search results.")
        target_result = self._find_search_result(target_file_id) if target_file_id else None
        if target_file_id is not None and target_result is None:
            raise ValueError("Selected target subtitle was not found in the current search results.")
        effective_feature_id = feature_id or self._feature_id_for_result(source_result)

        async with self._lock:
            self._state.status = "preparing"
            self._state.selected_feature_id = effective_feature_id
            self._state.selected_source_file_id = source_file_id
            self._state.selected_target_file_id = target_file_id
            self._state.error_message = ""
            self._state.warning_message = ""
            self._state.progress = AppProgress(stage="download", message="Downloading subtitle files...", current=0, total=2)
        await self._emit_app_state()
        await self._emit_app_progress()

        source_entry = self._catalog_result(source_file_id)
        if source_entry is None:
            raise ValueError("Selected source subtitle could not be resolved.")
        target_entry = self._catalog_result(target_file_id) if target_file_id else None

        try:
            source_path = await self._aggregator.download(source_entry)
            await self._set_progress("download", "Downloaded source subtitles.", 1, 2)
            target_path: Path | None = None
            if target_entry is not None:
                target_path = await self._aggregator.download(target_entry)
            await self._set_progress("download", "Downloaded subtitle files.", 2, 2)

            source_lines = load_subtitle_file(source_path)
            target_lines = load_subtitle_file(target_path) if target_path else []

            used_translation = False
            if target_lines:
                assign_target_translations(source_lines, target_lines)
            else:
                used_translation = True
                warm_status = await asyncio.to_thread(make_foundry_ready, self.config)
                if warm_status.phase != "ready":
                    raise TranslationError(warm_status.notes)
                await self._set_progress("translation", "Translating subtitles...", 0, len(source_lines))
                await translate_lines(
                    source_lines,
                    self.config,
                    progress_callback=lambda done, total: self._set_progress("translation", "Translating subtitles...", done, total),
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
            resolved_source_language=str(source_result.get("language") or self._state.source_language),
            source_language_mode=source_language_mode(
                self._state.source_language,
                str(source_result.get("language") or self._state.source_language),
            ),
            session_mode="subtitle_pair",
            target_match_mode="subtitle_file" if target_lines else "local_translation",
            feature_id=effective_feature_id,
            source_file_id=source_file_id,
            source_file_name=str(source_result.get("fileName") or ""),
            source_provider=str(source_result.get("providerLabel") or source_result.get("provider") or ""),
            source_path=str(source_path),
            source_line_count=len(source_lines),
            target_file_id=str(target_result.get("resultId") or target_file_id) if target_result is not None else None,
            target_file_name=str(target_result.get("fileName") or "") if target_result is not None else None,
            target_provider=str(target_result.get("providerLabel") or target_result.get("provider") or "") if target_result is not None else None,
            target_path=str(target_path) if target_path is not None else None,
            target_line_count=len(target_lines),
            translated_line_count=sum(1 for line in source_lines if line.translated),
            used_translation=used_translation,
        )

        async with self._lock:
            self._prepared_runtime = PreparedRuntime(
                session_mode="subtitle_pair",
                pair=pair,
                target_lines=target_lines,
                feature_id=effective_feature_id,
            )
            self._state.prepared_session = session
            self._state.status = "idle"
            self._state.progress = AppProgress(stage="ready", message="Session prepared.", current=1, total=1)
            if session.source_language_mode != "exact":
                self._state.warning_message = "Using a Chinese-family source subtitle fallback because no exact source language match was available."
        await self._emit_app_state()
        await self._emit_app_progress()
        return asdict(session)

    async def _prepare_ocr_fallback_session(
        self,
        feature_id: str | None,
        target_file_id: str | None,
    ) -> dict[str, object]:
        if feature_id is None:
            raise ValueError("Select a matched title before preparing an OCR fallback session.")
        feature = self._find_search_match(feature_id)
        if feature is None:
            raise ValueError("Selected title was not found in the current search matches.")

        target_result = self._find_search_result(target_file_id) if target_file_id else None
        if target_file_id is not None and target_result is None:
            raise ValueError("Selected target subtitle was not found in the current search results.")
        if target_result is not None and not self._result_matches_feature(target_result, feature_id):
            raise ValueError("Selected target subtitle does not belong to the chosen title.")

        async with self._lock:
            self._state.status = "preparing"
            self._state.selected_feature_id = feature_id
            self._state.selected_source_file_id = None
            self._state.selected_target_file_id = target_file_id
            self._state.error_message = ""
            self._state.warning_message = ""
            self._state.progress = AppProgress(stage="prepare", message="Preparing OCR fallback session...", current=0, total=1)
        await self._emit_app_state()
        await self._emit_app_progress()

        try:
            warm_status = await asyncio.to_thread(make_foundry_ready, self.config)
            if warm_status.phase != "ready":
                raise TranslationError(warm_status.notes)

            target_path: Path | None = None
            target_lines = []
            target_entry = self._catalog_result(target_file_id) if target_file_id else None
            if target_entry is not None:
                target_path = await self._aggregator.download(target_entry)
                target_lines = load_subtitle_file(target_path)
        except Exception as exc:
            await self._set_error(str(exc))
            raise

        title = str(feature.get("displayLabel") or feature.get("title") or self._state.title)
        session = PreparedSession(
            session_id=uuid4().hex[:8],
            title=title,
            source_language=self._state.source_language,
            target_language=self._state.target_language,
            resolved_source_language=self._state.source_language,
            source_language_mode="exact",
            session_mode="ocr_fallback",
            target_match_mode="target_subtitle_match" if target_lines else "direct_translation",
            feature_id=feature_id,
            target_file_id=str(target_result.get("resultId") or target_file_id) if target_result is not None else None,
            target_file_name=str(target_result.get("fileName") or "") if target_result is not None else None,
            target_provider=str(target_result.get("providerLabel") or target_result.get("provider") or "") if target_result is not None else None,
            target_path=str(target_path) if target_path is not None else None,
            target_line_count=len(target_lines),
            used_translation=True,
        )

        async with self._lock:
            self._prepared_runtime = PreparedRuntime(
                session_mode="ocr_fallback",
                pair=None,
                target_lines=target_lines,
                feature_id=feature_id,
            )
            self._state.prepared_session = session
            self._state.status = "idle"
            self._state.progress = AppProgress(stage="ready", message="OCR fallback session prepared.", current=1, total=1)
            self._state.warning_message = (
                "No source subtitle matched the requested language. The session will use OCR plus live AI translation."
            )
        await self._emit_app_state()
        await self._emit_app_progress()
        return asdict(session)

    async def start_session(self, session_id: str | None = None) -> dict[str, object]:
        logger.info("Start session: session_id=%s", session_id)
        if self._prepared_runtime is None or self._state.prepared_session is None:
            raise ValueError("Prepare a session before starting sync.")
        if session_id and session_id != self._state.prepared_session.session_id:
            raise ValueError("Prepared session does not match the requested session ID.")
        if self._sync_task and not self._sync_task.done():
            raise RuntimeError("A session is already running.")

        resolution = resolve_ocr_language(self.config.ocr_language)
        if resolution.warning_message and resolution.resolved_language == resolution.requested_language and "not installed" in resolution.warning_message.lower():
            raise RuntimeError(resolution.warning_message)
        async with self._lock:
            self._state.status = "running"
            self._state.error_message = ""
            self._state.warning_message = resolution.warning_message
            message = (
                "Sync loop is running."
                if self._prepared_runtime.session_mode == "subtitle_pair"
                else "OCR fallback loop is running."
            )
            self._state.progress = AppProgress(stage="sync", message=message, current=1, total=1)
        await self._emit_app_state()
        await self._emit_app_progress()

        self._sync_task = asyncio.create_task(self._run_sync_loop(self._prepared_runtime, self.config))
        return {"status": self._state.status}

    async def stop_session(self) -> dict[str, object]:
        logger.info("Stop session requested")
        task = self._sync_task
        if task is None or task.done():
            async with self._lock:
                self._state.status = "idle"
                self._state.last_subtitle = ""
                self._state.progress = AppProgress()
                self._state.warning_message = ""
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
            self._state.warning_message = ""
        await self._emit_app_state()
        await self._emit_app_event("subtitle", {"text": ""})
        await self._emit_overlay_event("subtitle", {"text": ""})
        return {"status": self._state.status}

    def _make_debug_broadcast(self) -> Callable[[dict[str, object]], Awaitable[None]]:
        async def cb(data: dict[str, object]) -> None:
            await self._emit_app_event("debug", {"data": data})
        return cb

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

    async def _run_sync_loop(self, runtime: PreparedRuntime, config: AppConfig) -> None:
        debug_cb = self._make_debug_broadcast() if config.debug_mode else None
        try:
            if runtime.session_mode == "subtitle_pair":
                if runtime.pair is None:
                    raise RuntimeError("Prepared subtitle-pair runtime is missing source data.")
                await run_sync_loop(runtime.pair, config, self.broadcast_overlay_subtitle, debug_broadcast=debug_cb)
            else:
                await run_ocr_fallback_loop(runtime.target_lines, config, self.broadcast_overlay_subtitle, debug_broadcast=debug_cb)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive safety
            await self._set_error(str(exc))
        finally:
            if self._sync_task is asyncio.current_task():
                self._sync_task = None

    def _catalog_result(self, result_id: str | None) -> AggregatedSubtitleResult | None:
        return self._search_catalog.find_result(result_id) if self._search_catalog else None

    def _find_search_result(self, file_id: str | None) -> dict[str, object] | None:
        if file_id is None:
            return None
        for item in self._state.search_results:
            if str(item.get("resultId") or item.get("id") or "") == str(file_id):
                return item
        return None

    def _find_search_match(self, feature_id: str | None) -> dict[str, object] | None:
        if feature_id is None:
            return None
        for item in self._state.search_matches:
            if str(item.get("matchId") or item.get("id") or "") == str(feature_id):
                return item
        return None

    def _feature_id_for_result(self, result: dict[str, object]) -> str | None:
        value = result.get("matchId") or result.get("id")
        return str(value) if value not in {None, ""} else None

    def _result_matches_feature(self, result: dict[str, object], feature_id: str) -> bool:
        return str(result.get("matchId") or "") == str(feature_id)

    async def _set_progress(self, stage: str, message: str, current: int, total: int) -> None:
        async with self._lock:
            self._state.progress = AppProgress(stage=stage, message=message, current=current, total=total)
        await self._emit_app_progress()

    async def _set_error(self, message: str) -> None:
        async with self._lock:
            self._state.status = "error"
            self._state.error_message = message
            self._state.warning_message = ""
            self._state.progress = AppProgress()
        await self._emit_app_state()
        await self._emit_app_event("error", {"message": message})

    async def _emit_app_state(self) -> None:
        await self._emit_app_event("state", {"state": self.state_snapshot()})

    async def _emit_app_progress(self) -> None:
        await self._emit_app_event("progress", {"progress": asdict(self._state.progress)})


def _expand_search_languages(source_language: str, target_language: str) -> str:
    requested = {source_language, target_language}
    normalized = {code.strip().lower() for code in requested if code}
    if "zh" in normalized or "zht" in normalized or any(code.startswith("zh") for code in normalized):
        normalized.update({"zh", "zht"})
    return ",".join(sorted(normalized))
