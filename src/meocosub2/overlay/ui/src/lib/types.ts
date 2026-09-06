export type Phase = "home" | "prep" | "live" | "settings" | "empty" | "no-key";

export type BackendStatus = "idle" | "searching" | "preparing" | "running" | "stopping" | "error";

export interface BackendMatch {
  id: string;
  matchId: string;
  title: string;
  year: number | null;
  imdbId: string | null;
  tmdbId: string | null;
  mediaType: string;
  season: number | null;
  episode: number | null;
  parentTitle: string | null;
  subtitlesCount: number;
  matchScore: number;
  providerCount: number;
  providers: string[];
  providerLabels: string[];
  displayLabel: string;
}

export interface BackendResult {
  id: string;
  resultId: string;
  matchId: string;
  provider: string;
  providerLabel: string;
  title: string;
  year: number | null;
  imdbId: string | null;
  mediaType: string;
  season: number | null;
  episode: number | null;
  parentTitle: string | null;
  language: string;
  downloadCount: number;
  fileName: string;
  matchScore: number;
  providerRank: number;
  displayLabel: string;
  languageLabel: string;
}

export interface BackendPreparedSession {
  session_id: string;
  title: string;
  source_language: string;
  target_language: string;
  resolved_source_language: string;
  source_language_mode: "exact" | "family_fallback";
  session_mode: "subtitle_pair" | "ocr_fallback" | "auto_candidates";
  target_match_mode:
    | "subtitle_file"
    | "local_translation"
    | "target_subtitle_match"
    | "direct_translation"
    | "auto_subtitle_file"
    | "auto_live_translation";
  feature_id: string | null;
  source_file_id: string | null;
  source_file_name: string | null;
  source_summary: string | null;
  source_provider: string | null;
  source_path: string | null;
  source_line_count: number;
  target_file_id: string | null;
  target_file_name: string | null;
  target_provider: string | null;
  target_path: string | null;
  target_line_count: number;
  translated_line_count: number;
  used_translation: boolean;
  source_candidate_count: number;
  target_candidate_count: number;
  target_alignment: BackendTargetAlignment[];
}

export interface BackendTargetAlignment {
  result_id: string;
  file_name: string;
  provider: string;
  unpaired_cues: number;
  unpaired_ms: number;
  chosen: boolean;
}

export interface BackendProgress {
  stage: string;
  message: string;
  current: number;
  total: number;
}

export interface BackendConfig {
  subtitleSources: {
    opensubtitles: {
      enabled: boolean;
      apiKey: string;
      username: string;
      password: string;
      enableOrgFallback: boolean;
    };
    subdl: { enabled: boolean; apiKey: string };
    assrt: { enabled: boolean; token: string };
    tmdb: { apiKey: string; mergeEnabled: boolean };
  };
  languages: { source: string; target: string };
  capture: {
    region: [number, number, number, number];
    intervalMs: number;
    ocrLanguage: string;
  };
  matching: { fuzzyThreshold: number; windowSize: number };
  translation: {
    timeoutS: number;
  };
  sync: { biasMs: number };
  overlay: Record<string, unknown>;
  debug: { mode: boolean };
}

export interface BackendEpisode {
  season: number | null;
  episode: number | null;
  title: string;
  matchId: string;
  year: number | null;
  subtitlesCount: number;
  providers: string[];
}

export interface BackendSeason {
  seasonNumber: number;
  subtitlesCount: number;
  episodes: BackendEpisode[];
}

export interface BackendInfoChip {
  kind: string;
  label: string;
  tone: string;
}

export interface BackendWork {
  id: string;
  workId: string;
  title: string;
  mediaType: "movie" | "series";
  year: number | null;
  yearEnd: number | null;
  displayYear: string;
  imdbId: string | null;
  tmdbId: string | null;
  posterUrl: string | null;
  providers: string[];
  providerLabels: string[];
  primaryMatchId: string | null;
  expandable: boolean;
  totalEpisodes: number;
  totalSubtitles: number;
  matchScore: number;
  seasons: BackendSeason[];
  infoChips: BackendInfoChip[];
}

export interface BackendSnapshot {
  status: BackendStatus;
  title: string;
  source_language: string;
  target_language: string;
  search_results: BackendResult[];
  search_matches: BackendMatch[];
  search_works: BackendWork[];
  selected_feature_id: string | null;
  selected_source_file_id: string | null;
  selected_target_file_id: string | null;
  prepared_session: BackendPreparedSession | null;
  progress: BackendProgress;
  last_subtitle: string;
  error_message: string;
  warning_message: string;
  config: BackendConfig;
}

export interface WorkEpisodeItem {
  matchId: string;
  season: number | null;
  episode: number | null;
  label: string;
  title: string;
  subtitlesCount: number;
}

export interface WorkSeasonItem {
  seasonNumber: number;
  label: string;
  subtitlesCount: number;
  episodes: WorkEpisodeItem[];
}

export interface InfoChip {
  kind: string;
  label: string;
  tone: "neutral" | "accent" | "verified";
}

export interface WorkItem {
  id: string;
  title: string;
  year: string;
  type: string;
  mediaType: "movie" | "series";
  expandable: boolean;
  primaryMatchId: string | null;
  totalSubtitles: number;
  totalEpisodes: number;
  providers: string[];
  providerLabels: string[];
  posterUrl: string | null;
  chips: InfoChip[];
  seasons: WorkSeasonItem[];
  raw: BackendWork;
}

export interface SourceItem {
  id: string;
  file: string;
  provider: string;
  downloads: string;
  fps: string;
  hi: boolean;
  trusted: boolean;
  recommended: boolean;
  raw: BackendResult;
}

export type TargetKind = "local" | "ocr" | "file";

export interface TargetItem {
  id: string;
  kind: TargetKind;
  title?: string;
  note?: string;
  file?: string;
  provider?: string;
  downloads?: string;
  fps?: string;
  recommended: boolean;
  raw?: BackendResult;
}

export interface LiveLine {
  tc: string;
  text: string;
}

export type PaletteTabId = "titles" | "source" | "target";

export type TitleMediaFilter = "all" | "series" | "movie" | "specials";

export interface LanguageOption {
  code: string;
  label: string;
}

export interface OcrLanguageOption extends LanguageOption {
  installed: boolean;
}

export interface LanguagesPayload {
  sourceTarget: LanguageOption[];
  ocr?: OcrLanguageOption[];
}

export interface EngineStatus {
  phase: "unsupported" | "needsSetup" | "installing" | "idle" | "ready" | "failed";
  message: string;
  model: string;
  endpoint: string | null;
  ready: boolean;
  installPercent: number;
  accelerator: string;
}
