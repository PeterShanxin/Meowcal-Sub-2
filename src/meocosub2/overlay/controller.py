"""GUI session controller for the local web dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

from meocosub2 import engine
from meocosub2.bilingual import split_bilingual
from meocosub2.capture import available_ocr_languages, resolve_ocr_language
from meocosub2.config import AppConfig, config_to_payload, overlay_style_payload, save_config
from meocosub2.errors import TranslationError
from meocosub2.event_log import log_event
from meocosub2.languages import (
    is_chinese_family,
    language_label,
    normalize_ocr_language,
    normalize_source_language,
    source_language_mode,
    source_result_matches_requested_language,
)
from meocosub2.models import (
    AppProgress,
    AppStateSnapshot,
    PreparedRuntime,
    PreparedSession,
    SearchRequest,
    SourceSubtitleCandidate,
    SubtitleLine,
    SubtitlePair,
    TargetAlignment,
)
from meocosub2.semantic import SemanticIndex
from meocosub2.subtitle_sources import (
    AggregatedEpisode,
    AggregatedSearchCatalog,
    AggregatedSeason,
    AggregatedSubtitleResult,
    AggregatedTitleMatch,
    AggregatedWork,
    SubtitleSearchAggregator,
)
from meocosub2.subtitle_sources.utils import result_id_for
from meocosub2.subtitles import (
    align_subtitles,
    alignment_report,
    assign_target_translations,
    load_subtitle_file,
)
from meocosub2.sync import (
    MATCHED,
    CandidateSession,
    DirectTranslationSession,
    LiveTranslator,
    open_live_translator,
    run_session_loop,
)

logger = logging.getLogger(__name__)
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
AUTO_SOURCE_CANDIDATE_LIMIT = 3
AUTO_TARGET_CANDIDATE_LIMIT = 1
# How many target files the viewer did not choose are weighed against the source,
# so they can see whether a better-aligned one was on offer. Each is tens of
# kilobytes; the point is a comparison, not a survey.
TARGET_ALIGNMENT_SAMPLE = 3
# The whole comparison is advice arriving during preparation, so it is given a
# budget rather than a provider's timeout. Whatever is weighed inside it is
# reported; the rest is simply not mentioned.
TARGET_ALIGNMENT_BUDGET_S = 15.0
# Downloads left with a metered provider below which none are spent on advice.
# A session costs a source file and a target file, so this keeps back enough for
# the viewer to start one after the comparison decides against running.
DOWNLOADS_KEPT_FOR_WATCHING = 2
# Stands where a target file id would, for the translation a bilingual source
# already carries. It names no downloadable file, so it never reaches a provider.
SOURCE_OWN_TRANSLATION = "__source__"
# Shown when the engine is missing but the target file can carry the session on
# its own. It names what the viewer will see rather than what failed. The two
# symptoms differ: nothing has been drawn yet before the first match, while a
# cue the target file has no answer for leaves the previous line on the plate,
# which is the stale line this session's filling exists to replace.
NO_ENGINE_WARNING = (
    "Local translation is not installed, so the plate stays empty until the first match "
    "and holds the previous line through cues the target subtitles do not answer. "
    "Run setup from Settings to add it."
)


def _pair_target_mode(own_translation: bool, target_lines: list[SubtitleLine]) -> str:
    """Where a paired session's translations come from, for the studio to report."""
    if own_translation:
        return "source_own_translation"
    return "subtitle_file" if target_lines else "local_translation"


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


def search_work_payload(work: AggregatedWork) -> dict[str, object]:
    return {
        "id": work.id,
        "workId": work.id,
        "title": work.title,
        "mediaType": work.media_type,
        "year": work.year,
        "yearEnd": work.year_end,
        "displayYear": work.display_year(),
        "imdbId": work.imdb_id,
        "tmdbId": work.tmdb_id,
        "posterUrl": work.poster_url,
        "providers": list(work.providers),
        "providerLabels": list(work.provider_labels),
        "primaryMatchId": work.primary_match_id,
        "expandable": work.expandable,
        "totalEpisodes": work.total_episodes,
        "totalSubtitles": work.total_subtitles,
        "matchScore": work.match_score,
        "seasons": [
            {
                "seasonNumber": season.season_number,
                "subtitlesCount": season.subtitles_count,
                "episodes": [
                    {
                        "season": episode.season,
                        "episode": episode.episode,
                        "title": episode.title,
                        "matchId": episode.match_id,
                        "year": episode.year,
                        "subtitlesCount": episode.subtitles_count,
                        "providers": list(episode.providers),
                    }
                    for episode in season.episodes
                ],
            }
            for season in work.seasons
        ],
        "infoChips": [
            {"kind": chip.kind, "label": chip.label, "tone": chip.tone} for chip in work.info_chips
        ],
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
        config_path: Path | None = None,
    ) -> None:
        self.config = config
        self._emit_app_event = app_event_emitter
        self._config_path = config_path
        self._lock = asyncio.Lock()
        self._sync_task: asyncio.Task[None] | None = None
        self._prepared_runtime: PreparedRuntime | None = None
        # The source the target step read, kept so preparation does not fetch it
        # a second time. Only OpenSubtitles answers a repeat download from disk.
        self._inspected_source: tuple[str, Path] | None = None
        self._runtime_port = config.overlay_port
        self._aggregator = SubtitleSearchAggregator(config)
        self._search_catalog: AggregatedSearchCatalog | None = None
        # Which search a preparation was made from. Results are selectable
        # before every provider has answered, so the last one landing must
        # not throw away a session prepared from the same search's interim.
        self._prepared_search_id: str | None = None
        # Guards progressive search updates: a slow provider from an earlier
        # search must not clobber the state of a search the user has since
        # retyped past.
        self._active_search_id: str | None = None
        self._state = AppStateSnapshot(
            source_language=config.source_language,
            target_language=config.target_language,
        )

    def state_snapshot(self) -> dict[str, object]:
        snapshot = asdict(self._state)
        snapshot["config"] = config_to_payload(self.config)
        return snapshot

    async def get_config_payload(self) -> dict[str, object]:
        return config_to_payload(self.config)

    async def get_engine_status_payload(self) -> dict[str, object]:
        status = await asyncio.to_thread(engine.status)
        return status.payload()

    async def install_engine_payload(self) -> dict[str, object]:
        status = await asyncio.to_thread(engine.install_engine)
        return status.payload()

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
            '  $caps += Get-WindowsCapability -Online | Where-Object { $_.Name -Like "Language.OCR*$pattern*" }; '
            "} "
            "$caps = @($caps | Sort-Object Name -Unique); "
            "$supported = ($caps.Count -gt 0); "
            "if ($supported) { "
            "  $pending = @($caps | Where-Object { $_.State -ne 'Installed' }); "
            "  if ($pending.Count -gt 0) { $pending | Add-WindowsCapability -Online | Out-Null }; "
            "  $caps = @(); "
            "  foreach ($pattern in $patterns) { "
            '    $caps += Get-WindowsCapability -Online | Where-Object { $_.Name -Like "Language.OCR*$pattern*" }; '
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
        log_event(
            "config.save.requested",
            layer="backend",
            sections=sorted(str(key) for key in payload),
        )
        from meocosub2.config import config_from_payload

        # Always merge against the in-memory config so partial dashboard saves do
        # not silently reset unrelated settings.
        new_config = config_from_payload(payload, fallback=self.config)
        save_config(new_config, self._config_path)
        previous_config = self.config
        self.config = new_config
        self._aggregator = SubtitleSearchAggregator(new_config)
        if _search_inputs_changed(previous_config, new_config):
            self._clear_search_state()
        self._state.source_language = new_config.source_language
        self._state.target_language = new_config.target_language
        await self._emit_app_state()
        await self._emit_app_event("style", {"style": overlay_style_payload(self.config)})
        return config_to_payload(self.config)

    def _clear_search_state(self) -> None:
        """Drop the catalog and everything derived from it.

        The results the UI offers and the catalog a session is prepared from have
        to describe the same search. Dropping only the catalog left the studio
        showing titles whose candidates no longer existed, and preparing one of
        them fell through to OCR translation while reporting that no subtitle
        matched the language.
        """
        self._search_catalog = None
        self._state.search_results = []
        self._state.search_matches = []
        self._state.search_works = []
        self._state.selected_feature_id = None
        self._state.selected_source_file_id = None
        self._state.selected_target_file_id = None

    async def search(self, request: SearchRequest) -> dict[str, object]:
        correlation_id = request.correlation_id or f"search-{uuid4().hex[:12]}"
        started = time.perf_counter()
        logger.info(
            "Search: title=%r source=%s target=%s correlation_id=%s",
            request.title,
            request.source_language,
            request.target_language,
            correlation_id,
        )
        log_event(
            "search.requested",
            layer="backend",
            correlation_id=correlation_id,
            title=request.title,
            source_language=request.source_language,
            target_language=request.target_language,
        )
        self._active_search_id = correlation_id
        async with self._lock:
            self._state.status = "searching"
            self._state.title = request.title
            self._state.source_language = request.source_language
            self._state.target_language = request.target_language
            self._state.error_message = ""
            self._state.warning_message = ""
            self._state.progress = AppProgress(
                stage="search", message="Searching subtitle sources..."
            )
        await self._emit_app_state()
        await self._emit_app_progress()

        async def on_provider_update(
            succeeded_codes: list[str], settled_codes: list[str], interim: AggregatedSearchCatalog
        ) -> None:
            if self._active_search_id != correlation_id:
                return  # A newer search has already replaced this one.
            done_labels = [
                provider.provider_label
                for provider in self._aggregator.providers
                if provider.provider_code in succeeded_codes
            ]
            # A provider that failed is still settled — it must not linger in
            # "waiting on..." after it has already given up.
            pending_labels = [
                provider.provider_label
                for provider in self._aggregator.providers
                if provider.provider_code not in settled_codes
            ]
            total = len(self._aggregator.providers)
            if not pending_labels:
                message = (
                    f"{', '.join(done_labels)} answered — finishing up…"
                    if done_labels
                    else "Finishing up…"
                )
            elif done_labels:
                message = (
                    f"{', '.join(done_labels)} answered — waiting on {', '.join(pending_labels)}…"
                )
            else:
                message = f"Waiting on {', '.join(pending_labels)}…"
            async with self._lock:
                if self._active_search_id != correlation_id:
                    return
                # Stored with the results it describes, not when the search
                # finishes. These results are selectable the moment they are
                # shown, and every lookup behind that click reads the catalog.
                self._search_catalog = interim
                self._state.search_results = [
                    search_result_payload(result) for result in interim.results
                ]
                self._state.search_matches = [
                    search_match_payload(match) for match in interim.matches
                ]
                self._state.search_works = [search_work_payload(work) for work in interim.works]
                self._state.progress = AppProgress(
                    stage="search", message=message, current=len(settled_codes), total=total
                )
            await self._emit_app_state()
            await self._emit_app_progress()

        languages = _expand_search_languages(request.source_language, request.target_language)
        try:
            catalog = await self._aggregator.search_catalog(
                request.title,
                languages,
                correlation_id=correlation_id,
                on_provider_update=on_provider_update,
            )
        except Exception as exc:
            log_event(
                "search.failed",
                layer="backend",
                level="error",
                correlation_id=correlation_id,
                title=request.title,
                duration_ms=round((time.perf_counter() - started) * 1000),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            if self._active_search_id == correlation_id:
                await self._set_error(str(exc))
            raise

        payload = [search_result_payload(result) for result in catalog.results]
        matches = [search_match_payload(match) for match in catalog.matches]
        works = [search_work_payload(work) for work in catalog.works]
        # A newer search may have already replaced this one's state; still hand
        # the caller its own results, just don't clobber the newer state with them.
        if self._active_search_id == correlation_id:
            prepared_here = self._prepared_search_id == correlation_id
            async with self._lock:
                self._search_catalog = catalog
                self._state.status = "idle"
                self._state.search_results = payload
                self._state.search_matches = matches
                self._state.search_works = works
                self._state.progress = AppProgress()
                self._state.warning_message = _search_warning_message(request, catalog.warnings)
                if not prepared_here:
                    self._state.selected_feature_id = None
                    self._state.selected_source_file_id = None
                    self._state.selected_target_file_id = None
                    self._state.prepared_session = None
                    self._prepared_runtime = None
            await self._emit_app_state()
            log_event(
                "search.completed",
                layer="backend",
                correlation_id=correlation_id,
                title=request.title,
                duration_ms=round((time.perf_counter() - started) * 1000),
                results=len(payload),
                matches=len(matches),
                works=len(works),
                warnings=len(catalog.warnings),
            )
        return {
            "results": payload,
            "matches": matches,
            "works": works,
            "warnings": catalog.warnings,
        }

    async def hydrate_episode(
        self,
        *,
        work_id: str,
        title: str,
        season: int,
        episode: int,
        correlation_id: str | None = None,
    ) -> dict[str, object]:
        if self._search_catalog is None:
            raise ValueError("Search before hydrating an episode.")
        if season < 0 or episode < 1:
            raise ValueError("Episode hydration needs a valid season and episode.")

        work = next((item for item in self._search_catalog.works if item.id == work_id), None)
        query_title = title or (work.title if work is not None else self._state.title)
        if not query_title:
            raise ValueError("Episode hydration needs a title.")

        query = f"{query_title} S{season:02d}E{episode:02d}"
        languages = _expand_search_languages(
            self._state.source_language, self._state.target_language
        )
        log_event(
            "search.episode_hydrate.requested",
            layer="backend",
            correlation_id=correlation_id,
            work_id=work_id,
            title=query_title,
            season=season,
            episode=episode,
        )

        catalog = await self._aggregator.search_catalog(
            query, languages, correlation_id=correlation_id
        )
        catalogs = [catalog]
        if _should_hydrate_season_neighbors(work, season):
            season_query = f"{query_title} S{season:02d}"
            season_catalog = await self._aggregator.search_catalog(
                season_query,
                languages,
                correlation_id=correlation_id,
            )
            catalogs.append(season_catalog)

        results_by_episode = _collect_hydratable_episode_results(
            catalogs, work, query_title, season
        )
        if not results_by_episode:
            log_event(
                "search.episode_hydrate.empty",
                layer="backend",
                correlation_id=correlation_id,
                work_id=work_id,
                season=season,
                episode=episode,
            )
            return {
                "hydrated": False,
                "matchId": None,
                "results": self._state.search_results,
                "matches": self._state.search_matches,
                "works": self._state.search_works,
            }

        all_matches = [match for item in catalogs for match in item.matches]
        match_id: str | None = None
        hydrated_count = 0
        for episode_no, episode_results in sorted(results_by_episode.items()):
            hydrated_count += len(episode_results)
            hydrated_match_id = self._merge_hydrated_episode(
                work_id=work_id,
                title=query_title,
                season=season,
                episode=episode_no,
                results=episode_results,
                matches=all_matches,
            )
            if episode_no == episode:
                match_id = hydrated_match_id

        async with self._lock:
            self._state.search_results = [
                search_result_payload(result) for result in self._search_catalog.results
            ]
            self._state.search_matches = [
                search_match_payload(match) for match in self._search_catalog.matches
            ]
            self._state.search_works = [
                search_work_payload(work) for work in self._search_catalog.works
            ]
            if match_id is not None:
                self._state.selected_feature_id = match_id
                self._state.selected_source_file_id = None
                self._state.selected_target_file_id = None
                self._state.prepared_session = None
                self._prepared_runtime = None
        await self._emit_app_state()
        log_event(
            "search.episode_hydrate.completed",
            layer="backend",
            correlation_id=correlation_id,
            work_id=work_id,
            match_id=match_id,
            season=season,
            episode=episode,
            results=hydrated_count,
            hydrated_episodes=len(results_by_episode),
        )
        return {
            "hydrated": match_id is not None,
            "matchId": match_id,
            "results": self._state.search_results,
            "matches": self._state.search_matches,
            "works": self._state.search_works,
        }

    async def hydrate_season(
        self,
        *,
        work_id: str,
        title: str,
        season: int,
        correlation_id: str | None = None,
    ) -> dict[str, object]:
        if self._search_catalog is None:
            raise ValueError("Search before hydrating a season.")
        if season < 0:
            raise ValueError("Season hydration needs a valid season.")

        work = next((item for item in self._search_catalog.works if item.id == work_id), None)
        query_title = title or (work.title if work is not None else self._state.title)
        if not query_title:
            raise ValueError("Season hydration needs a title.")

        query = f"{query_title} S{season:02d}"
        languages = _expand_search_languages(
            self._state.source_language, self._state.target_language
        )
        log_event(
            "search.season_hydrate.requested",
            layer="backend",
            correlation_id=correlation_id,
            work_id=work_id,
            title=query_title,
            season=season,
        )

        catalog = await self._aggregator.search_catalog(
            query, languages, correlation_id=correlation_id
        )
        results_by_episode = _collect_hydratable_episode_results(
            [catalog], work, query_title, season
        )
        if not results_by_episode:
            log_event(
                "search.season_hydrate.empty",
                layer="backend",
                correlation_id=correlation_id,
                work_id=work_id,
                season=season,
            )
            return {
                "hydrated": False,
                "hydratedEpisodes": 0,
                "results": self._state.search_results,
                "matches": self._state.search_matches,
                "works": self._state.search_works,
            }

        hydrated_count = 0
        for episode_no, episode_results in sorted(results_by_episode.items()):
            hydrated_count += len(episode_results)
            self._merge_hydrated_episode(
                work_id=work_id,
                title=query_title,
                season=season,
                episode=episode_no,
                results=episode_results,
                matches=catalog.matches,
            )

        async with self._lock:
            self._state.search_results = [
                search_result_payload(result) for result in self._search_catalog.results
            ]
            self._state.search_matches = [
                search_match_payload(match) for match in self._search_catalog.matches
            ]
            self._state.search_works = [
                search_work_payload(work) for work in self._search_catalog.works
            ]
        await self._emit_app_state()
        log_event(
            "search.season_hydrate.completed",
            layer="backend",
            correlation_id=correlation_id,
            work_id=work_id,
            season=season,
            results=hydrated_count,
            hydrated_episodes=len(results_by_episode),
        )
        return {
            "hydrated": True,
            "hydratedEpisodes": len(results_by_episode),
            "results": self._state.search_results,
            "matches": self._state.search_matches,
            "works": self._state.search_works,
        }

    def _merge_hydrated_episode(
        self,
        *,
        work_id: str,
        title: str,
        season: int,
        episode: int,
        results: list[AggregatedSubtitleResult],
        matches: list[AggregatedTitleMatch],
    ) -> str:
        if self._search_catalog is None:
            raise ValueError("Search before hydrating an episode.")

        target_work = next(
            (work for work in self._search_catalog.works if work.id == work_id), None
        )
        existing_match = next(
            (
                match
                for match in self._search_catalog.matches
                if (
                    match.media_type == "episode"
                    and match.season == season
                    and match.episode == episode
                    and _episode_match_belongs_to_work(match, target_work, title)
                )
            ),
            None,
        )
        match_id = (
            existing_match.id
            if existing_match is not None
            else f"hydrated:{work_id}:{season}:{episode}"
        )
        existing_keys = {
            (
                result.provider,
                getattr(result.provider_result, "id", result.file_name),
                result.language,
            )
            for result in self._search_catalog.results
            if result.match_id == match_id
        }

        appended: list[AggregatedSubtitleResult] = []
        for result in results:
            key = (
                result.provider,
                getattr(result.provider_result, "id", result.file_name),
                result.language,
            )
            if key in existing_keys:
                continue
            existing_keys.add(key)
            appended.append(
                replace(
                    result,
                    result_id=result_id_for(*key),
                    match_id=match_id,
                )
            )
        match_results = [
            result for result in self._search_catalog.results if result.match_id == match_id
        ]
        if not appended:
            if match_results:
                self._search_catalog.works = [
                    self._replace_work_episode(
                        work, match_id, title, season, episode, match_results
                    )
                    if work.id == work_id
                    else work
                    for work in self._search_catalog.works
                ]
            return match_id

        providers = tuple(sorted({result.provider for result in appended}))
        provider_labels = tuple(sorted({result.provider_label for result in appended}))
        best_match = next(
            (
                match
                for match in matches
                if (
                    match.media_type == "episode"
                    and match.season == season
                    and match.episode == episode
                    and _episode_match_belongs_to_work(match, target_work, title)
                )
            ),
            None,
        )
        if existing_match is None:
            hydrated_match = AggregatedTitleMatch(
                id=match_id,
                title=best_match.title if best_match else appended[0].title,
                year=best_match.year if best_match else appended[0].year,
                imdb_id=best_match.imdb_id if best_match else appended[0].imdb_id,
                tmdb_id=best_match.tmdb_id if best_match else appended[0].tmdb_id,
                media_type="episode",
                season=season,
                episode=episode,
                parent_title=(best_match.parent_title if best_match else appended[0].parent_title)
                or title,
                subtitles_count=len(appended),
                match_score=max([result.match_score for result in appended], default=0.0),
                provider_count=len(providers),
                providers=providers,
                provider_labels=provider_labels,
            )
            self._search_catalog.matches.append(hydrated_match)
        else:
            merged_providers = tuple(sorted({*existing_match.providers, *providers}))
            merged_labels = tuple(sorted({*existing_match.provider_labels, *provider_labels}))
            self._search_catalog.matches = [
                replace(
                    match,
                    subtitles_count=match.subtitles_count + len(appended),
                    provider_count=len(merged_providers),
                    providers=merged_providers,
                    provider_labels=merged_labels,
                    match_score=max(
                        match.match_score, max(result.match_score for result in appended)
                    ),
                )
                if match.id == match_id
                else match
                for match in self._search_catalog.matches
            ]

        self._search_catalog.results.extend(appended)
        self._search_catalog.works = [
            self._replace_work_episode(
                work, match_id, title, season, episode, [*match_results, *appended]
            )
            if work.id == work_id
            else work
            for work in self._search_catalog.works
        ]
        return match_id

    def _replace_work_episode(
        self,
        work: AggregatedWork,
        match_id: str,
        title: str,
        season: int,
        episode: int,
        results: list[AggregatedSubtitleResult],
    ) -> AggregatedWork:
        providers = tuple(sorted({result.provider for result in results}))
        hydrated = AggregatedEpisode(
            season=season,
            episode=episode,
            title=results[0].title if results else "",
            match_id=match_id,
            year=results[0].year if results else work.year,
            subtitles_count=len(results),
            providers=providers,
        )
        seasons: list[AggregatedSeason] = []
        replaced = False
        for item in work.seasons:
            if item.season_number != season:
                seasons.append(item)
                continue
            episodes = [hydrated if ep.episode == episode else ep for ep in item.episodes]
            if not any(ep.episode == episode for ep in item.episodes):
                episodes.append(hydrated)
                episodes.sort(key=lambda ep: (ep.episode is None, ep.episode or 0, ep.match_id))
            replaced = True
            seasons.append(
                replace(
                    item,
                    episodes=episodes,
                    subtitles_count=sum(ep.subtitles_count for ep in episodes),
                )
            )
        if not replaced:
            seasons.append(
                AggregatedSeason(
                    season_number=season, episodes=[hydrated], subtitles_count=len(results)
                )
            )
            seasons.sort(key=lambda item: item.season_number)
        episode_keys = {
            (ep.season, ep.episode)
            for season_item in seasons
            for ep in season_item.episodes
            if ep.season is not None
            and ep.episode is not None
            and not ep.match_id.startswith("skeleton:")
        }
        return replace(
            work,
            title=work.title or title,
            seasons=seasons,
            total_episodes=len(episode_keys),
            total_subtitles=sum(season_item.subtitles_count for season_item in seasons),
        )

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
        log_event(
            "session.prepare.requested",
            layer="backend",
            mode=mode,
            match_id=feature_id,
            source_result_id=source_file_id,
            target_result_id=target_file_id,
        )
        if self._sync_task and not self._sync_task.done():
            await self._set_error("Stop the active session before preparing another one.")
            raise RuntimeError("A session is already running.")
        if mode not in {"subtitle_pair", "ocr_fallback", "auto_candidates"}:
            raise ValueError(f"Unsupported session mode: {mode}")
        if mode == "auto_candidates":
            return await self._prepare_auto_candidate_session(
                feature_id or self._state.selected_feature_id
            )
        if mode == "ocr_fallback":
            return await self._prepare_ocr_fallback_session(
                feature_id or self._state.selected_feature_id, target_file_id
            )
        if source_file_id is None:
            raise ValueError("Select a source subtitle before preparing a subtitle-pair session.")
        return await self._prepare_subtitle_pair_session(feature_id, source_file_id, target_file_id)

    async def _downloaded_source(
        self, source_file_id: str, entry: AggregatedSubtitleResult
    ) -> Path:
        """The chosen source, reusing the copy the target step already fetched."""
        inspected = self._inspected_source
        if inspected is not None and inspected[0] == source_file_id and inspected[1].exists():
            return inspected[1]
        return await self._aggregator.download(entry)

    async def inspect_source(
        self, source_file_id: str, feature_id: str | None = None
    ) -> dict[str, object]:
        """Whether the chosen source carries its own translation.

        Asked when the viewer reaches the target step, because that is the first
        moment the answer is knowable and the last moment it is useful. Provider
        metadata names one language; only the file says whether its cues carry a
        second script, so this downloads it - which the session was going to do
        anyway, so the answer costs nothing extra and nothing from a metered
        provider's daily allowance.
        """
        source_result = self._find_search_result(source_file_id)
        entry = self._catalog_result(source_file_id)
        if source_result is None or entry is None:
            raise ValueError(
                "Selected source subtitle was not found in the current search results."
            )
        path = await self._aggregator.download(entry)
        # Preparation asks for this same file moments later, and only
        # OpenSubtitles answers a second time from disk - SubDL and ASSRT fetch
        # it again. Keeping the path spares the viewer a download between
        # choosing a target and the session starting.
        self._inspected_source = (source_file_id, path)
        lines = load_subtitle_file(path)
        report = split_bilingual(lines, self._state.source_language, self._state.target_language)
        return {
            "sourceFileId": source_file_id,
            "fileName": str(source_result.get("fileName") or ""),
            "featureId": feature_id or self._feature_id_for_result(source_result),
            "carriesTranslation": report.is_bilingual,
            "totalCues": report.total_cues,
            "translatedCues": report.split_cues,
        }

    async def _prepare_subtitle_pair_session(
        self,
        feature_id: str | None,
        source_file_id: str,
        target_file_id: str | None,
    ) -> dict[str, object]:
        source_result = self._find_search_result(source_file_id)
        if source_result is None:
            raise ValueError(
                "Selected source subtitle was not found in the current search results."
            )
        own_translation = target_file_id == SOURCE_OWN_TRANSLATION
        target_result = (
            self._find_search_result(target_file_id)
            if target_file_id and not own_translation
            else None
        )
        if target_file_id is not None and not own_translation and target_result is None:
            raise ValueError(
                "Selected target subtitle was not found in the current search results."
            )
        effective_feature_id = feature_id or self._feature_id_for_result(source_result)

        async with self._lock:
            self._state.status = "preparing"
            self._state.selected_feature_id = effective_feature_id
            self._state.selected_source_file_id = source_file_id
            self._state.selected_target_file_id = target_file_id
            self._state.error_message = ""
            self._state.warning_message = ""
            self._state.progress = AppProgress(
                stage="download", message="Downloading subtitle files...", current=0, total=2
            )
        await self._emit_app_state()
        await self._emit_app_progress()

        source_entry = self._catalog_result(source_file_id)
        if source_entry is None:
            raise ValueError("Selected source subtitle could not be resolved.")
        target_entry = (
            self._catalog_result(target_file_id) if target_file_id and not own_translation else None
        )

        try:
            source_path = await self._downloaded_source(source_file_id, source_entry)
            await self._set_progress("download", "Downloaded source subtitles.", 1, 2)
            target_path: Path | None = None
            if target_entry is not None:
                target_path = await self._aggregator.download(target_entry)
            await self._set_progress("download", "Downloaded subtitle files.", 2, 2)

            source_lines = load_subtitle_file(source_path)
            target_lines = load_subtitle_file(target_path) if target_path else []

            # Split first, whatever the viewer chose. It leaves every cue's text
            # in one language, which is what the plate draws and what the model
            # is asked to translate - an unsplit bilingual cue put both scripts
            # on the plate and handed the model a string containing its own
            # answer. The translation it yields then sits underneath whatever
            # comes next: a chosen target file overwrites the cues it answers
            # and leaves the rest to the file's own words, which beat anything
            # the model would write for them and cost nothing.
            bilingual = split_bilingual(
                source_lines, self._state.source_language, self._state.target_language
            )
            # Taken before anything is paired, so it holds only what the file
            # answers by itself - the floor every candidate is measured over,
            # since each of them falls back to it alike.
            carried = [line.translated for line in source_lines]

            if target_lines and not own_translation:
                assign_target_translations(source_lines, target_lines)
            # Matched lines are translated as they appear rather than up front:
            # a local 1.8B model needs hours for a whole subtitle file. It is
            # needed only where nothing else answered - neither a target file
            # nor the source's own rows.
            used_translation = not target_lines and not bilingual.split_cues
            engine_warning = await self._start_translation_engine(required=used_translation)
        except Exception as exc:
            await self._set_error(str(exc))
            raise

        # A file that answers itself has nothing to be compared against, and
        # weighing rivals would download them for advice that cannot apply.
        alignment = (
            []
            if own_translation
            else await self._weigh_target_candidates(
                effective_feature_id, target_entry, source_lines, target_lines, carried
            )
        )
        pair = align_subtitles(source_lines, target_lines)
        session = PreparedSession(
            session_id=uuid4().hex[:8],
            title=self._state.title,
            source_language=self._state.source_language,
            target_language=self._state.target_language,
            resolved_source_language=str(
                source_result.get("language") or self._state.source_language
            ),
            source_language_mode=source_language_mode(
                self._state.source_language,
                str(source_result.get("language") or self._state.source_language),
            ),
            session_mode="subtitle_pair",
            target_match_mode=_pair_target_mode(own_translation, target_lines),
            feature_id=effective_feature_id,
            source_file_id=source_file_id,
            source_file_name=str(source_result.get("fileName") or ""),
            source_provider=str(
                source_result.get("providerLabel") or source_result.get("provider") or ""
            ),
            source_path=str(source_path),
            source_line_count=len(source_lines),
            target_file_id=SOURCE_OWN_TRANSLATION
            if own_translation
            else (
                str(target_result.get("resultId") or target_file_id)
                if target_result is not None
                else None
            ),
            target_file_name=str(source_result.get("fileName") or "")
            if own_translation
            else (str(target_result.get("fileName") or "") if target_result is not None else None),
            target_provider=str(
                target_result.get("providerLabel") or target_result.get("provider") or ""
            )
            if target_result is not None
            else None,
            target_path=str(target_path) if target_path is not None else None,
            target_line_count=bilingual.split_cues if own_translation else len(target_lines),
            translated_line_count=sum(1 for line in source_lines if line.translated),
            used_translation=used_translation,
            target_alignment=alignment,
        )

        async with self._lock:
            self._prepared_search_id = self._active_search_id
            self._prepared_runtime = PreparedRuntime(
                session_mode="subtitle_pair",
                target_lines=target_lines,
                feature_id=effective_feature_id,
                source_candidates=[
                    SourceSubtitleCandidate(
                        result_id=source_file_id,
                        file_name=str(source_result.get("fileName") or ""),
                        provider=str(
                            source_result.get("providerLabel")
                            or source_result.get("provider")
                            or ""
                        ),
                        language=str(source_result.get("language") or ""),
                        path=str(source_path),
                        pair=pair,
                    )
                ],
            )
            self._state.prepared_session = session
            self._state.status = "idle"
            self._state.progress = AppProgress(
                stage="ready", message="Session prepared.", current=1, total=1
            )
            warnings = []
            if session.source_language_mode != "exact":
                warnings.append(
                    "Using a Chinese-family source subtitle fallback because no exact source language match was available."
                )
            if engine_warning:
                warnings.append(engine_warning)
            self._state.warning_message = " ".join(warnings)
        await self._emit_app_state()
        await self._emit_app_progress()
        return asdict(session)

    async def _prepare_auto_candidate_session(self, feature_id: str | None) -> dict[str, object]:
        if feature_id is None:
            raise ValueError("Select a matched title before preparing an automatic session.")
        feature = self._find_search_match(feature_id)
        if feature is None:
            raise ValueError("Selected title was not found in the current search matches.")
        if self._search_catalog is None:
            raise ValueError("These results are out of date. Search again to pick a title.")

        source_entries = self._candidate_results_for_feature(
            feature_id,
            self._state.source_language,
            AUTO_SOURCE_CANDIDATE_LIMIT,
        )
        target_entries = self._candidate_results_for_feature(
            feature_id,
            self._state.target_language,
            AUTO_TARGET_CANDIDATE_LIMIT,
        )
        target_entry = target_entries[0] if target_entries else None
        if not source_entries:
            return await self._prepare_ocr_fallback_session(
                feature_id, target_entry.result_id if target_entry else None
            )

        total_downloads = len(source_entries) + (1 if target_entry is not None else 0)
        async with self._lock:
            self._state.status = "preparing"
            self._state.selected_feature_id = feature_id
            self._state.selected_source_file_id = None
            self._state.selected_target_file_id = target_entry.result_id if target_entry else None
            self._state.error_message = ""
            self._state.warning_message = ""
            self._state.progress = AppProgress(
                stage="download",
                message="Downloading subtitle candidates...",
                current=0,
                total=total_downloads,
            )
        await self._emit_app_state()
        await self._emit_app_progress()

        try:
            downloaded = 0
            source_candidates: list[SourceSubtitleCandidate] = []
            target_path: Path | None = None
            target_lines = []

            for entry in source_entries:
                source_path = await self._aggregator.download(entry)
                downloaded += 1
                await self._set_progress(
                    "download",
                    "Downloaded source subtitle candidates.",
                    downloaded,
                    total_downloads,
                )
                source_lines = load_subtitle_file(source_path)
                # Every candidate gets the same reading a manually chosen source
                # does: one language per cue before anything else looks at it,
                # and its own translation kept where it carries one.
                split_bilingual(
                    source_lines, self._state.source_language, self._state.target_language
                )
                source_candidates.append(
                    SourceSubtitleCandidate(
                        result_id=entry.result_id,
                        file_name=entry.file_name,
                        provider=entry.provider_label or entry.provider,
                        language=entry.language,
                        path=str(source_path),
                        pair=SubtitlePair(source_lines=source_lines),
                    )
                )

            if target_entry is not None:
                target_path = await self._aggregator.download(target_entry)
                downloaded += 1
                await self._set_progress(
                    "download", "Downloaded target subtitles.", downloaded, total_downloads
                )
                target_lines = load_subtitle_file(target_path)
                for candidate in source_candidates:
                    candidate.pair.target_lines = target_lines
                    assign_target_translations(candidate.pair.source_lines, target_lines)
            # A candidate that answered itself needs the model no more than a
            # paired target file does.
            answered = any(
                line.translated
                for candidate in source_candidates
                for line in candidate.pair.source_lines
            )
            engine_warning = await self._start_translation_engine(
                required=not target_lines and not answered
            )
        except Exception as exc:
            await self._set_error(str(exc))
            raise

        title = str(feature.get("displayLabel") or feature.get("title") or self._state.title)
        primary_source = source_entries[0]
        session = PreparedSession(
            session_id=uuid4().hex[:8],
            title=title,
            source_language=self._state.source_language,
            target_language=self._state.target_language,
            resolved_source_language=primary_source.language,
            source_language_mode=source_language_mode(
                self._state.source_language, primary_source.language
            ),
            session_mode="auto_candidates",
            target_match_mode="auto_subtitle_file" if target_lines else "auto_live_translation",
            feature_id=feature_id,
            source_file_id=None,
            source_file_name=None,
            source_summary=f"{len(source_candidates)} source candidates",
            source_provider=", ".join(
                dict.fromkeys(candidate.provider for candidate in source_candidates)
            ),
            source_path=None,
            source_line_count=sum(
                len(candidate.pair.source_lines) for candidate in source_candidates
            ),
            target_file_id=target_entry.result_id if target_entry else None,
            target_file_name=target_entry.file_name if target_entry else None,
            target_provider=(target_entry.provider_label or target_entry.provider)
            if target_entry
            else None,
            target_path=str(target_path) if target_path is not None else None,
            target_line_count=len(target_lines),
            translated_line_count=sum(
                1
                for candidate in source_candidates
                for line in candidate.pair.source_lines
                if line.translated
            ),
            used_translation=not bool(target_lines),
            source_candidate_count=len(source_candidates),
            target_candidate_count=len(target_entries),
        )

        async with self._lock:
            if str(self._state.selected_feature_id) != str(feature_id):
                logger.debug(
                    "Ignoring stale auto-prepare completion for feature_id=%s selected_feature_id=%s",
                    feature_id,
                    self._state.selected_feature_id,
                )
                raise RuntimeError(
                    "Stale auto-prepare result ignored because another title is selected."
                )
            self._prepared_search_id = self._active_search_id
            self._prepared_runtime = PreparedRuntime(
                session_mode="auto_candidates",
                target_lines=target_lines,
                feature_id=feature_id,
                source_candidates=source_candidates,
            )
            self._state.prepared_session = session
            self._state.status = "idle"
            self._state.progress = AppProgress(
                stage="ready", message="Automatic subtitle session prepared.", current=1, total=1
            )
            warnings = []
            if session.source_language_mode != "exact":
                warnings.append(
                    "Using Chinese-family source subtitle candidates because no exact source language match was available."
                )
            if target_entry is None:
                warnings.append(
                    "No target subtitle matched the requested language. The session will translate matched source lines live."
                )
            if engine_warning:
                warnings.append(engine_warning)
            self._state.warning_message = " ".join(warnings)
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
            raise ValueError(
                "Selected target subtitle was not found in the current search results."
            )
        if target_result is not None and not self._result_matches_feature(
            target_result, feature_id
        ):
            raise ValueError("Selected target subtitle does not belong to the chosen title.")

        async with self._lock:
            self._state.status = "preparing"
            self._state.selected_feature_id = feature_id
            self._state.selected_source_file_id = None
            self._state.selected_target_file_id = target_file_id
            self._state.error_message = ""
            self._state.warning_message = ""
            self._state.progress = AppProgress(
                stage="prepare", message="Preparing OCR fallback session...", current=0, total=1
            )
        await self._emit_app_state()
        await self._emit_app_progress()

        try:
            await self._start_translation_engine(required=True)

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
            target_file_id=str(target_result.get("resultId") or target_file_id)
            if target_result is not None
            else None,
            target_file_name=str(target_result.get("fileName") or "")
            if target_result is not None
            else None,
            target_provider=str(
                target_result.get("providerLabel") or target_result.get("provider") or ""
            )
            if target_result is not None
            else None,
            target_path=str(target_path) if target_path is not None else None,
            target_line_count=len(target_lines),
            used_translation=True,
        )

        async with self._lock:
            self._prepared_search_id = self._active_search_id
            self._prepared_runtime = PreparedRuntime(
                session_mode="ocr_fallback",
                target_lines=target_lines,
                feature_id=feature_id,
            )
            self._state.prepared_session = session
            self._state.status = "idle"
            self._state.progress = AppProgress(
                stage="ready", message="OCR fallback session prepared.", current=1, total=1
            )
            self._state.warning_message = "No source subtitle matched the requested language. The session will use OCR plus live AI translation."
        await self._emit_app_state()
        await self._emit_app_progress()
        return asdict(session)

    async def start_session(self, session_id: str | None = None) -> dict[str, object]:
        logger.info("Start session: session_id=%s", session_id)
        log_event("session.start.requested", layer="backend", session_id=session_id)
        if self._prepared_runtime is None or self._state.prepared_session is None:
            raise ValueError("Prepare a session before starting sync.")
        if session_id and session_id != self._state.prepared_session.session_id:
            raise ValueError("Prepared session does not match the requested session ID.")
        if self._sync_task and not self._sync_task.done():
            raise RuntimeError("A session is already running.")

        if len(self.config.capture_region) != 4 or self.config.capture_region[2] <= 0:
            raise ValueError("Select the capture region before starting sync.")

        resolution = resolve_ocr_language(self.config.ocr_language)
        if (
            resolution.warning_message
            and resolution.resolved_language == resolution.requested_language
            and "not installed" in resolution.warning_message.lower()
        ):
            raise RuntimeError(resolution.warning_message)
        async with self._lock:
            self._state.status = "running"
            self._state.error_message = ""
            self._state.warning_message = resolution.warning_message
            message = _running_message(self._prepared_runtime)
            self._state.progress = AppProgress(stage="sync", message=message, current=1, total=1)
        await self._emit_app_state()
        await self._emit_app_progress()

        self._sync_task = asyncio.create_task(
            self._run_sync_loop(self._prepared_runtime, self.config)
        )
        return {"status": self._state.status}

    async def stop_session(self) -> dict[str, object]:
        logger.info("Stop session requested")
        log_event("session.stop.requested", layer="backend")
        task = self._sync_task
        if task is None or task.done():
            async with self._lock:
                self._state.status = "idle"
                self._state.last_subtitle = ""
                self._state.progress = AppProgress()
                self._state.warning_message = ""
            await self._emit_app_state()
            await self._emit_app_event("subtitle", {"text": "", "source": MATCHED})
            return {"status": self._state.status}

        async with self._lock:
            self._state.status = "stopping"
            self._state.progress = AppProgress(
                stage="stopping", message="Stopping session...", current=0, total=1
            )
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
        await self._emit_app_event("subtitle", {"text": "", "source": MATCHED})
        return {"status": self._state.status}

    def _make_debug_broadcast(self) -> Callable[[dict[str, object]], Awaitable[None]]:
        async def cb(data: dict[str, object]) -> None:
            await self._emit_app_event("debug", {"data": data})

        return cb

    async def broadcast_overlay_subtitle(self, subtitle_text: str, source: str = MATCHED) -> None:
        """Put a line on the plate, saying whether it came from a file or the model."""
        async with self._lock:
            self._state.last_subtitle = subtitle_text
        await self._emit_app_event("subtitle", {"text": subtitle_text, "source": source})

    async def shutdown(self) -> None:
        task = self._sync_task
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _start_translation_engine(self, *, required: bool) -> str:
        """Have the engine running before the session that needs it starts.

        Called while preparing whatever the target file turned out to be. Until a
        match anchors the clock the model is the only thing that can fill the
        plate, and starting it on the first read spends that whole window
        loading; it also answers the lines the target file has none for.

        A session with a target file still plays without it, so a missing engine
        is reported and stepped over. Returns the warning to show, empty when the
        engine is up. Where nothing but the model can fill the plate the same
        failure ends preparation, because the session would show nothing at all.
        """
        try:
            await engine.ensure_ready()
        except (engine.EngineStartError, engine.EngineInstallError) as exc:
            if required:
                raise TranslationError(str(exc)) from exc
            logger.warning("Preparing without local translation: %s", exc)
            return NO_ENGINE_WARNING
        return ""

    async def _run_sync_loop(self, runtime: PreparedRuntime, config: AppConfig) -> None:
        # Debug events ride alongside the normal broadcast path so the dashboard
        # panel can inspect OCR timing without changing capture behavior.
        debug_cb = self._make_debug_broadcast() if config.debug_mode else None
        opened: list = []
        opening = asyncio.Lock()

        async def semantic_factory() -> SemanticIndex:
            return SemanticIndex(await engine.ensure_embedding_ready())

        async def translator_factory() -> LiveTranslator:
            """Open the translator once, however many reads ask for it at once.

            Every unmatched read starts its own task, and until the engine is up
            they all arrive here together. Checking `opened` without the lock
            let each of them past - measured as nine engines started in twenty
            seconds, one per waiting read, competing for the GPU.
            """
            async with opening:
                if not opened:
                    opened.append(await open_live_translator(config))
            return opened[0][1]

        try:
            if runtime.source_candidates:
                session = CandidateSession(
                    runtime.source_candidates,
                    config,
                    translator_factory,
                    semantic_factory,
                    bias_source=lambda: self.config.sync_bias_ms,
                )
            else:
                session = DirectTranslationSession(runtime.target_lines, config, translator_factory)
            await run_session_loop(
                session,
                config,
                self.broadcast_overlay_subtitle,
                debug_broadcast=debug_cb,
                region_source=lambda: tuple(self.config.capture_region),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._set_error(str(exc))
        finally:
            if opened:
                await opened[0][0].close()
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

    def _candidate_results_for_feature(
        self,
        feature_id: str,
        language: str,
        limit: int,
    ) -> list[AggregatedSubtitleResult]:
        if self._search_catalog is None:
            return []
        matches = [
            result
            for result in self._search_catalog.results
            if str(result.match_id) == str(feature_id)
            and source_result_matches_requested_language(language, result.language)
        ]
        requested = normalize_source_language(language)
        matches.sort(
            key=lambda result: (
                normalize_source_language(result.language) != requested,
                result.provider_rank,
                -result.match_score,
                -result.download_count,
                result.result_id,
            )
        )
        return matches[:limit]

    def _can_spend_a_download_on_advice(self, entry: AggregatedSubtitleResult) -> bool:
        """Whether weighing this rival is worth what the download may cost.

        OpenSubtitles meters downloads by the day. Weighing a rival is advice
        about a session the viewer can already run, so it must never be what
        uses up an allowance they need in order to watch something. The
        provider's own count of what is left decides; a provider that does not
        meter downloads reports nothing and is always weighed.

        A file already in the cache costs no allowance, but saying which ones
        those are means knowing how each provider names them, so this does not
        try - the reserve below is what a cache miss is measured against.
        """
        remaining = self._aggregator.downloads_remaining(entry.provider)
        if remaining is not None and remaining <= DOWNLOADS_KEPT_FOR_WATCHING:
            logger.debug(
                "Not weighing rival target files: %s has %d download(s) left today",
                entry.provider,
                remaining,
            )
            return False
        return True

    async def _weigh_target_candidates(
        self,
        feature_id: str | None,
        chosen_entry: AggregatedSubtitleResult | None,
        source_lines: list[SubtitleLine],
        target_lines: list[SubtitleLine],
        carried: list[str] | None = None,
    ) -> list[TargetAlignment]:
        """How the chosen target file compares with the others for this episode.

        Target files differ by more than an order of magnitude in how much of the
        source they answer, and every cue they do not answer is one the local
        model writes instead of a translator. The viewer's choice is never
        overridden: the comparison is reported and they decide what to do.

        Weighing a rival costs a download, so the whole comparison runs on a
        budget. A rival that will not arrive in time is simply not mentioned -
        preparation must not fail, or slow down noticeably, for advice.
        """
        if not target_lines or chosen_entry is None:
            return []
        chosen = alignment_report(source_lines, target_lines, carried)
        weighed = [
            TargetAlignment(
                result_id=chosen_entry.result_id,
                file_name=chosen_entry.file_name,
                unpaired_cues=chosen.unpaired_cues,
                unpaired_ms=chosen.unpaired_ms,
                chosen=True,
            )
        ]
        if feature_id is None:
            return weighed

        rivals = [
            entry
            for entry in self._candidate_results_for_feature(
                feature_id, self._state.target_language, TARGET_ALIGNMENT_SAMPLE + 1
            )
            if entry.result_id != chosen_entry.result_id
            and self._can_spend_a_download_on_advice(entry)
        ][:TARGET_ALIGNMENT_SAMPLE]

        deadline = time.monotonic() + TARGET_ALIGNMENT_BUDGET_S
        for entry in rivals:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                path = await asyncio.wait_for(self._aggregator.download(entry), remaining)
                rival_lines = load_subtitle_file(path)
            except Exception as error:
                # Deliberately without a traceback: a subtitle that fails to parse
                # can carry the offending line into one, and this log records
                # whatever the viewer is watching.
                logger.debug(
                    "Could not weigh target candidate %s: %s",
                    entry.result_id,
                    type(error).__name__,
                )
                continue
            report = alignment_report(source_lines, rival_lines, carried)
            weighed.append(
                TargetAlignment(
                    result_id=entry.result_id,
                    file_name=entry.file_name,
                    unpaired_cues=report.unpaired_cues,
                    unpaired_ms=report.unpaired_ms,
                )
            )

        weighed.sort(key=lambda item: (item.unpaired_ms, item.unpaired_cues))
        return weighed

    async def _set_progress(self, stage: str, message: str, current: int, total: int) -> None:
        async with self._lock:
            self._state.progress = AppProgress(
                stage=stage, message=message, current=current, total=total
            )
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


def _running_message(runtime: PreparedRuntime) -> str:
    """What the running session is doing, in the viewer's terms."""
    if not runtime.source_candidates:
        return "Reading the screen and translating on this device."
    if runtime.needs_live_translation:
        return "Matching downloaded subtitles, translating new lines on this device."
    return "Matching downloaded subtitles."


def _search_inputs_changed(previous: AppConfig, current: AppConfig) -> bool:
    """Whether a config change invalidates the results of the last search."""
    return (
        previous.source_language,
        previous.target_language,
        previous.opensubtitles_enabled,
        previous.opensubtitles_api_key,
        previous.subdl_enabled,
        previous.subdl_api_key,
        previous.assrt_enabled,
        previous.assrt_token,
        previous.tmdb_api_key,
        previous.tmdb_merge_enabled,
    ) != (
        current.source_language,
        current.target_language,
        current.opensubtitles_enabled,
        current.opensubtitles_api_key,
        current.subdl_enabled,
        current.subdl_api_key,
        current.assrt_enabled,
        current.assrt_token,
        current.tmdb_api_key,
        current.tmdb_merge_enabled,
    )


def _expand_search_languages(source_language: str, target_language: str) -> str:
    requested = {source_language, target_language}
    normalized = {code.strip().lower() for code in requested if code}
    if (
        "zh" in normalized
        or "zht" in normalized
        or any(code.startswith("zh") for code in normalized)
    ):
        normalized.update({"zh", "zht"})
    return ",".join(sorted(normalized))


def _should_hydrate_season_neighbors(work: AggregatedWork | None, season: int) -> bool:
    if work is None or season <= 0:
        return False
    season_item = next((item for item in work.seasons if item.season_number == season), None)
    if season_item is None:
        return False
    skeletons = [
        episode
        for episode in season_item.episodes
        if episode.episode is not None and episode.match_id.startswith("skeleton:")
    ]
    return len(skeletons) > 1


def _collect_hydratable_episode_results(
    catalogs: list[AggregatedSearchCatalog],
    work: AggregatedWork | None,
    title: str,
    season: int,
) -> dict[int, list[AggregatedSubtitleResult]]:
    results_by_episode: dict[int, list[AggregatedSubtitleResult]] = {}
    for catalog in catalogs:
        for result in catalog.results:
            if (
                result.media_type != "episode"
                or result.season != season
                or result.episode is None
                or not _episode_result_belongs_to_work(result, work, title)
            ):
                continue
            results_by_episode.setdefault(result.episode, []).append(result)
    return results_by_episode


def _episode_match_belongs_to_work(
    match: AggregatedTitleMatch,
    work: AggregatedWork | None,
    title: str,
) -> bool:
    if work is not None and match.id.startswith(f"hydrated:{work.id}:"):
        return True
    if work is None:
        return False
    if work is not None:
        if work.tmdb_id and match.tmdb_id == work.tmdb_id:
            return True
        if _same_imdb_id(work.imdb_id, match.imdb_id):
            return True
        if (work.imdb_id and match.imdb_id) or (work.tmdb_id and match.tmdb_id):
            return False
    return False


def _episode_result_belongs_to_work(
    result: AggregatedSubtitleResult,
    work: AggregatedWork | None,
    title: str,
) -> bool:
    if work is None:
        return False
    if work.tmdb_id and result.tmdb_id == work.tmdb_id:
        return True
    if _same_imdb_id(work.imdb_id, result.imdb_id):
        return True
    if (work.imdb_id and result.imdb_id) or (work.tmdb_id and result.tmdb_id):
        return False

    result_title = (result.parent_title or "").casefold()
    expected_title = (work.title or title).casefold()
    if not result_title or result_title != expected_title:
        return False
    if work.imdb_id or work.tmdb_id:
        return True
    return _year_in_work_range(result.year, work)


def _same_imdb_id(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return left.casefold().removeprefix("tt") == right.casefold().removeprefix("tt")


def _year_in_work_range(year: int | None, work: AggregatedWork) -> bool:
    if year is None or work.year is None:
        return False
    return work.year <= year <= (work.year_end or work.year)


def _search_warning_message(request: SearchRequest, warnings: list[str]) -> str:
    normalized_warnings = [warning.strip() for warning in warnings if warning and warning.strip()]
    if not normalized_warnings:
        return ""
    if not is_chinese_family(request.source_language):
        return "; ".join(normalized_warnings[:3])

    rewritten: list[str] = []
    for warning in normalized_warnings[:3]:
        if warning == "ASSRT is disabled.":
            rewritten.append("ASSRT is disabled, so Chinese subtitle coverage may be thin.")
        elif warning == "ASSRT token is not configured.":
            rewritten.append("ASSRT is not configured, so Chinese subtitle coverage may be thin.")
        else:
            rewritten.append(warning)
    return "; ".join(rewritten)
