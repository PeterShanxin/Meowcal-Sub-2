/** The run token the backend injects into the served page. */
declare global {
  interface Window {
    __MEOWCAL__?: { token?: string };
  }
}

function readToken(): string {
  const injected = window.__MEOWCAL__?.token;
  if (injected) return injected;
  // The desktop shell navigates with the token in the query string; keep it in
  // memory and take it back out of the address bar.
  const url = new URL(window.location.href);
  const fromQuery = url.searchParams.get("token") ?? "";
  if (fromQuery) {
    url.searchParams.delete("token");
    window.history.replaceState(null, "", url.toString());
  }
  return fromQuery;
}

export const accessToken = readToken();

export function withToken(path: string): string {
  if (!accessToken) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}token=${encodeURIComponent(accessToken)}`;
}

export {};
