import type {
  BackendMatch,
  BackendResult,
  BackendSnapshot,
  CommandItem,
  Phase,
  SourceItem,
  TargetItem,
  TitleItem,
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

export function mapMatchesToTitles(
  matches: BackendMatch[],
  results: BackendResult[] = [],
  sourceLanguage = "en",
  targetLanguage = "zh",
): TitleItem[] {
  const coverageByMatch = new Map<string, { sourceCount: number; targetCount: number }>();
  for (const result of results) {
    const key = result.matchId;
    const entry = coverageByMatch.get(key) ?? { sourceCount: 0, targetCount: 0 };
    if (languageMatches(result.language, sourceLanguage)) {
      entry.sourceCount += 1;
    }
    if (languageMatches(result.language, targetLanguage)) {
      entry.targetCount += 1;
    }
    coverageByMatch.set(key, entry);
  }

  const items = matches.map((m, index) => {
    const coverage = coverageByMatch.get(m.matchId) ?? { sourceCount: 0, targetCount: 0 };
    const type =
      m.mediaType === "movie"
        ? "Movie"
        : m.mediaType === "episode" || m.mediaType === "series" || m.mediaType === "tvshow"
          ? `Series${m.season != null ? ` · S${m.season}` : ""}${
              m.episode != null ? `E${m.episode}` : ""
            }`
          : m.mediaType || "Title";
    const runtime =
      m.subtitlesCount > 0
        ? `${m.subtitlesCount.toLocaleString()} subs`
        : (m.providerLabels.join(" · ") || m.displayLabel);
    return {
      id: m.matchId,
      title: m.title,
      year: m.year != null ? String(m.year) : "—",
      type,
      runtime,
      sourceCount: coverage.sourceCount,
      targetCount: coverage.targetCount,
      isRecommended: false,
      raw: m,
      _originalIndex: index,
    };
  });

  const eligible = items.filter((item) => item.sourceCount > 0 && item.targetCount > 0);
  if (eligible.length === 0) {
    return items.map(({ _originalIndex, ...item }) => item);
  }

  const recommended = eligible.reduce((best, current) => {
    if (best === null) return current;
    const bestMin = Math.min(best.sourceCount, best.targetCount);
    const currentMin = Math.min(current.sourceCount, current.targetCount);
    if (currentMin !== bestMin) return currentMin > bestMin ? current : best;

    const bestSum = best.sourceCount + best.targetCount;
    const currentSum = current.sourceCount + current.targetCount;
    if (currentSum !== bestSum) return currentSum > bestSum ? current : best;

    if (current.raw.matchScore !== best.raw.matchScore) {
      return current.raw.matchScore > best.raw.matchScore ? current : best;
    }

    return current._originalIndex < best._originalIndex ? current : best;
  }, null as (typeof items)[number] | null);

  if (!recommended) {
    return items.map(({ _originalIndex, ...item }) => item);
  }

  const recommendedId = recommended.id;
  const ordered = [
    ...items.filter((item) => item.id === recommendedId).map((item) => ({ ...item, isRecommended: true })),
    ...items.filter((item) => item.id !== recommendedId),
  ];
  return ordered.map(({ _originalIndex, ...item }) => item);
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
