import { t } from "../i18n";
import type {
  BackendGapFill,
  BackendPreparedSession,
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
  return count === 1 ? t("1 line") : t("{count} lines", { count });
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
    if (chosen === null || chosen.unpaired_cues === 0) return t("every line answered");
    const seconds = Math.round(chosen.unpaired_ms / 1000);
    return t("{lines} written on this device · {seconds}s", {
      lines: plural(chosen.unpaired_cues),
      seconds,
    });
  }
  if (fill.active) {
    return t("writing {filled} of {total} lines the file leaves blank…", {
      filled: fill.filled,
      total: fill.total,
    });
  }
  const left = fill.total - fill.filled;
  if (left <= 0) return t("every line answered");
  return t("{left} of {total} blank lines still to write", { left, total: fill.total });
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
        ? t("Movie")
        : w.totalEpisodes > 0
          ? t("Series · {count} eps", { count: w.totalEpisodes })
          : t("Series");
    const seasons: WorkSeasonItem[] = w.seasons.map((season) => ({
      seasonNumber: season.seasonNumber,
      label:
        season.seasonNumber > 0
          ? t("Season {number}", { number: season.seasonNumber })
          : t("Specials"),
      subtitlesCount: season.subtitlesCount,
      episodes: season.episodes.map((ep) => {
        const s = ep.season ?? season.seasonNumber;
        const e = ep.episode;
        const code =
          s && e
            ? `S${String(s).padStart(2, "0")}E${String(e).padStart(2, "0")}`
            : s
              ? t("Season {number} · all episodes", { number: s })
              : ep.title || t("Entry");
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

export const OCR_SOURCE_ID = "__ocr_source__";

const LOCAL_TRANSLATION_ID = "__local__";
const OCR_ONLY_ID = "__ocr__";

export function prepareSelection(sourceId: string, targetId: string) {
  const ocr = sourceId === OCR_SOURCE_ID || targetId === OCR_ONLY_ID;
  return {
    mode: ocr ? ("ocr_fallback" as const) : ("subtitle_pair" as const),
    sourceResultId: ocr ? null : sourceId,
    targetResultId: targetId === LOCAL_TRANSLATION_ID || targetId === OCR_ONLY_ID ? null : targetId,
  };
}

export function selectionChangesPreparedWork(
  prepared: Pick<BackendPreparedSession, "feature_id" | "source_file_id" | "target_file_id"> | null,
  matchId: string | null,
  sourceId: string | null,
  targetId: string | null,
): boolean {
  if (!prepared || !matchId || prepared.feature_id === matchId) return false;
  if (!sourceId || !targetId) return true;
  const selection = prepareSelection(sourceId, targetId);
  return (
    prepared.source_file_id !== selection.sourceResultId ||
    prepared.target_file_id !== selection.targetResultId
  );
}

function subtitleDetail(result: BackendResult): string {
  const suffix = result.fileName.match(/(?:[^.]+\.)?(?:srt|ass|ssa|vtt)$/i)?.[0];
  return [result.languageLabel && t(result.languageLabel), suffix].filter(Boolean).join(" · ");
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
  if (matchId && ranked.length === 0) {
    return [
      {
        id: OCR_SOURCE_ID,
        file: t("Use on-screen OCR"),
        provider: "",
        downloads: "",
        hi: false,
        trusted: false,
        recommended: false,
        note: t("No matching source file. Read the screen and translate live instead."),
      },
    ];
  }
  return ranked.map((r, index) => ({
    id: r.resultId,
    file: r.fileName || r.displayLabel,
    provider: r.providerLabel || r.provider,
    downloads: formatDownloads(r.downloadCount),
    hi: false,
    detail: subtitleDetail(r),
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
  ocrSource = false,
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
    detail: subtitleDetail(r),
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
          title: t("Translation inside the source file"),
          note: t("{translated} of {total} lines · exact timing · nothing to download", {
            translated: inspection.translatedCues,
            total: inspection.totalCues,
          }),
          recommended: true,
        },
      ]
    : [];

  // Neither fallback is a subtitle in the target language, so they sit after the
  // real files rather than competing with them for the top of the list.
  const local: TargetItem = {
    id: LOCAL_TRANSLATION_ID,
    kind: "local",
    title: t("Local translation"),
    note: t("On-device model · translates the source lines"),
    recommended: false,
  };
  const ocr: TargetItem = {
    id: OCR_ONLY_ID,
    kind: "ocr",
    title: t("OCR fallback only"),
    note: t("No subtitle file — OCR only"),
    recommended: false,
  };

  return [...carried, ...fileEntries, ...(ocrSource ? [] : [local]), ocr];
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
