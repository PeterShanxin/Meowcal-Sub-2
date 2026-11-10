import { beforeEach, expect, test } from "vitest";
import type { BackendResult, BackendSnapshot, BackendWork } from "../lib/types";
import { store } from "./store";
import { selectionChangesPreparedWork } from "./mappers";

function snapshot(matchId: string, workId: string, files = ["source", "target"]): BackendSnapshot {
  const work: BackendWork = {
    id: workId,
    workId,
    title: "Paper Lanterns",
    mediaType: "movie",
    year: 2026,
    yearEnd: null,
    displayYear: "2026",
    imdbId: null,
    tmdbId: null,
    posterUrl: null,
    providers: [],
    providerLabels: [],
    primaryMatchId: matchId,
    expandable: false,
    totalEpisodes: 0,
    totalSubtitles: files.length,
    matchScore: 100,
    seasons: [],
    infoChips: [],
  };
  return {
    search_results: files.map((resultId) => ({ resultId, matchId }) as BackendResult),
    search_works: [work],
  } as BackendSnapshot;
}

beforeEach(() => {
  store.resetSelection();
  store.set({ snapshot: null });
});

test.each([null, "source"])(
  "selection follows stable files into an enriched catalog: %s",
  (source) => {
    store.set({
      snapshot: snapshot("provisional", "provisional-work"),
      selectedWorkId: "provisional-work",
      selectedEpisodeMatchId: "provisional",
      selectedSourceId: source,
      selectedTargetId: "target",
      tab: "target",
    });
    store.set({ snapshot: snapshot("identified", "identified-work") });
    expect(store.get()).toMatchObject({
      selectedWorkId: "identified-work",
      selectedEpisodeMatchId: "identified",
      selectedSourceId: source,
      selectedTargetId: "target",
      tab: "target",
    });
  },
);

test("a selected file identifies its group when an interim catalog splits", () => {
  store.set({
    snapshot: snapshot("interim", "interim-work"),
    selectedWorkId: "interim-work",
    selectedEpisodeMatchId: "interim",
    selectedSourceId: "source",
    selectedTargetId: "target",
  });
  const next = snapshot("source-match", "source-work", ["source"]);
  next.search_results.push({ resultId: "target", matchId: "other-match" } as BackendResult);
  store.set({ snapshot: next });
  expect(store.get()).toMatchObject({
    selectedEpisodeMatchId: "source-match",
    selectedWorkId: "source-work",
    selectedSourceId: "source",
    selectedTargetId: null,
  });
});

test("a retained source selection follows the file when it reappears in a catalog", () => {
  store.set({
    snapshot: snapshot("old-match", "old-work"),
    selectedEpisodeMatchId: "old-match",
    selectedSourceId: "source",
  });
  store.set({ snapshot: snapshot("unrelated", "unrelated-work", ["another-file"]) });
  store.set({ snapshot: snapshot("identified", "identified-work") });
  expect(store.get().selectedEpisodeMatchId).toBe("identified");
  expect(store.get().selectedSourceId).toBe("source");
});

test("unrelated new files do not replace a selection", () => {
  store.set({
    snapshot: snapshot("old-match", "old-work"),
    selectedEpisodeMatchId: "old-match",
    selectedWorkId: "old-work",
  });
  store.set({ snapshot: snapshot("other-match", "other-work", ["other-file"]) });
  expect(store.get().selectedEpisodeMatchId).toBe("old-match");
});

test("an explicit reset is not restored by a snapshot", () => {
  store.set({
    snapshot: snapshot("old-match", "old-work"),
    selectedEpisodeMatchId: "old-match",
  });
  store.set({ snapshot: snapshot("new-match", "new-work"), selectedEpisodeMatchId: null });
  expect(store.get().selectedEpisodeMatchId).toBeNull();
});

test("OCR source selection keeps its intent when its title becomes identified", () => {
  store.set({
    snapshot: snapshot("provisional", "provisional-work"),
    selectedEpisodeMatchId: "provisional",
    selectedSourceId: "__ocr_source__",
    selectedTargetId: "__local__",
  });
  store.set({ snapshot: snapshot("identified", "identified-work") });
  expect(store.get()).toMatchObject({
    selectedEpisodeMatchId: "identified",
    selectedSourceId: "__ocr_source__",
    selectedTargetId: "__local__",
  });
});

test("ambiguous regrouping without a chosen file does not guess a new title", () => {
  store.set({
    snapshot: snapshot("old-match", "old-work"),
    selectedEpisodeMatchId: "old-match",
  });
  const next = snapshot("one-match", "one-work", ["source"]);
  next.search_results.push({ resultId: "target", matchId: "other-match" } as BackendResult);
  store.set({ snapshot: next });
  expect(store.get().selectedEpisodeMatchId).toBe("old-match");
});

test("catalog identification does not replace the same prepared files", () => {
  const prepared = {
    feature_id: "provisional",
    source_file_id: "source",
    target_file_id: "target",
  };
  expect(selectionChangesPreparedWork(prepared, "identified", "source", "target")).toBe(false);
  expect(selectionChangesPreparedWork(prepared, "another", null, null)).toBe(true);
  expect(selectionChangesPreparedWork(prepared, "another", "other-source", "target")).toBe(true);
  expect(selectionChangesPreparedWork(prepared, "another", "source", "other-target")).toBe(true);
});

test("an identified OCR selection is retained but choosing a new title still replaces it", () => {
  const prepared = { feature_id: "provisional", source_file_id: null, target_file_id: null };
  expect(selectionChangesPreparedWork(prepared, "identified", "__ocr_source__", "__local__")).toBe(
    false,
  );
  expect(selectionChangesPreparedWork(prepared, "another", null, null)).toBe(true);
});

test("loading and an unchanged title do not replace a prepared work", () => {
  const prepared = { feature_id: "same", source_file_id: "source", target_file_id: "target" };
  expect(selectionChangesPreparedWork(null, "same", "source", "target")).toBe(false);
  expect(selectionChangesPreparedWork(prepared, null, "source", "target")).toBe(false);
  expect(selectionChangesPreparedWork(prepared, "same", "source", "target")).toBe(false);
});
