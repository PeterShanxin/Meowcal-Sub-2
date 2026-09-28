import type {
  BackendGapFill,
  BackendResult,
  BackendSnapshot,
  BackendTargetAlignment,
  BackendWork,
  InfoChip,
  Phase,
  SourceInspection,
  SourceItem,
  TargetItem,
  WorkItem,
  WorkSeasonItem,
} from "../lib/types";

export function derivePhase(snapshot: BackendSnapshot | null, manualView: Phase | null): Phase {
  if (manualView) return manualView;
  if (!snapshot) return "home";
  if (snapshot.status === "running") return "live";
  if (snapshot.prepared_session) return "prep";
  return "home";
}

function plural(count: number): string {
  return count === 1 ? "1 line" : `${count} lines`;
}

/**
 * What the chosen target file leaves for the model, in the viewer's terms.
 *
 * The same number throughout, read at whatever stage it has reached: what the
 * model will have to write, what it is writing, and what it wrote. The seconds
 * are dropped once filling starts, because they measure the whole hole and only
 * part of it is left.
 *
 * Says whose blanks these are once the count is live. A bilingual source that
 * answers 442 of its 450 cues still leaves eight, and a card that only says
 * lines are being written here reads as the app second-guessing a file the
 * viewer picked precisely because it was complete.
 */
export function coverageLabel(
  chosen: BackendTargetAlignment | null,
  fill: BackendGapFill | null,
): string {
  if (fill === null) {
    if (chosen === null || chosen.unpaired_cues === 0) return "every line answered";
    const seconds = Math.round(chosen.unpaired_ms / 1000);
    return `${plural(chosen.unpaired_cues)} written on this device · ${seconds}s`;
  }
  if (fill.active) return `writing ${fill.filled} of ${fill.total} lines the file leaves blank…`;
  const left = fill.total - fill.filled;
  if (left <= 0) return "every line answered";
  return `${left} of ${fill.total} blank lines still to write`;
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
        const code =
          s && e
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

/** How many ranked entries carry the recommended badge. */
const RECOMMENDED_COUNT = 3;

/**
 * Best subtitle first: how well the file matches the episode, then how much the
 * provider is trusted, then how many people downloaded it.
 */
function byRank(a: BackendResult, b: BackendResult): number {
  return (
    b.matchScore - a.matchScore ||
    a.providerRank - b.providerRank ||
    b.downloadCount - a.downloadCount
  );
}

/** A badge on the only option tells the reader nothing. */
function recommendedUpTo(total: number): number {
  return total > 1 ? RECOMMENDED_COUNT : 0;
}

export function mapResultsToSource(
  results: BackendResult[],
  matchId: string | null,
  sourceLanguage: string,
): SourceItem[] {
  const ranked = results
    .filter((r) => {
      if (matchId && r.matchId !== matchId) return false;
      return languageMatches(r.language, sourceLanguage);
    })
    .sort(byRank);
  const recommendUpTo = recommendedUpTo(ranked.length);
  return ranked.map((r, index) => ({
    id: r.resultId,
    file: r.fileName || r.displayLabel,
    provider: r.providerLabel || r.provider,
    downloads: formatDownloads(r.downloadCount),
    hi: false,
    trusted: r.providerRank <= 1,
    recommended: index < recommendUpTo,
    raw: r,
  }));
}

export function mapResultsToTarget(
  results: BackendResult[],
  matchId: string | null,
  targetLanguage: string,
  inspection?: SourceInspection | null,
): TargetItem[] {
  const ranked = results
    .filter((r) => {
      if (matchId && r.matchId !== matchId) return false;
      return languageMatches(r.language, targetLanguage);
    })
    .sort(byRank);
  const recommendUpTo = recommendedUpTo(ranked.length);
  const fileEntries: TargetItem[] = ranked.map((r, index) => ({
    id: r.resultId,
    kind: "file" as const,
    file: r.fileName || r.displayLabel,
    provider: r.providerLabel || r.provider,
    downloads: formatDownloads(r.downloadCount),
    recommended: index < recommendUpTo,
    raw: r,
  }));

  // A source that carries its own translation leads the list. It shares the cue
  // with the dialogue rather than being matched to it by time overlap, so it is
  // aligned exactly, and it is already downloaded.
  const carried: TargetItem[] = inspection?.carriesTranslation
    ? [
        {
          id: "__source__",
          kind: "source" as const,
          title: "Translation inside the source file",
          note: `${inspection.translatedCues} of ${inspection.totalCues} lines · exact timing · nothing to download`,
          recommended: true,
        },
      ]
    : [];

  // Neither fallback is a subtitle in the target language, so they sit after the
  // real files rather than competing with them for the top of the list.
  const local: TargetItem = {
    id: "__local__",
    kind: "local",
    title: "Local translation",
    note: "On-device model · translates the source lines",
    recommended: false,
  };
  const ocr: TargetItem = {
    id: "__ocr__",
    kind: "ocr",
    title: "OCR fallback only",
    note: "No subtitle file — OCR only",
    recommended: false,
  };

  return [...carried, ...fileEntries, local, ocr];
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

/**
 * The language pair after choosing `code` for `side`. Choosing the language
 * already on the other side reverses the pair rather than pointing a language
 * at itself.
 */
export function applyLanguageChoice(
  languages: { source: string; target: string },
  side: "source" | "target",
  code: string,
): { source: string; target: string } {
  const other = side === "source" ? "target" : "source";
  const next = { ...languages, [side]: code };
  if (code.toLowerCase() === languages[other].toLowerCase()) {
    next[other] = languages[side];
  }
  return next;
}

export function seasonHydrateKey(workId: string, seasonNumber: number): string {
  return `${workId}:${seasonNumber}`;
}

export function episodeHydrateKey(workId: string, seasonNumber: number, episode: number): string {
  return `${workId}:${seasonNumber}:${episode}`;
}
