import type {
  BackendResult,
  BackendSnapshot,
  BackendWork,
  CommandItem,
  InfoChip,
  Phase,
  SourceItem,
  TargetItem,
  WorkItem,
  WorkSeasonItem,
} from "../lib/types";

export function derivePhase(
  snapshot: BackendSnapshot | null,
  manualView: Phase | null,
): Phase {
  if (manualView) return manualView;
  if (!snapshot) return "home";
  if (snapshot.status === "running") return "live";
  if (snapshot.prepared_session) return "prep";
  return "home";
}

const CHIP_TONES = new Set<InfoChip["tone"]>(["neutral", "accent", "verified"]);

function normalizeChip(raw: { kind: string; label: string; tone: string }): InfoChip {
  const tone = CHIP_TONES.has(raw.tone as InfoChip["tone"])
    ? (raw.tone as InfoChip["tone"])
    : "neutral";
  return { kind: raw.kind, label: raw.label, tone };
}

export function mapWorksToItems(works: BackendWork[]): WorkItem[] {
  return works.map((w) => {
    const type =
      w.mediaType === "movie"
        ? "Movie"
        : w.totalEpisodes > 0
          ? `Series · ${w.totalEpisodes} eps`
          : "Series";
    const seasons: WorkSeasonItem[] = w.seasons.map((season) => ({
      seasonNumber: season.seasonNumber,
      label: season.seasonNumber > 0 ? `Season ${season.seasonNumber}` : "Specials",
      subtitlesCount: season.subtitlesCount,
      episodes: season.episodes.map((ep) => {
        const s = ep.season ?? season.seasonNumber;
        const e = ep.episode;
        const code = s && e
          ? `S${String(s).padStart(2, "0")}E${String(e).padStart(2, "0")}`
          : s
            ? `Season ${s} · all episodes`
            : ep.title || `Entry`;
        const label = ep.title && ep.title !== code ? `${code} — ${ep.title}` : code;
        return {
          matchId: ep.matchId,
          season: ep.season,
          episode: ep.episode,
          label,
          title: ep.title,
          subtitlesCount: ep.subtitlesCount,
        };
      }),
    }));
    return {
      id: w.id,
      title: w.title,
      year: w.displayYear || "—",
      type,
      mediaType: w.mediaType,
      expandable: w.expandable && seasons.some((s) => s.episodes.length > 0),
      primaryMatchId: w.primaryMatchId,
      totalSubtitles: w.totalSubtitles,
      totalEpisodes: w.totalEpisodes,
      providers: w.providers,
      providerLabels: w.providerLabels,
      posterUrl: w.posterUrl,
      chips: w.infoChips.map(normalizeChip),
      seasons,
      raw: w,
    };
  });
}

function formatDownloads(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "—";
  return n.toLocaleString();
}

export function mapResultsToSource(
  results: BackendResult[],
  matchId: string | null,
  sourceLanguage: string,
): SourceItem[] {
  return results
    .filter((r) => {
      if (matchId && r.matchId !== matchId) return false;
      return languageMatches(r.language, sourceLanguage);
    })
    .map((r) => ({
      id: r.resultId,
      file: r.fileName || r.displayLabel,
      provider: r.providerLabel || r.provider,
      downloads: formatDownloads(r.downloadCount),
      fps: "—",
      hi: false,
      trusted: r.providerRank <= 1,
      raw: r,
    }));
}

export function mapResultsToTarget(
  results: BackendResult[],
  matchId: string | null,
  targetLanguage: string,
): TargetItem[] {
  const fileEntries: TargetItem[] = results
    .filter((r) => {
      if (matchId && r.matchId !== matchId) return false;
      return languageMatches(r.language, targetLanguage);
    })
    .map((r) => ({
      id: r.resultId,
      kind: "file" as const,
      file: r.fileName || r.displayLabel,
      provider: r.providerLabel || r.provider,
      downloads: formatDownloads(r.downloadCount),
      fps: "—",
      raw: r,
    }));

  const local: TargetItem = {
    id: "__local__",
    kind: "local",
    title: "Local translation",
    note: "Foundry · batch translate source lines",
  };
  const ocr: TargetItem = {
    id: "__ocr__",
    kind: "ocr",
    title: "OCR fallback only",
    note: "No subtitle file — OCR only",
  };

  return [local, ...fileEntries, ocr];
}

export function buildCommands(phase: Phase): CommandItem[] {
  const isPrep = phase === "prep";
  return [
    {
      id: "c1",
      icon: "▶",
      label: "Start sync",
      shortcut: "⌘↵",
      kind: "primary",
      disabled: !isPrep,
    },
    {
      id: "c2",
      icon: "⎚",
      label: "Select capture region",
      shortcut: "C",
    },
    {
      id: "c3",
      icon: "⚙",
      label: "Settings",
      shortcut: ",",
    },
    {
      id: "c4",
      icon: "⟲",
      label: "Clear session",
      shortcut: "⇧⌫",
    },
  ];
}

// Backend normalizes Chinese codes: "zh" = Simplified, "zht" = Traditional.
// Both are returned together when either is requested, so treat as one family.
const CHINESE_FAMILY = new Set(["zh", "zht"]);

function languageMatches(resultLang: string, wanted: string): boolean {
  if (!resultLang) return true;
  const a = resultLang.toLowerCase();
  const b = wanted.toLowerCase();
  if (a === b) return true;
  const baseA = a.split(/[-_]/)[0];
  const baseB = b.split(/[-_]/)[0];
  if (baseA === baseB) return true;
  return CHINESE_FAMILY.has(baseA) && CHINESE_FAMILY.has(baseB);
}
