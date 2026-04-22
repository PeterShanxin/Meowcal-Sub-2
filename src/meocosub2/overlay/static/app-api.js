export const TAURI = window.__TAURI__?.core?.invoke ? window.__TAURI__ : null;
const API_BASE = /^https?:$/i.test(window.location.protocol) ? window.location.origin : "";

export function apiUrl(path) {
  return `${API_BASE}${path}`;
}

export function wsUrl(path) {
  if (!API_BASE) {
    return `ws://${location.host}${path}`;
  }
  const url = new URL(API_BASE);
  return `ws://${url.host}${path}`;
}

export async function fetchJson(url, options = {}) {
  const response = await fetch(apiUrl(url), {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail || response.statusText);
  }

  return response.json();
}
