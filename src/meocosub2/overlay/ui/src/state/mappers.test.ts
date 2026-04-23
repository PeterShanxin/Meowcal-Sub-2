import { describe, expect, it } from "vitest";

import type { BackendMatch, BackendResult } from "../lib/types";
import { mapMatchesToTitles, mapResultsToTarget } from "./mappers";

function makeMatch(overrides: Partial<BackendMatch> & Pick<BackendMatch, "matchId" | "title">): BackendMatch {
  const { matchId, title, ...rest } = overrides;
  return {
    id: matchId,
    matchId,
    title,
    year: null,
    imdbId: null,
    tmdbId: null,
    mediaType: "tvshow",
    season: null,
    episode: null,
    parentTitle: null,
    subtitlesCount: 0,
    matchScore: 0,
    providerCount: 1,
    providers: ["opensubtitles"],
    providerLabels: ["OpenSubtitles"],
    displayLabel: title,
    ...rest,
  };
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

describe("mapMatchesToTitles", () => {
  it("promotes and badges the Overlord-style entry with both source and target files", () => {
    const matches = [
      makeMatch({ matchId: "movie", title: "Overlord", year: 2018, mediaType: "movie", subtitlesCount: 384, matchScore: 492 }),
      makeMatch({ matchId: "anime", title: "オーバーロード", year: 2015, mediaType: "tvshow", subtitlesCount: 61, matchScore: 124 }),
      makeMatch({
        matchId: "episode",
        title: "overlord",
        year: 2015,
        mediaType: "episode",
        season: 2,
        episode: 4,
        parentTitle: "Manhattan",
        subtitlesCount: 43,
        matchScore: 486,
      }),
    ];
    const results = [
      makeResult({ resultId: "anime-zh", matchId: "anime", language: "zh" }),
      makeResult({ resultId: "anime-en", matchId: "anime", language: "en" }),
      makeResult({ resultId: "movie-en", matchId: "movie", language: "en" }),
    ];

    const titles = mapMatchesToTitles(matches, results, "zh", "en");

    expect(titles[0].id).toBe("anime");
    expect(titles[0].isRecommended).toBe(true);
    expect(titles[0].sourceCount).toBe(1);
    expect(titles[0].targetCount).toBe(1);
    expect(titles.filter((item) => item.isRecommended)).toHaveLength(1);
  });

  it("chooses the best eligible title by readiness score before match score", () => {
    const matches = [
      makeMatch({ matchId: "balanced", title: "Balanced", matchScore: 200 }),
      makeMatch({ matchId: "lopsided", title: "Lopsided", matchScore: 260 }),
    ];
    const results = [
      makeResult({ resultId: "balanced-zh-1", matchId: "balanced", language: "zh" }),
      makeResult({ resultId: "balanced-zh-2", matchId: "balanced", language: "zh" }),
      makeResult({ resultId: "balanced-en-1", matchId: "balanced", language: "en" }),
      makeResult({ resultId: "balanced-en-2", matchId: "balanced", language: "en" }),
      makeResult({ resultId: "lopsided-zh-1", matchId: "lopsided", language: "zh" }),
      makeResult({ resultId: "lopsided-zh-2", matchId: "lopsided", language: "zh" }),
      makeResult({ resultId: "lopsided-zh-3", matchId: "lopsided", language: "zh" }),
      makeResult({ resultId: "lopsided-en-1", matchId: "lopsided", language: "en" }),
    ];

    const titles = mapMatchesToTitles(matches, results, "zh", "en");

    expect(titles[0].id).toBe("balanced");
    expect(titles[0].isRecommended).toBe(true);
    expect(titles[1].isRecommended).toBe(false);
  });

  it("keeps backend order and shows no badge when no title has both sides", () => {
    const matches = [
      makeMatch({ matchId: "source-only", title: "Source Only", matchScore: 300 }),
      makeMatch({ matchId: "target-only", title: "Target Only", matchScore: 200 }),
    ];
    const results = [
      makeResult({ resultId: "source-only-zh", matchId: "source-only", language: "zh" }),
      makeResult({ resultId: "target-only-en", matchId: "target-only", language: "en" }),
    ];

    const titles = mapMatchesToTitles(matches, results, "zh", "en");

    expect(titles.map((item) => item.id)).toEqual(["source-only", "target-only"]);
    expect(titles.every((item) => item.isRecommended === false)).toBe(true);
  });

  it("does not count local or ocr target options as recommendation coverage", () => {
    const matches = [makeMatch({ matchId: "source-only", title: "Source Only", matchScore: 300 })];
    const results = [makeResult({ resultId: "source-only-zh", matchId: "source-only", language: "zh" })];

    const targets = mapResultsToTarget(results, "source-only", "en");
    const titles = mapMatchesToTitles(matches, results, "zh", "en");

    expect(targets.map((item) => item.kind)).toEqual(["local", "ocr"]);
    expect(titles[0].targetCount).toBe(0);
    expect(titles[0].isRecommended).toBe(false);
  });
});
