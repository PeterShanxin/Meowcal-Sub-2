import { useSyncExternalStore } from "react";
import type {
  BackendConfig,
  BackendSnapshot,
  EngineStatus,
  LanguagesPayload,
  LiveLine,
  PaletteTabId,
  Phase,
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
  cursorIndex: number;
  /** Season/episode keys with a subtitle lookup in flight, for per-row progress. */
  hydrating: string[];
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
  cursorIndex: -1,
  hydrating: [],
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
    this.state = { ...this.state, ...next };
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
