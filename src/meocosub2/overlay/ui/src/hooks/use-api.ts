import type { BackendSnapshot, FoundryStatus, LanguagesPayload } from "../lib/types";

const API_BASE = "";

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const init: RequestInit = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body !== undefined) init.body = JSON.stringify(body);
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    let detail: string;
    try {
      const j = (await res.json()) as { detail?: string };
      detail = j?.detail ?? res.statusText;
    } catch {
      detail = await res.text().catch(() => res.statusText);
    }
    throw new Error(`${method} ${path} failed (${res.status}): ${detail}`);
  }
  return (await res.json()) as T;
}

export interface SearchResponse {
  results: BackendSnapshot["search_results"];
  matches: BackendSnapshot["search_matches"];
  works: BackendSnapshot["search_works"];
  warnings: string[];
}

export interface PrepareBody {
  mode: "subtitle_pair" | "ocr_fallback";
  matchId?: string | null;
  sourceResultId?: string | null;
  targetResultId?: string | null;
}

export interface ClientLogBody {
  event: string;
  level?: "debug" | "info" | "warning" | "error";
  correlationId?: string | null;
  data?: Record<string, unknown>;
}

export const api = {
  getState: () => request<BackendSnapshot>("GET", "/api/state"),
  getConfig: () => request<BackendSnapshot["config"]>("GET", "/api/config"),
  putConfig: (payload: BackendSnapshot["config"]) =>
    request<BackendSnapshot["config"]>("PUT", "/api/config", payload),
  getLanguages: () => request<LanguagesPayload>("GET", "/api/languages"),
  getFoundryStatus: (probe = false, autoStart = false) =>
    request<FoundryStatus>(
      "GET",
      `/api/foundry/status?probe=${probe}&autoStart=${autoStart}`,
    ),
  prepareFoundry: () => request<FoundryStatus>("POST", "/api/foundry/prepare"),
  installOcrLanguage: (languageTag: string) =>
    request<{ status: string }>("POST", "/api/ocr/install", { languageTag }),
  search: (
    title: string,
    sourceLanguage?: string,
    targetLanguage?: string,
    correlationId?: string,
  ): Promise<SearchResponse> =>
    request("POST", "/api/search", { title, sourceLanguage, targetLanguage, correlationId }),
  logClient: (body: ClientLogBody) =>
    request<{ status: string }>("POST", "/api/log/client", body),
  prepareSession: (body: PrepareBody) =>
    request<{ session: BackendSnapshot["prepared_session"] }>(
      "POST",
      "/api/session/prepare",
      body,
    ),
  startSession: (sessionId?: string | null) =>
    request<{ status: string }>("POST", "/api/session/start", { sessionId }),
  stopSession: () => request<{ status: string }>("POST", "/api/session/stop"),
};
