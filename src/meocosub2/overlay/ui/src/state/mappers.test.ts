import { describe, expect, it } from "vitest";

import type { BackendResult, BackendTargetAlignment, BackendWork } from "../lib/types";
import {
  applyLanguageChoice,
  coverageLabel,
  mapResultsToSource,
  mapResultsToTarget,
  mapWorksToItems,
} from "./mappers";

function makeWork(
  overrides: Partial<BackendWork> & Pick<BackendWork, "id" | "title" | "mediaType">,
): BackendWork {
  return {
    workId: overrides.id,
    year: null,
    yearEnd: null,
    displayYear: "",
    imdbId: null,
    tmdbId: null,
    providers: [],
    providerLabels: [],
    primaryMatchId: null,
    expandable: false,
    totalEpisodes: 0,
    totalSubtitles: 0,
    matchScore: 0,
    seasons: [],
    infoChips: [],
    ...overrides,
  } as BackendWork;
}

function makeResult(
  overrides: Partial<BackendResult> & Pick<BackendResult, "resultId" | "matchId" | "language">,
): BackendResult {
  const { resultId, matchId, language, ...rest } = overrides;
  return {
    id: resultId,
    resultId,
    matchId,
    provider: "opensubtitles",
    providerLabel: "OpenSubtitles",
    title: "subtitle",
    year: null,
    imdbId: null,
    mediaType: "episode",
    season: null,
    episode: null,
    parentTitle: null,
    language,
    downloadCount: 0,
    fileName: resultId,
    matchScore: 0,
    providerRank: 2,
    displayLabel: resultId,
    languageLabel: language,
    ...rest,
  };
}

describe("mapWorksToItems", () => {
  it("marks movie works as non-expandable and carries primary match id", () => {
    const items = mapWorksToItems([
      makeWork({
        id: "work-1",
        title: "Inception",
        mediaType: "movie",
        displayYear: "2010",
        primaryMatchId: "match-7",
      }),
    ]);
    expect(items).toHaveLength(1);
    expect(items[0].expandable).toBe(false);
    expect(items[0].type).toBe("Movie");
    expect(items[0].primaryMatchId).toBe("match-7");
  });

  it("builds season+episode labels for series", () => {
    const items = mapWorksToItems([
      makeWork({
        id: "work-1",
        title: "Overlord",
        mediaType: "series",
        expandable: true,
        totalEpisodes: 2,
        seasons: [
          {
            seasonNumber: 1,
            subtitlesCount: 5,
            episodes: [
              {
                season: 1,
                episode: 1,
                title: "The End and the Beginning",
                matchId: "match-10",
                year: 2015,
                subtitlesCount: 3,
                providers: ["opensubtitles"],
              },
              {
                season: 1,
                episode: 2,
                title: "",
                matchId: "match-11",
                year: 2015,
                subtitlesCount: 2,
                providers: ["subdl"],
              },
            ],
          },
        ],
      }),
    ]);
    const work = items[0];
    expect(work.expandable).toBe(true);
    expect(work.type).toBe("Series · 2 eps");
    expect(work.seasons[0].episodes[0].label).toBe("S01E01 — The End and the Beginning");
    expect(work.seasons[0].episodes[1].label).toBe("S01E02");
  });
});

describe("mapResultsToTarget", () => {
  it("falls back to local translation and OCR when no file matches the language", () => {
    const results = [makeResult({ resultId: "r1", matchId: "m1", language: "zh" })];
    const targets = mapResultsToTarget(results, "m1", "en");
    expect(targets.map((t) => t.kind)).toEqual(["local", "ocr"]);
  });

  it("leads with ranked subtitle files and keeps the fallbacks last", () => {
    const results = [
      makeResult({ resultId: "second", matchId: "m1", language: "en", matchScore: 20 }),
      makeResult({ resultId: "first", matchId: "m1", language: "en", matchScore: 80 }),
    ];
    const targets = mapResultsToTarget(results, "m1", "en");
    expect(targets.map((t) => t.id)).toEqual(["first", "second", "__local__", "__ocr__"]);
    expect(targets.map((t) => t.recommended)).toEqual([true, true, false, false]);
  });

  it("puts a source that carries its own translation at the top", () => {
    const results = [
      makeResult({ resultId: "first", matchId: "m1", language: "en", matchScore: 80 }),
      makeResult({ resultId: "second", matchId: "m1", language: "en", matchScore: 20 }),
    ];
    const targets = mapResultsToTarget(results, "m1", "en", {
      sourceFileId: "src-1",
      fileName: "bilingual.srt",
      featureId: "m1",
      carriesTranslation: true,
      totalCues: 450,
      translatedCues: 442,
    });
    expect(targets[0].id).toBe("__source__");
    expect(targets[0].kind).toBe("source");
    expect(targets[0].note).toContain("442 of 450");
    expect(targets.map((t) => t.id)).toEqual([
      "__source__",
      "first",
      "second",
      "__local__",
      "__ocr__",
    ]);
  });

  it("offers nothing extra when the source carries no translation", () => {
    const results = [makeResult({ resultId: "first", matchId: "m1", language: "en" })];
    const targets = mapResultsToTarget(results, "m1", "en", {
      sourceFileId: "src-1",
      fileName: "plain.srt",
      featureId: "m1",
      carriesTranslation: false,
      totalCues: 450,
      translatedCues: 0,
    });
    expect(targets.map((t) => t.id)).toEqual(["first", "__local__", "__ocr__"]);
  });
});

describe("applyLanguageChoice", () => {
  it("reverses the pair when the chosen language is already on the other side", () => {
    expect(applyLanguageChoice({ source: "en", target: "zh" }, "source", "zh")).toEqual({
      source: "zh",
      target: "en",
    });
    expect(applyLanguageChoice({ source: "en", target: "zh" }, "target", "en")).toEqual({
      source: "zh",
      target: "en",
    });
  });

  it("reverses regardless of how the stored codes are cased", () => {
    expect(applyLanguageChoice({ source: "EN", target: "zh-TW" }, "source", "zh-tw")).toEqual({
      source: "zh-tw",
      target: "EN",
    });
  });

  it("leaves the other side alone for an unrelated language", () => {
    expect(applyLanguageChoice({ source: "en", target: "zh" }, "target", "ja")).toEqual({
      source: "en",
      target: "ja",
    });
  });
});

describe("mapResultsToSource", () => {
  it("ranks by match score, then provider rank, then downloads", () => {
    const results = [
      makeResult({ resultId: "weak", matchId: "m1", language: "en", matchScore: 10 }),
      makeResult({
        resultId: "popular",
        matchId: "m1",
        language: "en",
        matchScore: 90,
        downloadCount: 900,
      }),
      makeResult({
        resultId: "quiet",
        matchId: "m1",
        language: "en",
        matchScore: 90,
        downloadCount: 10,
      }),
      makeResult({
        resultId: "trusted",
        matchId: "m1",
        language: "en",
        matchScore: 90,
        providerRank: 1,
      }),
    ];
    expect(mapResultsToSource(results, "m1", "en").map((s) => s.id)).toEqual([
      "trusted",
      "popular",
      "quiet",
      "weak",
    ]);
  });

  it("recommends the top three entries", () => {
    const results = [1, 2, 3, 4].map((n) =>
      makeResult({ resultId: `r${n}`, matchId: "m1", language: "en", matchScore: 100 - n }),
    );
    expect(mapResultsToSource(results, "m1", "en").map((s) => s.recommended)).toEqual([
      true,
      true,
      true,
      false,
    ]);
  });

  it("does not recommend a lone result", () => {
    const results = [makeResult({ resultId: "r1", matchId: "m1", language: "en" })];
    expect(mapResultsToSource(results, "m1", "en")[0].recommended).toBe(false);
  });
});

const chosenTarget: BackendTargetAlignment = {
  result_id: "result-2",
  file_name: "target.srt",
  unpaired_cues: 12,
  unpaired_ms: 47_000,
  chosen: true,
};

describe("coverageLabel", () => {
  it("says what the target file leaves for the model before anything is written", () => {
    expect(coverageLabel(chosenTarget, null)).toBe("12 lines written on this device · 47s");
  });

  it("counts up while the model is writing them", () => {
    expect(coverageLabel(chosenTarget, { filled: 5, total: 12, active: true })).toBe(
      "writing 5 of 12 lines the file leaves blank…",
    );
  });

  it("says so once every line has an answer", () => {
    expect(coverageLabel(chosenTarget, { filled: 12, total: 12, active: false })).toBe(
      "every line answered",
    );
  });

  it("drops the seconds for a fill that stopped partway, which they no longer measure", () => {
    expect(coverageLabel(chosenTarget, { filled: 9, total: 12, active: false })).toBe(
      "3 of 12 blank lines still to write",
    );
  });

  it("names a file that answers every cue, which has no alignment to report", () => {
    expect(coverageLabel(null, null)).toBe("every line answered");
  });
});
