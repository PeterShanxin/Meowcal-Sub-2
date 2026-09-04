import { describe, expect, it } from "vitest";

import type { BackendResult, BackendWork } from "../lib/types";
import { applyLanguageChoice, mapResultsToTarget, mapWorksToItems } from "./mappers";

function makeWork(overrides: Partial<BackendWork> & Pick<BackendWork, "id" | "title" | "mediaType">): BackendWork {
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

function makeResult(overrides: Partial<BackendResult> & Pick<BackendResult, "resultId" | "matchId" | "language">): BackendResult {
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
  it("injects local and ocr synthetic targets around real files", () => {
    const results = [makeResult({ resultId: "r1", matchId: "m1", language: "zh" })];
    const targets = mapResultsToTarget(results, "m1", "en");
    expect(targets.map((t) => t.kind)).toEqual(["local", "ocr"]);
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
