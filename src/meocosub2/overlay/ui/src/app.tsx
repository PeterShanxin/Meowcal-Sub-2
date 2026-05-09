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
import { tauri } from "./hooks/use-tauri";
import { store, useStore } from "./state/store";
import {
  buildCommands,
  derivePhase,
  mapResultsToSource,
  mapResultsToTarget,
  mapWorksToItems,
} from "./state/mappers";
import type {
  BackendConfig,
  LanguageOption,
  PaletteTabId,
  Phase,
  TitleMediaFilter,
  WorkItem,
} from "./lib/types";

export function App(): JSX.Element {
  useAppWebSocket();
  const snapshot = useStore((s) => s.snapshot);
  const config = useStore((s) => s.config);
  const foundry = useStore((s) => s.foundry);
  const manualView = useStore((s) => s.manualView);
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
  const liveLines = useStore((s) => s.liveLines);
  const languages = useStore((s) => s.languages);
  const wsConnected = useStore((s) => s.wsConnected);

  const settingsRequested = manualView === "settings";
  const showSettings = settingsRequested && !!config;
  const phase: Phase = derivePhase(snapshot, null);
  const [searching, setSearching] = useState(false);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const viewportWidth = useViewportWidth();
  const inputRef = useRef<HTMLInputElement>(null);
  const backgroundRef = useRef<HTMLDivElement>(null);
  const searchAbort = useRef<AbortController | null>(null);
  const lastSearchedQuery = useRef<string>("");

  // Bootstrap: initial state + config + foundry status
  useEffect(() => {
    let cancelled = false;
    const load = async (): Promise<void> => {
      try {
        const [snap, langs, foundryStatus] = await Promise.all([
          api.getState(),
          api.getLanguages(),
          api.getFoundryStatus(false, false).catch(() => null),
        ]);
        if (cancelled) return;
        store.set({
          snapshot: snap,
          config: snap.config,
          languages: langs,
          foundry: foundryStatus,
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
  const commands = useMemo(() => buildCommands(phase), [phase]);

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
        : tab === "target"
          ? targets.length
          : commands.length;

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

  // --- Actions ---

  const focusPalette = useCallback(() => {
    inputRef.current?.focus();
  }, []);

  const runSearch = useCallback(async (title: string) => {
    if (!title.trim()) return;
    lastSearchedQuery.current = title.trim();
    searchAbort.current?.abort();
    const ctrl = new AbortController();
    searchAbort.current = ctrl;
    setSearching(true);
    store.set({
      cursorIndex: -1,
      selectedWorkId: null,
      expandedWorkId: null,
      expandedSeasonNumber: null,
      selectedEpisodeMatchId: null,
      selectedSourceId: null,
      selectedTargetId: null,
    });
    try {
      const res = await api.search(title);
      const fresh = await api.getState();
      store.set({ snapshot: fresh, config: fresh.config });
      void res;
    } catch (err) {
      store.set({ error: err instanceof Error ? err.message : String(err) });
    } finally {
      if (searchAbort.current === ctrl) {
        setSearching(false);
        searchAbort.current = null;
      }
    }
  }, []);

  const onQueryChange = useCallback((v: string) => {
    store.set({ query: v, cursorIndex: -1 });
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
      store.set({ tab: t, cursorIndex: cursorForTab(t) });
    },
    [cursorForTab],
  );

  const advanceToSourceTab = useCallback((workId: string, matchId: string) => {
    store.set({
      selectedWorkId: workId,
      selectedEpisodeMatchId: matchId,
      selectedSourceId: null,
      selectedTargetId: null,
      tab: "source",
      query: "",
      cursorIndex: -1,
    });
  }, []);

  const onToggleExpandWork = useCallback(
    (id: string) => {
      const work = filteredWorks.find((w) => w.id === id);
      if (!work) return;
      if (!work.expandable) {
        if (work.primaryMatchId) advanceToSourceTab(id, work.primaryMatchId);
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
    [filteredWorks, advanceToSourceTab],
  );

  const onToggleExpandSeason = useCallback(
    (workId: string, seasonNumber: number) => {
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
    },
    [],
  );

  const onPickWork = useCallback(
    (id: string) => {
      const work = filteredWorks.find((w) => w.id === id);
      if (!work) return;
      if (work.expandable) {
        onToggleExpandWork(id);
        return;
      }
      if (work.primaryMatchId) advanceToSourceTab(id, work.primaryMatchId);
    },
    [filteredWorks, onToggleExpandWork, advanceToSourceTab],
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
    (workId: string, matchId: string) => advanceToSourceTab(workId, matchId),
    [advanceToSourceTab],
  );

  const onPickSource = useCallback((id: string) => {
    store.set({ selectedSourceId: id, tab: "target", cursorIndex: -1 });
  }, []);

  const onPickTarget = useCallback(async (id: string) => {
    store.set({ selectedTargetId: id, tab: "cmd", cursorIndex: -1 });
    const currentEpisode = store.get().selectedEpisodeMatchId;
    const currentSource = store.get().selectedSourceId;
    if (!currentEpisode || !currentSource) return;
    // Backend accepts only "subtitle_pair" | "ocr_fallback". Local AI
    // translation is triggered by subtitle_pair with no targetResultId —
    // the controller falls back to Foundry via target_match_mode.
    const mode: "subtitle_pair" | "ocr_fallback" =
      id === "__ocr__" ? "ocr_fallback" : "subtitle_pair";
    const targetResultId =
      id === "__local__" || id === "__ocr__" ? null : id;
    try {
      await api.prepareSession({
        mode,
        matchId: currentEpisode,
        sourceResultId: currentSource,
        targetResultId,
      });
      const fresh = await api.getState();
      store.set({ snapshot: fresh, config: fresh.config });
    } catch (err) {
      store.set({ error: err instanceof Error ? err.message : String(err) });
    }
  }, []);

  const startSync = useCallback(async () => {
    try {
      await api.startSession();
      const fresh = await api.getState();
      store.set({ snapshot: fresh, config: fresh.config });
    } catch (err) {
      store.set({ error: err instanceof Error ? err.message : String(err) });
    }
  }, []);

  const onChangeLang = useCallback(async (type: "source" | "target", code: string) => {
    const current = store.get().config;
    if (!current) return;
    const next: BackendConfig = {
      ...current,
      languages: { ...current.languages, [type]: code },
    };
    try {
      const saved = await api.putConfig(next);
      store.set({ config: saved });
      store.resetSelection();
    } catch (err) {
      store.set({ error: err instanceof Error ? err.message : String(err) });
    }
  }, []);

  const enableSubdlOnly = useCallback(async () => {
    const current = store.get().config;
    if (!current) return;
    const next: BackendConfig = {
      ...current,
      subtitleSources: {
        ...current.subtitleSources,
        subdl: { enabled: true },
      },
    };
    try {
      const saved = await api.putConfig(next);
      store.set({ config: saved });
    } catch (err) {
      store.set({ error: err instanceof Error ? err.message : String(err) });
    }
  }, []);

  const clearSession = useCallback(async () => {
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
  }, []);

  const openSettings = useCallback(() => {
    if (store.get().config) {
      store.set({ manualView: "settings" });
    }
  }, []);

  const closeSettings = useCallback(() => {
    store.set({ manualView: null });
  }, []);

  const onCommand = useCallback(
    (id: string) => {
      if (id === "c1") void startSync();
      else if (id === "c2") void tauri.openAreaSelector();
      else if (id === "c3") openSettings();
      else if (id === "c4") void clearSession();
    },
    [startSync, openSettings, clearSession],
  );

  const onSelect = useCallback(() => {
    if (tab === "titles" && query.trim() && query.trim() !== lastSearchedQuery.current) {
      void runSearch(query.trim());
      return;
    }
    if (tab === "titles" && activeListLength === 0 && query.trim()) {
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
      return;
    }
    if (tab === "cmd") {
      const item = commands[index];
      if (item) onCommand(item.id);
    }
  }, [
    activeListLength,
    commands,
    cursorIndex,
    onCommand,
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
    if (phase === "home" && tab === "titles" && query.trim()) {
      void runSearch(query.trim());
      return;
    }
    if (phase === "prep") {
      void startSync();
    } else if (episodeMatchId && selectedSourceId && selectedTargetId) {
      void onPickTarget(selectedTargetId); // re-prepare if user changed mind
    }
  }, [phase, tab, query, runSearch, startSync, episodeMatchId, selectedSourceId, selectedTargetId, onPickTarget]);

  const onMoveCursor = useCallback(
    (dir: "up" | "down" | "left" | "right") => {
      store.set((s) => {
        if ((dir === "left" || dir === "right") && s.tab !== "titles") {
          const order: PaletteTabId[] = ["titles", "source", "target", "cmd"];
          const idx = order.indexOf(s.tab);
          const next = order[(idx + (dir === "right" ? 1 : -1) + order.length) % order.length];
          return { tab: next, cursorIndex: cursorForTab(next) };
        }
        const list =
          s.tab === "titles"
            ? titleListLength
            : s.tab === "source"
              ? sources.length
              : s.tab === "target"
                ? targets.length
                : commands.length;
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
    [titleListLength, sources.length, targets.length, commands.length, titleGridColumns, titleNavRows, titleWorkRowIndices, cursorForTab],
  );

  const onCycleTab = useCallback((dir: 1 | -1) => {
    const order: PaletteTabId[] = ["titles", "source", "target", "cmd"];
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
  const palettePhase = showSettings ? "settings" : phase;

  useEffect(() => {
    const background = backgroundRef.current as (HTMLDivElement & { inert?: boolean }) | null;
    if (!background) return;
    background.inert = showSettings;
    if (showSettings) {
      background.setAttribute("inert", "");
    } else {
      background.removeAttribute("inert");
    }
  }, [showSettings]);

  return (
    <div
      style={{
        position: "relative",
        width: "100vw",
        height: "100vh",
        overflow: "hidden",
      }}
    >
      <Backdrop />
      <div
        ref={backgroundRef}
        aria-hidden={showSettings}
        style={{
          position: "absolute",
          inset: 0,
          pointerEvents: showSettings ? "none" : "auto",
        }}
      >
        <TopBar
          phase={phase}
          wsConnected={wsConnected}
          foundryPhase={foundry?.phase ?? "—"}
          sourcesCount={countEnabledSources(config)}
          onOpenSettings={openSettings}
        />

        {noKey && phase === "home" && !query && (
          <NoApiKey
            onOpenSettings={openSettings}
            onUseSubdl={() => void enableSubdlOnly()}
          />
        )}

        {!noKey && isEmpty && phase === "home" && !query && (
          <EmptyState
            sourceLabel={languageLabel(config?.languages.source)}
            targetLabel={languageLabel(config?.languages.target)}
            onOpenPalette={focusPalette}
          />
        )}

        <div
          style={{
            position: "absolute",
            top: isCompact ? 56 : isIdle ? 210 : 88,
            left: isCompact ? 20 : "50%",
            right: isCompact ? 20 : "auto",
            transform: isCompact ? "none" : "translateX(-50%)",
            width: isCompact ? "auto" : "min(920px, calc(100vw - 28px))",
            zIndex: 4,
            transition:
              "top 520ms cubic-bezier(.22, 1.3, .36, 1), transform 280ms cubic-bezier(.2,.7,.3,1), width 280ms cubic-bezier(.2,.7,.3,1)",
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
              commands={commands}
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
              onPickSource={onPickSource}
              onPickTarget={(id) => void onPickTarget(id)}
              onCommand={onCommand}
              onPrimary={() => void onPrimaryConfirm()}
              inputRef={inputRef}
              sourceLang={sourceLang}
              targetLang={targetLang}
              searching={searching}
              langOptions={(languages?.sourceTarget ?? []) as LanguageOption[]}
              onChangeLang={(type, code) => void onChangeLang(type, code)}
            />
          )}
        </div>

        {phase === "prep" && (
          <div
            style={{
              position: "absolute",
              top: 380,
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

function shouldShowNoKey(config: BackendConfig | null): boolean {
  if (!config) return false;
  const s = config.subtitleSources;
  const osReady = s.opensubtitles.enabled && !!s.opensubtitles.apiKey;
  const subdlReady = s.subdl.enabled;
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
  if (s.opensubtitles.enabled) n++;
  if (s.subdl.enabled) n++;
  if (s.assrt.enabled) n++;
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
