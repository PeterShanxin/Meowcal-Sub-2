import type { BackendSnapshot, EngineStatus, LanguagesPayload } from "../lib/types";
import { accessToken } from "../lib/session";

const API_BASE = "";

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const init: RequestInit = {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-Meowcal-Token": accessToken,
    },
  };
  if (body !== undefined) init.body = JSON.stringify(body);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch {
    // The studio and its backend are the same install, so a request that never
    // left means the backend is down - "Failed to fetch" says nothing the reader
    // can act on.
    throw new Error("Meowcal's backend is not responding. It may still be starting up.");
  }
  if (!res.ok) {
    let detail: string;
    try {
      const j = (await res.json()) as { detail?: string };
      detail = j?.detail ?? "";
    } catch {
      detail = await res.text().catch(() => "");
    }
    // The backend's own wording names the provider and the reason; the method and
    // path belong in the event log, not in front of the reader.
    throw new Error(detail.trim() || `The backend returned ${res.status} ${res.statusText}.`);
  }
  return (await res.json()) as T;
}

export interface SearchResponse {
  results: BackendSnapshot["search_results"];
  matches: BackendSnapshot["search_matches"];
  works: BackendSnapshot["search_works"];
  warnings: string[];
}

export interface HydrateEpisodeResponse {
  hydrated: boolean;
  matchId: string | null;
  results: BackendSnapshot["search_results"];
  matches: BackendSnapshot["search_matches"];
  works: BackendSnapshot["search_works"];
}

export interface HydrateSeasonResponse {
  hydrated: boolean;
  hydratedEpisodes: number;
  results: BackendSnapshot["search_results"];
  matches: BackendSnapshot["search_matches"];
  works: BackendSnapshot["search_works"];
}

export interface PrepareBody {
  mode: "subtitle_pair" | "ocr_fallback" | "auto_candidates";
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
  getEngineStatus: () => request<EngineStatus>("GET", "/api/engine/status"),
  installEngine: () => request<EngineStatus>("POST", "/api/engine/install"),
  installOcrLanguage: (languageTag: string) =>
    request<{ status: string }>("POST", "/api/ocr/install", { languageTag }),
  search: (
    title: string,
    sourceLanguage?: string,
    targetLanguage?: string,
    correlationId?: string,
  ): Promise<SearchResponse> =>
    request("POST", "/api/search", { title, sourceLanguage, targetLanguage, correlationId }),
  hydrateEpisode: (
    workId: string,
    title: string,
    season: number,
    episode: number,
    correlationId?: string,
  ): Promise<HydrateEpisodeResponse> =>
    request("POST", "/api/search/episode", { workId, title, season, episode, correlationId }),
  hydrateSeason: (
    workId: string,
    title: string,
    season: number,
    correlationId?: string,
  ): Promise<HydrateSeasonResponse> =>
    request("POST", "/api/search/season", { workId, title, season, correlationId }),
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
