import { isTauri } from "../hooks/use-tauri";

/** The run token the backend injects into the served page. */
declare global {
  interface Window {
    __MEOWCAL__?: { token?: string };
  }
}

function readToken(): string {
  // WebView2 has no address bar and needs the query token on a document reload.
  // Browser pages remove it from the visible address and keep it only in memory.
  const url = new URL(window.location.href);
  const fromQuery = url.searchParams.get("token") ?? "";
  if (fromQuery && !isTauri()) {
    url.searchParams.delete("token");
    window.history.replaceState(null, "", url.toString());
  }
  return window.__MEOWCAL__?.token ?? fromQuery;
}

export const accessToken = readToken();

export function withToken(path: string): string {
  if (!accessToken) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}token=${encodeURIComponent(accessToken)}`;
}
