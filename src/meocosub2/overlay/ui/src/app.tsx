import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Backdrop, TopBar } from "./components/primitives";
import { Palette } from "./components/palette";
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
  mapMatchesToTitles,
  mapResultsToSource,
  mapResultsToTarget,
} from "./state/mappers";
import type { BackendConfig, PaletteTabId, Phase } from "./lib/types";

export function App(): JSX.Element {
  useAppWebSocket();
  const snapshot = useStore((s) => s.snapshot);
  const config = useStore((s) => s.config);
  const foundry = useStore((s) => s.foundry);
  const manualView = useStore((s) => s.manualView);
  const query = useStore((s) => s.query);
  const tab = useStore((s) => s.tab);
  const selectedTitleId = useStore((s) => s.selectedTitleId);
  const selectedSourceId = useStore((s) => s.selectedSourceId);
  const selectedTargetId = useStore((s) => s.selectedTargetId);
  const cursorIndex = useStore((s) => s.cursorIndex);
  const liveLines = useStore((s) => s.liveLines);
  const wsConnected = useStore((s) => s.wsConnected);

  const phase: Phase = derivePhase(snapshot, manualView);
  const [searching, setSearching] = useState(false);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const searchAbort = useRef<AbortController | null>(null);

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
  const matchId = selectedTitleId;
  const titles = useMemo(
    () => mapMatchesToTitles(snapshot?.search_matches ?? []),
    [snapshot?.search_matches],
  );
  const sources = useMemo(
    () =>
      mapResultsToSource(
        snapshot?.search_results ?? [],
        matchId,
        snapshot?.source_language ?? "en",
      ),
    [snapshot?.search_results, matchId, snapshot?.source_language],
  );
  const targets = useMemo(
    () =>
      mapResultsToTarget(
        snapshot?.search_results ?? [],
        matchId,
        snapshot?.target_language ?? "zh",
      ),
    [snapshot?.search_results, matchId, snapshot?.target_language],
  );
  const commands = useMemo(() => buildCommands(phase), [phase]);

  const activeList =
    tab === "titles"
      ? titles
      : tab === "source"
        ? sources
        : tab === "target"
          ? targets
          : commands;

  // Enter live/exit live Tauri side-effects
  useEffect(() => {
    if (phase === "live") {
      void tauri.enterLiveMode();
    } else {
      void tauri.exitLiveMode();
    }
  }, [phase]);

  // --- Actions ---

  const focusPalette = useCallback(() => {
    inputRef.current?.focus();
  }, []);

  const runSearch = useCallback(async (title: string) => {
    if (!title.trim()) return;
    searchAbort.current?.abort();
    const ctrl = new AbortController();
    searchAbort.current = ctrl;
    setSearching(true);
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
    store.set({ query: v, cursorIndex: 0 });
  }, []);

  const onTabChange = useCallback((t: PaletteTabId) => {
    store.set({ tab: t, cursorIndex: 0 });
  }, []);

  const onPickTitle = useCallback(
    (id: string) => {
      const t = titles.find((x) => x.id === id);
      store.set({
        selectedTitleId: id,
        selectedSourceId: null,
        selectedTargetId: null,
        tab: "source",
        query: t?.title ?? "",
        cursorIndex: 0,
      });
    },
    [titles],
  );

  const onPickSource = useCallback((id: string) => {
    store.set({ selectedSourceId: id, tab: "target", cursorIndex: 0 });
  }, []);

  const onPickTarget = useCallback(async (id: string) => {
    store.set({ selectedTargetId: id, tab: "cmd", cursorIndex: 0 });
    const currentTitle = store.get().selectedTitleId;
    const currentSource = store.get().selectedSourceId;
    if (!currentTitle || !currentSource) return;
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
        matchId: currentTitle,
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

  const onCommand = useCallback(
    (id: string) => {
      if (id === "c1") void startSync();
      else if (id === "c2") void tauri.openAreaSelector();
      else if (id === "c3") store.set({ manualView: "settings" });
      else if (id === "c4") void clearSession();
    },
    [startSync, clearSession],
  );

  const onSelect = useCallback(() => {
    // Enter on Titles tab with no results yet = submit the search. This
    // matches the palette footer hint ("↵ to search") when titles are empty.
    if (tab === "titles" && activeList.length === 0 && query.trim()) {
      void runSearch(query.trim());
      return;
    }
    if (activeList.length === 0) return;
    const item = activeList[Math.max(0, Math.min(cursorIndex, activeList.length - 1))];
    if (!item) return;
    if (tab === "titles") {
      onPickTitle(item.id);
      return;
    }
    if (tab === "source") {
      onPickSource(item.id);
      return;
    }
    if (tab === "target") {
      void onPickTarget(item.id);
      return;
    }
    if (tab === "cmd") {
      onCommand(item.id);
    }
  }, [activeList, cursorIndex, tab, query, runSearch, onPickTitle, onPickSource, onPickTarget, onCommand]);

  const onPrimaryConfirm = useCallback(() => {
    if (phase === "home" && tab === "titles" && query.trim()) {
      void runSearch(query.trim());
      return;
    }
    if (phase === "prep") {
      void startSync();
    } else if (selectedTitleId && selectedSourceId && selectedTargetId) {
      void onPickTarget(selectedTargetId); // re-prepare if user changed mind
    }
  }, [phase, tab, query, runSearch, startSync, selectedTitleId, selectedSourceId, selectedTargetId, onPickTarget]);

  const onMoveCursor = useCallback(
    (dir: 1 | -1) => {
      store.set((s) => {
        const list =
          s.tab === "titles"
            ? titles.length
            : s.tab === "source"
              ? sources.length
              : s.tab === "target"
                ? targets.length
                : commands.length;
        if (list === 0) return {};
        const next = (s.cursorIndex + dir + list) % list;
        return { cursorIndex: next };
      });
    },
    [titles.length, sources.length, targets.length, commands.length],
  );

  const onCycleTab = useCallback((dir: 1 | -1) => {
    const order: PaletteTabId[] = ["titles", "source", "target", "cmd"];
    store.set((s) => {
      const idx = order.indexOf(s.tab);
      const next = order[(idx + dir + order.length) % order.length];
      return { tab: next, cursorIndex: 0 };
    });
  }, []);

  useKeybinds({
    onFocusPalette: focusPalette,
    onCycleTab,
    onMoveCursor,
    onPrimaryConfirm,
    onSelect,
    onOpenSettings: () => store.set({ manualView: "settings" }),
    onClearSession: () => void clearSession(),
  });

  // --- Render ---

  const showSettings = phase === "settings";
  const noKey = shouldShowNoKey(config);
  const isEmpty = isFirstLaunch(config);

  const isCompact = phase === "prep" || phase === "live";

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
      {!showSettings && (
        <TopBar
          phase={phase}
          wsConnected={wsConnected}
          foundryPhase={foundry?.phase ?? "—"}
          sourcesCount={countEnabledSources(config)}
        />
      )}

      {showSettings && config && (
        <SettingsView
          initialConfig={config}
          onClose={() => store.set({ manualView: null })}
        />
      )}

      {!showSettings && noKey && phase === "home" && !query && (
        <NoApiKey
          onOpenSettings={() => store.set({ manualView: "settings" })}
          onUseSubdl={() => void enableSubdlOnly()}
        />
      )}

      {!showSettings && !noKey && isEmpty && phase === "home" && !query && (
        <EmptyState
          sourceLabel={languageLabel(config?.languages.source)}
          targetLabel={languageLabel(config?.languages.target)}
          onOpenPalette={focusPalette}
        />
      )}

      {!showSettings && (
        <div
          style={{
            position: "absolute",
            top: isCompact ? 56 : 110,
            left: isCompact ? 20 : "50%",
            right: isCompact ? 20 : "auto",
            transform: isCompact ? "none" : "translateX(-50%)",
            width: isCompact ? "auto" : 860,
            zIndex: 4,
            transition: "all 280ms cubic-bezier(.2,.7,.3,1)",
          }}
        >
          {!isCompact && !noKey && !isEmpty && (
            <div style={{ textAlign: "center", marginBottom: 18 }}>
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: 2.5,
                  color: "var(--text-label)",
                  textTransform: "uppercase",
                }}
              >
                Meowcal Studio
              </div>
              <h1
                className="display-serif"
                style={{
                  margin: "6px 0 0",
                  fontSize: 32,
                  fontWeight: 500,
                  letterSpacing: -0.8,
                  color: "var(--text-heading)",
                }}
              >
                What are you watching?
              </h1>
            </div>
          )}
          {!noKey && !isEmpty && (
            <Palette
              phase={phase}
              compact={isCompact}
              query={query}
              onQueryChange={onQueryChange}
              tab={tab}
              onTabChange={onTabChange}
              titles={titles}
              sources={sources}
              targets={targets}
              commands={commands}
              selectedTitleId={selectedTitleId}
              selectedSourceId={selectedSourceId}
              selectedTargetId={selectedTargetId}
              cursorIndex={cursorIndex}
              onPickTitle={onPickTitle}
              onPickSource={onPickSource}
              onPickTarget={(id) => void onPickTarget(id)}
              onCommand={onCommand}
              onPrimary={() => void onPrimaryConfirm()}
              inputRef={inputRef}
              sourceLang={sourceLang}
              targetLang={targetLang}
              searching={searching}
            />
          )}
        </div>
      )}

      {phase === "prep" && !showSettings && (
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
            title={titles.find((t) => t.id === selectedTitleId) ?? null}
            source={sources.find((s) => s.id === selectedSourceId) ?? null}
            target={targets.find((t) => t.id === selectedTargetId) ?? null}
            prepared={snapshot?.prepared_session ?? null}
          />
          <PreviewCard line={liveLines[liveLines.length - 1] ?? null} />
        </div>
      )}

      {phase === "live" && !showSettings && (
        <LiveView
          prev={liveLines[liveLines.length - 2] ?? null}
          current={liveLines[liveLines.length - 1] ?? null}
          onStop={() => void clearSession()}
          onSelectRegion={() => void tauri.openAreaSelector()}
          onOpenSettings={() => store.set({ manualView: "settings" })}
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
