import { useSyncExternalStore } from "react";
import type {
  BackendConfig,
  BackendSnapshot,
  FoundryStatus,
  LanguagesPayload,
  LiveLine,
  PaletteTabId,
  Phase,
} from "../lib/types";

export interface UIState {
  snapshot: BackendSnapshot | null;
  config: BackendConfig | null;
  languages: LanguagesPayload | null;
  foundry: FoundryStatus | null;
  manualView: Phase | null;
  query: string;
  tab: PaletteTabId;
  selectedWorkId: string | null;
  expandedWorkId: string | null;
  expandedSeasonNumber: number | null;
  selectedEpisodeMatchId: string | null;
  selectedSourceId: string | null;
  selectedTargetId: string | null;
  cursorIndex: number;
  liveLines: LiveLine[];
  lastSubtitle: string;
  error: string | null;
  wsConnected: boolean;
}

const initial: UIState = {
  snapshot: null,
  config: null,
  languages: null,
  foundry: null,
  manualView: null,
  query: "",
  tab: "titles",
  selectedWorkId: null,
  expandedWorkId: null,
  expandedSeasonNumber: null,
  selectedEpisodeMatchId: null,
  selectedSourceId: null,
  selectedTargetId: null,
  cursorIndex: -1,
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
