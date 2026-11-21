import { useSyncExternalStore } from "react";
import type {
  BackendConfig,
  BackendSnapshot,
  EngineStatus,
  LanguagesPayload,
  LiveLine,
  PaletteTabId,
  Phase,
  SourceInspection,
  TitleMediaFilter,
} from "../lib/types";

export interface UIState {
  snapshot: BackendSnapshot | null;
  config: BackendConfig | null;
  languages: LanguagesPayload | null;
  engine: EngineStatus | null;
  manualView: Phase | null;
  query: string;
  tab: PaletteTabId;
  titleMediaFilter: TitleMediaFilter;
  selectedSeasonFilters: number[];
  selectedWorkId: string | null;
  expandedWorkId: string | null;
  expandedSeasonNumber: number | null;
  selectedEpisodeMatchId: string | null;
  selectedSourceId: string | null;
  selectedTargetId: string | null;
  /** What the chosen source turned out to hold. Null until it has been read. */
  sourceInspection: SourceInspection | null;
  /** The target step waits on this: the list it shows depends on the answer. */
  inspectingSource: boolean;
  cursorIndex: number;
  /** Season/episode keys with a subtitle lookup in flight, for per-row progress. */
  hydrating: string[];
  /**
   * Episode keys whose own lookup already ran and found nothing. Repeating it
   * sends the identical query for the identical answer, at the cost of a slot
   * against the provider quota.
   */
  emptyLookups: string[];
  liveLines: LiveLine[];
  lastSubtitle: string;
  error: string | null;
  wsConnected: boolean;
}

const initial: UIState = {
  snapshot: null,
  config: null,
  languages: null,
  engine: null,
  manualView: null,
  query: "",
  tab: "titles",
  titleMediaFilter: "all",
  selectedSeasonFilters: [],
  selectedWorkId: null,
  expandedWorkId: null,
  expandedSeasonNumber: null,
  selectedEpisodeMatchId: null,
  selectedSourceId: null,
  selectedTargetId: null,
  sourceInspection: null,
  inspectingSource: false,
  cursorIndex: -1,
  hydrating: [],
  emptyLookups: [],
  liveLines: [],
  lastSubtitle: "",
  error: null,
  wsConnected: false,
};

type Listener = () => void;

class Store {
  private state: UIState = initial;
  private listeners = new Set<Listener>();

  get = (): UIState => this.state;

  subscribe = (fn: Listener): (() => void) => {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  };

  set = (patch: Partial<UIState> | ((s: UIState) => Partial<UIState>)): void => {
    const next = typeof patch === "function" ? patch(this.state) : patch;
    const updated = { ...this.state, ...next };
    if (
      next.snapshot &&
      this.state.snapshot &&
      this.state.selectedEpisodeMatchId &&
      next.selectedEpisodeMatchId === undefined
    ) {
      // Provider enrichment may identify a provisional title differently. File
      // identities survive that merge and preserve the selection the user made.
      const oldFiles = this.state.snapshot.search_results;
      const chosen = next.snapshot.search_results.find(
        (r) => r.resultId === updated.selectedSourceId,
      );
      const ids = new Set(
        chosen
          ? [chosen.resultId]
          : oldFiles
              .filter((r) => r.matchId === this.state.selectedEpisodeMatchId)
              .map((r) => r.resultId),
      );
      const matches = new Set(
        next.snapshot.search_results.filter((r) => ids.has(r.resultId)).map((r) => r.matchId),
      );
      if (matches.size === 1) {
        const [matchId] = matches;
        updated.selectedEpisodeMatchId = matchId;
        const work = next.snapshot.search_works.find(
          (w) =>
            w.primaryMatchId === matchId ||
            w.seasons.some((s) => s.episodes.some((e) => e.matchId === matchId)),
        );
        if (work) updated.selectedWorkId = work.id;
        const target = next.snapshot.search_results.find(
          (r) => r.resultId === updated.selectedTargetId,
        );
        if (target && target.matchId !== matchId) updated.selectedTargetId = null;
      }
    }
    this.state = updated;
    this.listeners.forEach((fn) => fn());
  };

  pushLiveLine = (text: string, tc: string): void => {
    const line: LiveLine = { text, tc };
    const next = [...this.state.liveLines, line].slice(-5);
    this.set({ liveLines: next, lastSubtitle: text });
  };

  resetSelection = (): void => {
    this.set({
      query: "",
      tab: "titles",
      titleMediaFilter: "all",
      selectedSeasonFilters: [],
      selectedWorkId: null,
      expandedWorkId: null,
      expandedSeasonNumber: null,
      selectedEpisodeMatchId: null,
      selectedSourceId: null,
      selectedTargetId: null,
      sourceInspection: null,
      inspectingSource: false,
      cursorIndex: -1,
      manualView: null,
    });
  };
}

export const store = new Store();

export function useStore<T>(selector: (s: UIState) => T): T {
  return useSyncExternalStore(
    store.subscribe,
    () => selector(store.get()),
    () => selector(store.get()),
  );
}
