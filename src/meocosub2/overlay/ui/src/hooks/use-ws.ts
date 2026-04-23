import { useEffect } from "react";
import { store } from "../state/store";
import type { BackendSnapshot } from "../lib/types";

type WsMessage =
  | { type: "state"; state: BackendSnapshot }
  | { type: "style"; style: Record<string, unknown> }
  | {
      type: "progress";
      progress: { stage: string; message: string; current: number; total: number };
    }
  | { type: "subtitle"; text: string }
  | { type: "error"; message: string }
  | { type: "debug"; data: unknown };

function wsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/app`;
}

export function useAppWebSocket(): void {
  useEffect(() => {
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let cancelled = false;

    const connect = (): void => {
      if (cancelled) return;
      socket = new WebSocket(wsUrl());

      socket.onopen = () => {
        store.set({ wsConnected: true });
      };

      socket.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string) as WsMessage;
          switch (msg.type) {
            case "state":
              store.set({ snapshot: msg.state, config: msg.state.config });
              break;
            case "subtitle": {
              const current = store.get().snapshot;
              const tc = current?.progress.stage
                ? current.progress.message || ""
                : "";
              store.pushLiveLine(msg.text, tc);
              break;
            }
            case "progress":
              store.set((s) =>
                s.snapshot
                  ? { snapshot: { ...s.snapshot, progress: msg.progress } }
                  : {},
              );
              break;
            case "error":
              store.set({ error: msg.message });
              break;
            default:
              break;
          }
        } catch {
          // ignore malformed frames
        }
      };

      socket.onclose = () => {
        store.set({ wsConnected: false });
        if (!cancelled) {
          reconnectTimer = window.setTimeout(connect, 1500);
        }
      };

      socket.onerror = () => {
        socket?.close();
      };
    };

    connect();
    return () => {
      cancelled = true;
      if (reconnectTimer != null) window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);
}
