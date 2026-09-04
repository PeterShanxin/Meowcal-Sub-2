/** The run token the backend injects into the served page. */
declare global {
  interface Window {
    __MEOWCAL__?: { token?: string };
  }
}

function readToken(): string {
  // The desktop shell navigates with the token in the query string. Keep it in
  // memory and take it back out of the address bar either way, so it does not
  // sit in history for the lifetime of the backend.
  const url = new URL(window.location.href);
  const fromQuery = url.searchParams.get("token") ?? "";
  if (fromQuery) {
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

export {};
