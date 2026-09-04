import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Backdrop, TopBar } from "./components/primitives";
import { Palette, paletteWorksNavRows } from "./components/palette";
import { PrepCard, PreviewCard } from "./components/prep-card";
import { LiveView } from "./components/live-dock";
import { EmptyState } from "./components/variants/empty";
import { NoApiKey } from "./components/variants/no-key";
import { SettingsView } from "./components/variants/settings";
import { api } from "./hooks/use-api";
import { useAppWebSocket } from "./hooks/use-ws";
import { useKeybinds } from "./hooks/use-keybinds";
import { isTauri, tauri } from "./hooks/use-tauri";
import { store, useStore } from "./state/store";
import {
  applyLanguageChoice,
  derivePhase,
  episodeHydrateKey,
  mapResultsToSource,
  mapResultsToTarget,
  mapWorksToItems,
  seasonHydrateKey,
} from "./state/mappers";
import type {
  BackendConfig,
  LanguageOption,
  PaletteTabId,
  Phase,
  TitleMediaFilter,
  WorkItem,
} from "./lib/types";

const COMPACT_PALETTE_TOP = 56;

function clientEventId(prefix: string): string {
  if (crypto.randomUUID) return `${prefix}-${crypto.randomUUID()}`;
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  const random = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${prefix}-${random}`;
}

function logClientEvent(
  event: string,
  data: Record<string, unknown> = {},
  correlationId?: string,
): void {
  void api.logClient({ event, correlationId, data }).catch(() => undefined);
}

export function App(): JSX.Element {
  useAppWebSocket();
  const snapshot = useStore((s) => s.snapshot);
  const config = useStore((s) => s.config);
  const engineStatus = useStore((s) => s.engine);
  const manualView = useStore((s) => s.manualView);
  const actionError = useStore((s) => s.error);
  const query = useStore((s) => s.query);
  const tab = useStore((s) => s.tab);
  const titleMediaFilter = useStore((s) => s.titleMediaFilter);
  const selectedSeasonFilters = useStore((s) => s.selectedSeasonFilters);
  const selectedWorkId = useStore((s) => s.selectedWorkId);
  const expandedWorkId = useStore((s) => s.expandedWorkId);
  const expandedSeasonNumber = useStore((s) => s.expandedSeasonNumber);
  const selectedEpisodeMatchId = useStore((s) => s.selectedEpisodeMatchId);
  const selectedSourceId = useStore((s) => s.selectedSourceId);
  const selectedTargetId = useStore((s) => s.selectedTargetId);
  const cursorIndex = useStore((s) => s.cursorIndex);
  const hydrating = useStore((s) => s.hydrating);
  const liveLines = useStore((s) => s.liveLines);
  const languages = useStore((s) => s.languages);
  const wsConnected = useStore((s) => s.wsConnected);

  const settingsRequested = manualView === "settings";
  const showSettings = settingsRequested && !!config;
  const phase: Phase = derivePhase(snapshot, showSettings ? "home" : null);
  const [searching, setSearching] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const awaitingRegion = useRef(false);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  // Tracks visibility through the close animation so background stays inert
  // until the modal is fully hidden (not just until showSettings goes false).
  const [settingsVisible, setSettingsVisible] = useState(false);
  const settingsCloseTimerRef = useRef<number | null>(null);
  const viewportWidth = useViewportWidth();
  const inputRef = useRef<HTMLInputElement>(null);
  const backgroundRef = useRef<HTMLDivElement>(null);
  const paletteBoxRef = useRef<HTMLDivElement>(null);
  const [paletteHeight, setPaletteHeight] = useState(0);
  const searchAbort = useRef<AbortController | null>(null);
  const lastSearchedQuery = useRef<string>("");
  const hydrateInFlight = useRef<Set<string>>(new Set());
  const backgroundSearchCount = useRef(0);

  // Bootstrap: initial state + config + translation engine status
  useEffect(() => {
    let cancelled = false;
    const load = async (): Promise<void> => {
      try {
        const [snap, langs, engine] = await Promise.all([
          api.getState(),
          api.getLanguages(),
          api.getEngineStatus().catch(() => null),
        ]);
        if (cancelled) return;
        store.set({
          snapshot: snap,
          config: snap.config,
          languages: langs,
          engine,
        });
      } catch (err) {
        if (!cancelled) {
          setBootstrapError(err instanceof Error ? err.message : String(err));
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  // Derived data
  const sourceLang = (config?.languages.source ?? snapshot?.source_language ?? "en").toUpperCase();
  const targetLang = config?.languages.target ?? snapshot?.target_language ?? "zh-TW";
  const episodeMatchId = selectedEpisodeMatchId;
  const works = useMemo<WorkItem[]>(
    () => mapWorksToItems(snapshot?.search_works ?? []),
    [snapshot?.search_works],
  );
  const mediaFilteredWorks = useMemo(
    () => filterWorks(works, titleMediaFilter, [], null),
    [works, titleMediaFilter],
  );
  const seasonFilterScopeWork = useMemo(
    () => findSeasonFilterScopeWork(mediaFilteredWorks, selectedWorkId, expandedWorkId),
    [mediaFilteredWorks, selectedWorkId, expandedWorkId],
  );
  const availableSeasonNumbers = useMemo(
    () =>
      collectSeasonNumbers(
        seasonFilterScopeWork ? [seasonFilterScopeWork] : mediaFilteredWorks,
      ),
    [seasonFilterScopeWork, mediaFilteredWorks],
  );
  const filteredWorks = useMemo(
    () =>
      filterWorks(
        works,
        titleMediaFilter,
        selectedSeasonFilters,
        seasonFilterScopeWork?.id ?? null,
      ),
    [works, titleMediaFilter, selectedSeasonFilters, seasonFilterScopeWork?.id],
  );
  const sources = useMemo(
    () =>
      mapResultsToSource(
        snapshot?.search_results ?? [],
        episodeMatchId,
        snapshot?.source_language ?? "en",
      ),
    [snapshot?.search_results, episodeMatchId, snapshot?.source_language],
  );
  const targets = useMemo(
    () =>
      mapResultsToTarget(
        snapshot?.search_results ?? [],
        episodeMatchId,
        snapshot?.target_language ?? "zh",
      ),
    [snapshot?.search_results, episodeMatchId, snapshot?.target_language],
  );

  // Selecting another episode leaves the old session prepared until the new one
  // lands, so Start sync must not fire the episode the user just moved off.
  const preparingReplacement =
    !!selectedEpisodeMatchId &&
    snapshot?.prepared_session != null &&
    snapshot.prepared_session.feature_id !== selectedEpisodeMatchId;

  useEffect(() => {
    if (selectedSeasonFilters.length === 0) return;
    const available = new Set(availableSeasonNumbers);
    const valid = selectedSeasonFilters.filter((season) => available.has(season));
    if (valid.length !== selectedSeasonFilters.length) {
      store.set({ selectedSeasonFilters: valid, cursorIndex: -1 });
    }
  }, [availableSeasonNumbers, selectedSeasonFilters]);

  const titleNavRows = useMemo(
    () => paletteWorksNavRows(filteredWorks, expandedWorkId, expandedSeasonNumber),
    [filteredWorks, expandedWorkId, expandedSeasonNumber],
  );
  const titleWorkRowIndices = useMemo(
    () =>
      titleNavRows.flatMap((row, index) =>
        row.kind === "work" ? [index] : [],
      ),
    [titleNavRows],
  );

  const titleListLength = titleNavRows.length;
  const titleGridColumns = filteredWorks.length > 0 && viewportWidth >= 900 ? 2 : 1;
  const activeListLength =
    tab === "titles"
      ? titleListLength
      : tab === "source"
        ? sources.length
        : targets.length;

  // Enter live/exit live Tauri side-effects.
  // Only call exitLiveMode when transitioning OUT of live. Calling it on
  // every phase change used to re-center the window repeatedly.
  const prevPhase = useRef<Phase | null>(null);
  useEffect(() => {
    const previous = prevPhase.current;
    if (phase === "live") {
      void tauri.enterLiveMode();
    } else if (previous === "live") {
      void tauri.exitLiveMode();
    }
    prevPhase.current = phase;
  }, [phase]);

  useEffect(() => {
    if (showSettings) {
      if (settingsCloseTimerRef.current !== null) {
        window.clearTimeout(settingsCloseTimerRef.current);
        settingsCloseTimerRef.current = null;
      }
      setSettingsVisible(true);
      return;
    }
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    settingsCloseTimerRef.current = window.setTimeout(() => {
      setSettingsVisible(false);
      settingsCloseTimerRef.current = null;
    }, reducedMotion ? 0 : 160);
  }, [showSettings]);

  useEffect(() => {
    return () => {
      if (settingsCloseTimerRef.current !== null) {
        window.clearTimeout(settingsCloseTimerRef.current);
      }
    };
  }, []);

  // --- Actions ---

  const focusPalette = useCallback(() => {
    inputRef.current?.focus();
  }, []);

  const runSearch = useCallback(async (title: string) => {
    if (!title.trim()) return;
    const trimmedTitle = title.trim();
    const correlationId = clientEventId("search");
    lastSearchedQuery.current = trimmedTitle;
    searchAbort.current?.abort();
    const ctrl = new AbortController();
    searchAbort.current = ctrl;
    setSearching(true);
    logClientEvent("ui.search.submitted", {
      title: trimmedTitle,
      sourceLanguage: config?.languages.source ?? snapshot?.source_language,
      targetLanguage: config?.languages.target ?? snapshot?.target_language,
    }, correlationId);
    // Hydration keys name rows in the catalog this search replaces, and the
    // aggregator reuses ordinal work ids, so stale keys could mark a row of the
    // new catalog busy.
    hydrateInFlight.current.clear();
    store.set({
      error: null,
      cursorIndex: -1,
      selectedWorkId: null,
      expandedWorkId: null,
      expandedSeasonNumber: null,
      selectedEpisodeMatchId: null,
      selectedSourceId: null,
      selectedTargetId: null,
      hydrating: [],
    });
    try {
      const res = await api.search(
        trimmedTitle,
        config?.languages.source,
        config?.languages.target,
        correlationId,
      );
      const fresh = await api.getState();
      store.set({ snapshot: fresh, config: fresh.config });
      logClientEvent("ui.search.completed", {
        results: res.results.length,
        matches: res.matches.length,
        works: res.works.length,
        warnings: res.warnings.length,
      }, correlationId);
    } catch (err) {
      store.set({ error: err instanceof Error ? err.message : String(err) });
      logClientEvent("ui.search.failed", {
        error: err instanceof Error ? err.message : String(err),
      }, correlationId);
    } finally {
      if (searchAbort.current === ctrl) {
        searchAbort.current = null;
        if (backgroundSearchCount.current === 0) {
          setSearching(false);
        }
      }
    }
  }, [config?.languages.source, config?.languages.target, snapshot?.source_language, snapshot?.target_language]);

  const onQueryChange = useCallback((v: string) => {
    store.set({ query: v, cursorIndex: -1 });
  }, []);

  const retrySearch = useCallback(() => {
    const previous = lastSearchedQuery.current || store.get().query.trim();
    if (previous) void runSearch(previous);
  }, [runSearch]);

  const dismissError = useCallback(() => {
    store.set({ error: null });
  }, []);

  const cursorForTab = useCallback(
    (t: PaletteTabId): number => {
      if (t === "titles") {
        if (episodeMatchId) {
          const i = titleNavRows.findIndex(
            (row) => row.kind === "episode" && row.episodeMatchId === episodeMatchId,
          );
          if (i >= 0) return i;
        }
        if (selectedWorkId) {
          const i = titleNavRows.findIndex(
            (row) => row.kind === "work" && row.workId === selectedWorkId,
          );
          if (i >= 0) return i;
        }
        return -1;
      }
      if (t === "source" && selectedSourceId) {
        const i = sources.findIndex((x) => x.id === selectedSourceId);
        return i >= 0 ? i : -1;
      }
      if (t === "target" && selectedTargetId) {
        const i = targets.findIndex((x) => x.id === selectedTargetId);
        return i >= 0 ? i : -1;
      }
      return -1;
    },
    [titleNavRows, sources, targets, episodeMatchId, selectedWorkId, selectedSourceId, selectedTargetId],
  );

  const onTabChange = useCallback(
    (t: PaletteTabId) => {
      logClientEvent("ui.palette.tab_changed", { tab: t });
      store.set({ tab: t, cursorIndex: cursorForTab(t) });
    },
    [cursorForTab],
  );

  // Selecting is not committing: preparing downloads subtitle files and rebuilds
  // the screen, so it waits for the source and target the user picks next.
  const selectTitle = useCallback((workId: string, matchId: string) => {
    logClientEvent("ui.title.selected", { workId, matchId });
    store.set({
      selectedWorkId: workId,
      selectedEpisodeMatchId: matchId,
      selectedSourceId: null,
      selectedTargetId: null,
      query: "",
      cursorIndex: -1,
    });
  }, []);

  const beginBackgroundSearch = useCallback(() => {
    backgroundSearchCount.current += 1;
    setSearching(true);
  }, []);

  const endBackgroundSearch = useCallback(() => {
    backgroundSearchCount.current = Math.max(0, backgroundSearchCount.current - 1);
    if (backgroundSearchCount.current === 0 && searchAbort.current === null) {
      setSearching(false);
    }
  }, []);

  /** Claims a lookup, or returns false when the same one is already running. */
  const beginHydrate = useCallback(
    (key: string): boolean => {
      if (hydrateInFlight.current.has(key)) return false;
      hydrateInFlight.current.add(key);
      store.set({ hydrating: [...hydrateInFlight.current] });
      beginBackgroundSearch();
      return true;
    },
    [beginBackgroundSearch],
  );

  const endHydrate = useCallback(
    (key: string): void => {
      hydrateInFlight.current.delete(key);
      store.set({ hydrating: [...hydrateInFlight.current] });
      endBackgroundSearch();
    },
    [endBackgroundSearch],
  );

  const onToggleExpandWork = useCallback(
    (id: string) => {
      const work = filteredWorks.find((w) => w.id === id);
      if (!work) return;
      if (!work.expandable) {
        if (work.primaryMatchId) selectTitle(id, work.primaryMatchId);
        return;
      }
      store.set((s) => {
        const nextExpanded = s.expandedWorkId === id ? null : id;
        return {
          selectedWorkId: id,
          expandedWorkId: nextExpanded,
          expandedSeasonNumber: null,
          cursorIndex: -1,
        };
      });
    },
    [filteredWorks, selectTitle],
  );

  const hydrateSeasonIfNeeded = useCallback(async (workId: string, seasonNumber: number) => {
    const viewWork = works.find((item) => item.id === workId);
    const season = viewWork?.seasons.find((item) => item.seasonNumber === seasonNumber);
    if (!viewWork || !season) return;
    const hasSkeleton = season.episodes.some((episode) =>
      episode.matchId.startsWith("skeleton:") && episode.episode != null,
    );
    if (!hasSkeleton) return;
    const key = seasonHydrateKey(workId, seasonNumber);
    if (!beginHydrate(key)) return;
    const correlationId = clientEventId("season-hydrate");
    logClientEvent("ui.season.hydrate_requested", { workId, season: seasonNumber }, correlationId);
    try {
      const hydrated = await api.hydrateSeason(workId, viewWork.title, seasonNumber, correlationId);
      const fresh = await api.getState();
      store.set({ snapshot: fresh, config: fresh.config });
      logClientEvent("ui.season.hydrate_completed", {
        workId,
        season: seasonNumber,
        hydrated: hydrated.hydrated,
        hydratedEpisodes: hydrated.hydratedEpisodes,
      }, correlationId);
    } catch (err) {
      store.set({ error: err instanceof Error ? err.message : String(err) });
      logClientEvent("ui.season.hydrate_failed", {
        workId,
        season: seasonNumber,
        error: err instanceof Error ? err.message : String(err),
      }, correlationId);
    } finally {
      endHydrate(key);
    }
  }, [beginHydrate, endHydrate, works]);

  const onToggleExpandSeason = useCallback(
    (workId: string, seasonNumber: number) => {
      const state = store.get();
      const opening = !(state.expandedWorkId === workId && state.expandedSeasonNumber === seasonNumber);
      store.set((s) => {
        const sameWork = s.expandedWorkId === workId;
        const toggle = sameWork && s.expandedSeasonNumber === seasonNumber;
        return {
          selectedWorkId: workId,
          expandedWorkId: workId,
          expandedSeasonNumber: toggle ? null : seasonNumber,
          cursorIndex: -1,
        };
      });
      if (opening) void hydrateSeasonIfNeeded(workId, seasonNumber);
    },
    [hydrateSeasonIfNeeded],
  );

  const onPickWork = useCallback(
    (id: string) => {
      const work = filteredWorks.find((w) => w.id === id);
      if (!work) return;
      if (work.expandable) {
        onToggleExpandWork(id);
        return;
      }
      if (work.primaryMatchId) selectTitle(id, work.primaryMatchId);
    },
    [filteredWorks, onToggleExpandWork, selectTitle],
  );

  const onTitleMediaFilterChange = useCallback((filter: TitleMediaFilter) => {
    store.set({
      titleMediaFilter: filter,
      selectedSeasonFilters: [],
      cursorIndex: -1,
      expandedWorkId: null,
      expandedSeasonNumber: null,
    });
  }, []);

  const onToggleSeasonFilter = useCallback((seasonNumber: number) => {
    store.set((s) => {
      const active = s.selectedSeasonFilters.includes(seasonNumber);
      const next = active
        ? s.selectedSeasonFilters.filter((n) => n !== seasonNumber)
        : [...s.selectedSeasonFilters, seasonNumber].sort((a, b) => a - b);
      return {
        selectedSeasonFilters: next,
        cursorIndex: -1,
        expandedSeasonNumber: null,
      };
    });
  }, []);

  const onClearSeasonFilters = useCallback(() => {
    store.set({ selectedSeasonFilters: [], cursorIndex: -1, expandedSeasonNumber: null });
  }, []);

  const onPickEpisode = useCallback(
    (workId: string, matchId: string) => selectTitle(workId, matchId),
    [selectTitle],
  );

  const onHydrateEpisode = useCallback(async (workId: string, season: number, episode: number) => {
    const work = works.find((item) => item.id === workId);
    if (!work) return;
    const key = episodeHydrateKey(workId, season, episode);
    if (!beginHydrate(key)) return;
    const correlationId = clientEventId("hydrate");
    logClientEvent("ui.episode.hydrate_requested", { workId, season, episode }, correlationId);
    store.set({ selectedWorkId: workId, expandedWorkId: workId, expandedSeasonNumber: season, cursorIndex: -1 });
    try {
      const hydrated = await api.hydrateEpisode(workId, work.title, season, episode, correlationId);
      const fresh = await api.getState();
      store.set({ snapshot: fresh, config: fresh.config });
      if (hydrated.matchId) {
        selectTitle(workId, hydrated.matchId);
      }
      logClientEvent("ui.episode.hydrate_completed", {
        workId,
        season,
        episode,
        hydrated: hydrated.hydrated,
        matchId: hydrated.matchId,
      }, correlationId);
    } catch (err) {
      store.set({ error: err instanceof Error ? err.message : String(err) });
      logClientEvent("ui.episode.hydrate_failed", {
        workId,
        season,
        episode,
        error: err instanceof Error ? err.message : String(err),
      }, correlationId);
    } finally {
      endHydrate(key);
    }
  }, [beginHydrate, selectTitle, endHydrate, works]);

  const onPickSource = useCallback((id: string) => {
    logClientEvent("ui.source.selected", { resultId: id });
    store.set({ selectedSourceId: id, tab: "target", cursorIndex: -1 });
  }, []);

  const onPickTarget = useCallback(async (id: string) => {
    const correlationId = clientEventId("prepare");
    store.set({ selectedTargetId: id, tab: "titles", cursorIndex: -1 });
    const currentEpisode = store.get().selectedEpisodeMatchId;
    const currentSource = store.get().selectedSourceId;
    if (!currentEpisode || !currentSource) return;
    setPreparing(true);
    // Backend accepts only "subtitle_pair" | "ocr_fallback". Local AI
    // translation is triggered by subtitle_pair with no targetResultId —
    // the controller falls back to Foundry via target_match_mode.
    const mode: "subtitle_pair" | "ocr_fallback" =
      id === "__ocr__" ? "ocr_fallback" : "subtitle_pair";
    const targetResultId =
      id === "__local__" || id === "__ocr__" ? null : id;
    logClientEvent("ui.target.selected", {
      matchId: currentEpisode,
      sourceResultId: currentSource,
      targetResultId,
      mode,
    }, correlationId);
    try {
      await api.prepareSession({
        mode,
        matchId: currentEpisode,
        sourceResultId: currentSource,
        targetResultId,
      });
      const fresh = await api.getState();
      store.set({ snapshot: fresh, config: fresh.config });
      logClientEvent("ui.session.prepare_completed", { mode }, correlationId);
    } catch (err) {
      store.set({ error: err instanceof Error ? err.message : String(err) });
      logClientEvent("ui.session.prepare_failed", {
        error: err instanceof Error ? err.message : String(err),
      }, correlationId);
    } finally {
      setPreparing(false);
    }
  }, []);

  const startSync = useCallback(async () => {
    const correlationId = clientEventId("start");
    logClientEvent("ui.session.start_clicked", {
      sessionId: store.get().snapshot?.prepared_session?.session_id,
    }, correlationId);
    try {
      await api.startSession();
      const fresh = await api.getState();
      store.set({ snapshot: fresh, config: fresh.config });
      logClientEvent("ui.session.start_completed", {}, correlationId);
    } catch (err) {
      store.set({ error: err instanceof Error ? err.message : String(err) });
      logClientEvent("ui.session.start_failed", {
        error: err instanceof Error ? err.message : String(err),
      }, correlationId);
    }
  }, []);

  // The region names where the player draws its subtitles. Players rarely sit in
  // the same place twice, so starting always asks for it rather than trusting
  // whatever the last session saved.
  const startWithRegion = useCallback(async () => {
    if (!isTauri()) {
      // No desktop shell, so no selector window: the saved region is all there is.
      await startSync();
      return;
    }
    logClientEvent("ui.session.region_requested");
    awaitingRegion.current = true;
    await tauri.openAreaSelector();
  }, [startSync]);

  useEffect(() => {
    let disposed = false;
    const unlisteners: Array<() => void> = [];
    const attach = async (event: string, handler: () => void): Promise<void> => {
      let unlisten: (() => void) | null = null;
      try {
        unlisten = await tauri.listen(event, handler);
      } catch (err) {
        logClientEvent("ui.shell.listen_failed", { event, error: String(err) });
        return;
      }
      if (!unlisten) return;
      if (disposed) unlisten();
      else unlisteners.push(unlisten);
    };
    void attach("capture-region-selected", () => {
      if (!awaitingRegion.current) return;
      awaitingRegion.current = false;
      void startSync();
    });
    void attach("capture-region-cancelled", () => {
      if (!awaitingRegion.current) return;
      awaitingRegion.current = false;
      logClientEvent("ui.session.region_cancelled");
    });
    return () => {
      disposed = true;
      unlisteners.forEach((unlisten) => unlisten());
    };
  }, [startSync]);

  const onChangeLang = useCallback(async (type: "source" | "target", code: string) => {
    const current = store.get().config;
    if (!current) return;
    const languages = applyLanguageChoice(current.languages, type, code);
    const next: BackendConfig = { ...current, languages };
    logClientEvent("ui.language.changed", {
      type,
      code,
      source: languages.source,
      target: languages.target,
    });
    try {
      const saved = await api.putConfig(next);
      store.set({ config: saved });
      store.resetSelection();
      // Languages are part of the query, so the previous results no longer
      // describe what was asked for. Ask again rather than leaving stale titles.
      const previousQuery = lastSearchedQuery.current;
      if (previousQuery) {
        await runSearch(previousQuery);
      }
    } catch (err) {
      store.set({ error: err instanceof Error ? err.message : String(err) });
    }
  }, [runSearch]);

  const clearSession = useCallback(async () => {
    const correlationId = clientEventId("stop");
    logClientEvent("ui.session.stop_clicked", {}, correlationId);
    try {
      await api.stopSession();
    } catch {
      // stop can 409 if not running — ignore
    }
    try {
      const fresh = await api.getState();
      store.set({ snapshot: fresh, config: fresh.config });
    } catch {
      // ignore
    }
    store.resetSelection();
    logClientEvent("ui.session.stop_completed", {}, correlationId);
  }, []);

  const refreshEngine = useCallback(async (): Promise<void> => {
    const engine = await api.getEngineStatus().catch(() => null);
    if (engine) store.set({ engine });
  }, []);

  const installEngine = useCallback(async (): Promise<void> => {
    const engine = await api.installEngine().catch(() => null);
    if (engine) store.set({ engine });
  }, []);

  // The engine installs in the background and starts with the first session, so
  // the badge has to keep asking rather than trust the bootstrap snapshot.
  useEffect(() => {
    const busy = engineStatus?.phase === "installing";
    const period = busy ? 1000 : 15000;
    const timer = window.setInterval(() => void refreshEngine(), period);
    return () => window.clearInterval(timer);
  }, [engineStatus?.phase, refreshEngine]);

  const openSettings = useCallback(() => {
    if (store.get().config) {
      logClientEvent("ui.settings.opened");
      store.set({ manualView: "settings" });
    }
  }, []);

  const closeSettings = useCallback(() => {
    logClientEvent("ui.settings.closed");
    store.set({ manualView: null });
  }, []);

  const onSelect = useCallback(() => {
    const searchable = tab === "titles" || !episodeMatchId;
    if (searchable && query.trim() && query.trim() !== lastSearchedQuery.current) {
      void runSearch(query.trim());
      return;
    }
    if (searchable && activeListLength === 0 && query.trim()) {
      void runSearch(query.trim());
      return;
    }
    if (activeListLength === 0) return;
    const index = Math.max(0, Math.min(cursorIndex, activeListLength - 1));
    if (tab === "titles") {
      const row = titleNavRows[index];
      if (!row) return;
      if (row.kind === "work") onPickWork(row.workId);
      else if (row.kind === "season" && row.seasonNumber != null) {
        onToggleExpandSeason(row.workId, row.seasonNumber);
      } else if (row.kind === "episode" && row.episodeMatchId) {
        onPickEpisode(row.workId, row.episodeMatchId);
      } else if (row.kind === "skeleton_episode" && row.seasonNumber != null && row.episodeNumber != null) {
        void onHydrateEpisode(row.workId, row.seasonNumber, row.episodeNumber);
      }
      return;
    }
    if (tab === "source") {
      const item = sources[index];
      if (item) onPickSource(item.id);
      return;
    }
    if (tab === "target") {
      const item = targets[index];
      if (item) void onPickTarget(item.id);
    }
  }, [
    activeListLength,
    cursorIndex,
    onHydrateEpisode,
    onPickEpisode,
    onPickSource,
    onPickTarget,
    onPickWork,
    onToggleExpandSeason,
    query,
    runSearch,
    sources,
    tab,
    targets,
    titleNavRows,
  ]);

  const onPrimaryConfirm = useCallback(() => {
    // Until an episode is picked the source and target lists have nothing to
    // filter, so whatever is typed is a title to search for.
    if (phase === "home" && (tab === "titles" || !episodeMatchId) && query.trim()) {
      void runSearch(query.trim());
      return;
    }
    if (preparing) return;
    if (phase === "prep" && !preparingReplacement) {
      void startWithRegion();
      return;
    }
    if (!episodeMatchId) return;
    // Not ready to start yet, so send the user to whichever pick is still open.
    store.set({ tab: selectedSourceId ? "target" : "source", cursorIndex: -1 });
  }, [phase, tab, query, runSearch, startWithRegion, preparing, preparingReplacement, episodeMatchId, selectedSourceId]);

  const onMoveCursor = useCallback(
    (dir: "up" | "down" | "left" | "right") => {
      store.set((s) => {
        if ((dir === "left" || dir === "right") && s.tab !== "titles") {
          const order: PaletteTabId[] = ["titles", "source", "target"];
          const idx = order.indexOf(s.tab);
          const next = order[(idx + (dir === "right" ? 1 : -1) + order.length) % order.length];
          return { tab: next, cursorIndex: cursorForTab(next) };
        }
        const list =
          s.tab === "titles"
            ? titleListLength
            : s.tab === "source"
              ? sources.length
              : targets.length;
        if (list === 0) return {};
        if (s.cursorIndex === -1) {
          return { cursorIndex: dir === "up" || dir === "left" ? list - 1 : 0 };
        }
        const titleRow = s.tab === "titles" && s.cursorIndex >= 0
          ? titleNavRows[s.cursorIndex]
          : null;
        if (s.tab === "titles" && titleGridColumns > 1 && titleRow?.kind === "work") {
          const workPosition = titleWorkRowIndices.indexOf(s.cursorIndex);
          if (workPosition === -1) return {};
          const delta =
            dir === "down" ? titleGridColumns
              : dir === "up" ? -titleGridColumns
                : dir === "right" ? 1
                  : -1;
          const nextWorkPosition = Math.max(
            0,
            Math.min(titleWorkRowIndices.length - 1, workPosition + delta),
          );
          return { cursorIndex: titleWorkRowIndices[nextWorkPosition] };
        }
        const step = dir === "up" || dir === "left" ? -1 : 1;
        const next = (s.cursorIndex + step + list) % list;
        return { cursorIndex: next };
      });
    },
    [titleListLength, sources.length, targets.length, titleGridColumns, titleNavRows, titleWorkRowIndices, cursorForTab],
  );

  const onCycleTab = useCallback((dir: 1 | -1) => {
    const order: PaletteTabId[] = ["titles", "source", "target"];
    store.set((s) => {
      const idx = order.indexOf(s.tab);
      const next = order[(idx + dir + order.length) % order.length];
      return { tab: next, cursorIndex: cursorForTab(next) };
    });
  }, [cursorForTab]);

  useKeybinds({
    onFocusPalette: () => {
      if (!store.get().manualView) focusPalette();
    },
    onCycleTab: (dir) => {
      if (!store.get().manualView) onCycleTab(dir);
    },
    onMoveCursor: (dir) => {
      if (!store.get().manualView) onMoveCursor(dir);
    },
    onPrimaryConfirm: () => {
      if (!store.get().manualView) void onPrimaryConfirm();
    },
    onSelect: () => {
      if (!store.get().manualView) onSelect();
    },
    onOpenSettings: openSettings,
    onClearSession: () => {
      if (!store.get().manualView) void clearSession();
    },
  });

  // --- Render ---

  const noKey = shouldShowNoKey(config);
  const isEmpty = isFirstLaunch(config);
  const sourceNotices = useMemo(() => buildSourceNotices(config, snapshot?.warning_message ?? ""), [
    config,
    snapshot?.warning_message,
  ]);

  // One place for both: an action that failed in the studio and a failure the
  // backend is reporting. Neither had anywhere to appear before.
  const paletteError = actionError ?? (snapshot?.error_message || null);

  const isCompact = phase === "prep" || phase === "live";
  const isIdle =
    phase === "home" &&
    filteredWorks.length === 0 &&
    sources.length === 0;

  const selectedWork = works.find((w) => w.id === selectedWorkId) ?? null;
  const prepTitleLabel = selectedWork?.title ?? null;
  const prepRuntimeLabel = selectedWork
    ? selectedWork.totalSubtitles > 0
      ? `${selectedWork.totalSubtitles.toLocaleString()} subs`
      : selectedWork.type
    : "—";
  const palettePhase = settingsVisible ? "settings" : phase;

  // The palette's height moves with its filter rows and result count, so the
  // cards below it are placed from a measurement rather than a fixed offset.
  useEffect(() => {
    const box = paletteBoxRef.current;
    if (!box) return;
    const measure = (): void => setPaletteHeight(box.offsetHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    return () => observer.disconnect();
  }, [phase]);

  useEffect(() => {
    const background = backgroundRef.current as (HTMLDivElement & { inert?: boolean }) | null;
    if (!background) return;
    if (settingsVisible) {
      background.setAttribute("inert", "");
    } else {
      background.removeAttribute("inert");
    }
  }, [settingsVisible]);

  return (
    <div
      style={{
        position: "relative",
        width: "100vw",
        height: "100vh",
        // `clip`, not `hidden`: the decorative glows extend past the right edge,
        // and `hidden` would leave a scrollable box with no scrollbar — focus
        // inside it then scrolls the whole app sideways with no way back.
        overflow: "clip",
      }}
    >
      <Backdrop />
      <div
        ref={backgroundRef}
        aria-hidden={settingsVisible}
        style={{
          position: "absolute",
          inset: 0,
          pointerEvents: settingsVisible ? "none" : "auto",
        }}
      >
        {phase !== "live" && (
          <TopBar
            phase={phase}
            wsConnected={wsConnected}
            engineStatus={engineStatus}
            sourcesCount={countEnabledSources(config)}
            onOpenSettings={openSettings}
            onClearSession={
              selectedEpisodeMatchId || snapshot?.prepared_session
                ? () => void clearSession()
                : undefined
            }
          />
        )}
        {phase !== "live" && sourceNotices.length > 0 && (
          <SourceHealthStrip
            notices={sourceNotices}
            compact={isCompact}
            onOpenSettings={openSettings}
          />
        )}
        {/* Only while the palette is centred: the full-width palette covers this
            corner, and the persistent strip already carries the same warning. */}
        {!isCompact && (searching || snapshot?.warning_message) && sourceNotices.length > 0 && (
          <SearchNoticePanel
            searching={searching}
            notices={sourceNotices}
            onOpenSettings={openSettings}
          />
        )}

        {noKey && phase === "home" && !query && (
          <NoApiKey onOpenSettings={openSettings} />
        )}

        {!noKey && isEmpty && phase === "home" && !query && (
          <EmptyState
            sourceLabel={languageLabel(config?.languages.source)}
            targetLabel={languageLabel(config?.languages.target)}
            onOpenPalette={focusPalette}
          />
        )}

        {phase !== "live" && (
        <div
          ref={paletteBoxRef}
          style={{
            position: "absolute",
            top: isCompact ? COMPACT_PALETTE_TOP : isIdle ? 210 : 88,
            // Centred in every phase so only the width animates. Swapping the
            // horizontal anchor instead would snap `left` while `transform` was
            // still easing, throwing the palette off the side of the screen.
            left: "50%",
            transform: "translateX(-50%)",
            width: isCompact
              ? "calc(100vw - 40px)"
              : "min(920px, calc(100vw - 28px))",
            // Above the search notice, which is advisory and would otherwise
            // cover the language dropdown that opens under the chips.
            zIndex: 8,
            transition:
              "top 520ms cubic-bezier(.22, 1.3, .36, 1), width 280ms cubic-bezier(.2,.7,.3,1)",
          }}
        >
          {!isCompact && !noKey && !isEmpty && (
            <div style={{ textAlign: "center", marginBottom: 26 }}>
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  letterSpacing: 3.2,
                  color: "var(--text-label)",
                  textTransform: "uppercase",
                }}
              >
                Meowcal Studio
              </div>
              <h1
                className="display-serif"
                style={{
                  margin: "10px 0 0",
                  fontSize: 52,
                  fontWeight: 500,
                  letterSpacing: -1.2,
                  lineHeight: 1.1,
                  color: "var(--text-heading)",
                }}
              >
                What are you watching?
              </h1>
            </div>
          )}
          {!noKey && !isEmpty && (
            <Palette
              phase={palettePhase}
              compact={isCompact}
              query={query}
              onQueryChange={onQueryChange}
              tab={tab}
              onTabChange={onTabChange}
              works={filteredWorks}
              totalWorksCount={works.length}
              titleMediaFilter={titleMediaFilter}
              selectedSeasonFilters={selectedSeasonFilters}
              availableSeasonNumbers={availableSeasonNumbers}
              onTitleMediaFilterChange={onTitleMediaFilterChange}
              onToggleSeasonFilter={onToggleSeasonFilter}
              onClearSeasonFilters={onClearSeasonFilters}
              sources={sources}
              targets={targets}
              selectedWorkId={selectedWorkId}
              expandedWorkId={expandedWorkId}
              expandedSeasonNumber={expandedSeasonNumber}
              selectedEpisodeMatchId={selectedEpisodeMatchId}
              selectedSourceId={selectedSourceId}
              selectedTargetId={selectedTargetId}
              cursorIndex={cursorIndex}
              onToggleExpandWork={onToggleExpandWork}
              onToggleExpandSeason={onToggleExpandSeason}
              onPickWork={onPickWork}
              onPickEpisode={onPickEpisode}
              onHydrateEpisode={(workId, season, episode) => void onHydrateEpisode(workId, season, episode)}
              onPickSource={onPickSource}
              onPickTarget={(id) => void onPickTarget(id)}
              onPrimary={() => void onPrimaryConfirm()}
              inputRef={inputRef}
              sourceLang={sourceLang}
              targetLang={targetLang}
              searching={searching}
              hydrating={hydrating}
              errorMessage={paletteError}
              onRetrySearch={lastSearchedQuery.current || query.trim() ? retrySearch : null}
              onDismissError={dismissError}
              preparing={preparing}
              preparingReplacement={preparingReplacement}
              langOptions={(languages?.sourceTarget ?? []) as LanguageOption[]}
              onChangeLang={(type, code) => void onChangeLang(type, code)}
            />
          )}
        </div>
        )}

        {phase === "prep" && (
          <div
            style={{
              position: "absolute",
              top: COMPACT_PALETTE_TOP + paletteHeight + 16,
              left: 20,
              right: 20,
              bottom: 20,
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 16,
            }}
          >
            <PrepCard
              titleLabel={prepTitleLabel}
              runtimeLabel={prepRuntimeLabel}
              source={sources.find((s) => s.id === selectedSourceId) ?? null}
              target={targets.find((t) => t.id === selectedTargetId) ?? null}
              prepared={snapshot?.prepared_session ?? null}
            />
            <PreviewCard line={liveLines[liveLines.length - 1] ?? null} />
          </div>
        )}

        {phase === "live" && (
          <LiveView
            prev={liveLines[liveLines.length - 2] ?? null}
            current={liveLines[liveLines.length - 1] ?? null}
            onStop={() => void clearSession()}
            onSelectRegion={() => void tauri.openAreaSelector()}
            onOpenSettings={openSettings}
          />
        )}
      </div>

      {config && (
        <SettingsView
          initialConfig={config}
          onClose={closeSettings}
          open={showSettings}
          engine={engineStatus}
          onInstallEngine={() => void installEngine()}
        />
      )}

      {bootstrapError && (
        <div
          style={{
            position: "absolute",
            bottom: 16,
            left: 16,
            right: 16,
            padding: "12px 16px",
            borderRadius: 10,
            background: "var(--danger-soft)",
            border: "1px solid var(--danger-ring)",
            color: "var(--danger-text)",
            fontSize: 13,
          }}
        >
          Bootstrap error: {bootstrapError}
        </div>
      )}
    </div>
  );
}

interface SourceNotice {
  id: string;
  label: string;
  detail: string;
  tone: "warn" | "info";
}

function SourceHealthStrip({
  notices,
  compact,
  onOpenSettings,
}: {
  notices: SourceNotice[];
  compact: boolean;
  onOpenSettings: () => void;
}): JSX.Element {
  return (
    <div className="source-health-strip" data-compact={compact} aria-live="polite">
      <span className="source-health-dot" aria-hidden />
      <span className="source-health-text">{notices[0].label}</span>
      {notices.length > 1 && (
        <span className="source-health-count">+{notices.length - 1}</span>
      )}
      <button className="source-health-button" type="button" onClick={onOpenSettings}>
        Settings
      </button>
    </div>
  );
}

function SearchNoticePanel({
  searching,
  notices,
  onOpenSettings,
}: {
  searching: boolean;
  notices: SourceNotice[];
  onOpenSettings: () => void;
}): JSX.Element {
  return (
    <aside className="search-notice-panel" aria-live="polite" aria-label="Search notices">
      <div className="search-notice-kicker">{searching ? "Searching" : "Search notice"}</div>
      {notices.slice(0, 3).map((notice) => (
        <div className="search-notice-item" data-tone={notice.tone} key={notice.id}>
          <div className="search-notice-title">{notice.label}</div>
          <div className="search-notice-detail">{notice.detail}</div>
        </div>
      ))}
      <button className="search-notice-button" type="button" onClick={onOpenSettings}>
        Open source settings
      </button>
    </aside>
  );
}

function buildSourceNotices(config: BackendConfig | null, warning: string): SourceNotice[] {
  const notices: SourceNotice[] = [];
  if (!config) return notices;
  const sources = config.subtitleSources;
  const hasReadySource =
    (sources.opensubtitles.enabled && !!sources.opensubtitles.apiKey) ||
    (sources.subdl.enabled && !!sources.subdl.apiKey) ||
    (sources.assrt.enabled && !!sources.assrt.token);
  if (sources.opensubtitles.enabled && !sources.opensubtitles.apiKey) {
    notices.push({
      id: "opensubtitles-key",
      label: "OpenSubtitles key missing",
      detail: "OpenSubtitles is enabled but skipped until an API key is saved.",
      tone: "warn",
    });
  }
  if (sources.subdl.enabled && !sources.subdl.apiKey) {
    notices.push({
      id: "subdl-key",
      label: "SubDL key missing",
      detail: "SubDL now needs an API key, so searches may miss episode files.",
      tone: "warn",
    });
  }
  if (sources.assrt.enabled && !sources.assrt.token) {
    notices.push({
      id: "assrt-token",
      label: "ASSRT token missing",
      detail: "ASSRT is skipped; Chinese subtitle coverage can be thin.",
      tone: "warn",
    });
  }
  if (!hasReadySource && notices.length === 0) {
    notices.push({
      id: "no-source",
      label: "No subtitle source ready",
      detail: "Enable a source and save its key or token before searching.",
      tone: "warn",
    });
  }
  if (warning.trim()) {
    notices.push({
      id: "backend-warning",
      label: "Provider warning",
      detail: warning.trim(),
      tone: "info",
    });
  }
  return notices;
}

function shouldShowNoKey(config: BackendConfig | null): boolean {
  if (!config) return false;
  const s = config.subtitleSources;
  const osReady = s.opensubtitles.enabled && !!s.opensubtitles.apiKey;
  const subdlReady = s.subdl.enabled && !!s.subdl.apiKey;
  const assrtReady = s.assrt.enabled && !!s.assrt.token;
  return !(osReady || subdlReady || assrtReady);
}

function isFirstLaunch(config: BackendConfig | null): boolean {
  if (!config) return false;
  const region = config.capture.region;
  return region[2] === 0 && region[3] === 0;
}

function countEnabledSources(config: BackendConfig | null): number {
  if (!config) return 0;
  const s = config.subtitleSources;
  let n = 0;
  if (s.opensubtitles.enabled && s.opensubtitles.apiKey) n++;
  if (s.subdl.enabled && s.subdl.apiKey) n++;
  if (s.assrt.enabled && s.assrt.token) n++;
  return n;
}

function languageLabel(code: string | undefined): string {
  if (!code) return "—";
  const map: Record<string, string> = {
    en: "English",
    "en-US": "English",
    zh: "Chinese",
    "zh-CN": "Simplified Chinese",
    "zh-TW": "Traditional Chinese",
    ja: "Japanese",
    ko: "Korean",
    es: "Spanish",
    fr: "French",
    de: "German",
  };
  return map[code] ?? code;
}

function collectSeasonNumbers(works: WorkItem[]): number[] {
  const numbers = new Set<number>();
  for (const work of works) {
    if (work.mediaType !== "series") continue;
    for (const season of work.seasons) {
      numbers.add(season.seasonNumber);
    }
  }
  return [...numbers].sort((a, b) => a - b);
}

function filterWorks(
  works: WorkItem[],
  mediaFilter: TitleMediaFilter,
  seasonFilters: number[],
  seasonScopeWorkId: string | null,
): WorkItem[] {
  const seasonSet = new Set(seasonFilters);
  return works.flatMap((work) => {
    if (mediaFilter === "movie" && work.mediaType !== "movie") return [];
    if (mediaFilter === "series" && work.mediaType !== "series") return [];
    if (mediaFilter === "specials" && !isSpecialWork(work)) return [];
    if (seasonSet.size > 0 && seasonScopeWorkId && work.id !== seasonScopeWorkId) return [];

    if (work.mediaType !== "series" || seasonSet.size === 0) return [work];

    const seasons = work.seasons.filter((season) => seasonSet.has(season.seasonNumber));
    if (seasons.length === 0) return [];
    const totalEpisodes = seasons.reduce((sum, season) => sum + season.episodes.length, 0);
    const totalSubtitles = seasons.reduce((sum, season) => sum + season.subtitlesCount, 0);
    return [
      {
        ...work,
        seasons,
        totalEpisodes,
        totalSubtitles,
        expandable: seasons.some((season) => season.episodes.length > 0),
      },
    ];
  });
}

function findSeasonFilterScopeWork(
  works: WorkItem[],
  selectedWorkId: string | null,
  expandedWorkId: string | null,
): WorkItem | null {
  const ids = [expandedWorkId, selectedWorkId].filter(Boolean);
  for (const id of ids) {
    const work = works.find((item) => item.id === id && item.mediaType === "series");
    if (work) return work;
  }
  return works.find((work) => work.mediaType === "series") ?? null;
}

function isSpecialWork(work: WorkItem): boolean {
  if (work.mediaType === "series" && work.seasons.some((season) => season.seasonNumber <= 0)) {
    return true;
  }
  return /\b(ova|oad|ona|special|specials)\b/i.test(work.title);
}

function useViewportWidth(): number {
  const [width, setWidth] = useState(() =>
    typeof window === "undefined" ? 1024 : window.innerWidth,
  );

  useEffect(() => {
    const onResize = (): void => setWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return width;
}
