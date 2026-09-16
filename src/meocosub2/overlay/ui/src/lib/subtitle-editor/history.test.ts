import { expect, it } from "vitest";
import { diagnose } from "./diagnostics";
import { parseSubtitle } from "./document";
import { applyPreview, createHistory, editCue, integerMs, preview, redo, undo } from "./history";
import { transformSubtitle } from "./timing";
import type { SubtitleDocument, Transform } from "./types";

function withTimes(times: [number, number, string?][]): SubtitleDocument {
  return {
    filename: "test.srt",
    format: "srt",
    hadBom: false,
    blocks: [],
    cues: times.map(([startMs, endMs, text = "text"], i) => ({
      id: `cue-${i + 1}`,
      index: i + 1,
      startMs,
      endMs,
      text,
      sourceLine: 1,
    })),
  };
}
it("finds complete nested overlap groups, duplicates and disorder, allowing touching cues", () => {
  const issues = diagnose(
    withTimes([
      [20, 30, "same"],
      [0, 100],
      [20, 30, "same"],
      [100, 110],
      [110, 120],
    ]),
  );
  expect(issues.find((issue) => issue.code === "OVERLAP")?.cueIndices).toEqual([1, 2, 3]);
  expect(issues.find((issue) => issue.code === "DUPLICATE")?.cueIndices).toEqual([1, 3]);
  expect(issues.find((issue) => issue.code === "OUT_OF_ORDER")?.cueIndices).toEqual([1, 2]);
  expect(
    diagnose(
      withTimes([
        [0, 10],
        [10, 20],
        [20, 30],
      ]),
    ),
  ).toEqual([]);
});
it("groups 5000 overlapping cues without enumerating pairs", () => {
  const issues = diagnose(
    withTimes(Array.from({ length: 5000 }, (_, i) => [i, 10000, `cue ${i}`])),
  );
  expect(issues).toHaveLength(1);
  expect(issues[0].cueIndices).toHaveLength(5000);
});
it("transforms both endpoints exactly with ties upward and extrapolation", () => {
  const doc = withTimes([
    [1, 3],
    [3, 6],
    [7, 9],
  ]);
  const before = structuredClone(doc);
  expect(
    transformSubtitle(doc, {
      anchors: [
        { sourceMs: 0, targetMs: 0 },
        { sourceMs: 10, targetMs: 5 },
      ],
    }).cues.map((cue) => [cue.startMs, cue.endMs]),
  ).toEqual([
    [1, 2],
    [2, 3],
    [4, 5],
  ]);
  expect(doc).toEqual(before);
  const max = Number.MAX_SAFE_INTEGER;
  expect(
    transformSubtitle(withTimes([[0, max - 1]]), {
      anchors: [
        { sourceMs: -max, targetMs: -max },
        { sourceMs: max, targetMs: max },
      ],
    }).cues[0].endMs,
  ).toBe(max - 1);
  expect(
    transformSubtitle(withTimes([[5, 15]]), {
      anchors: [
        { sourceMs: 10, targetMs: 20 },
        { sourceMs: 20, targetMs: 40 },
      ],
    }).cues.map((cue) => [cue.startMs, cue.endMs]),
  ).toEqual([[10, 30]]);
});
it.each([
  undefined,
  {},
  { offsetMs: 0.5 },
  { offsetMs: NaN },
  { offsetMs: Number.MAX_SAFE_INTEGER + 1 },
  { offsetMs: 0, anchors: [] },
  { anchors: [] },
  {
    anchors: [
      { sourceMs: 0, targetMs: 0 },
      { sourceMs: 0, targetMs: 1 },
    ],
  },
  {
    anchors: [
      { sourceMs: 0, targetMs: 1 },
      { sourceMs: 1, targetMs: 0 },
    ],
  },
  {
    anchors: [
      { sourceMs: 0, targetMs: 0 },
      { sourceMs: 10, targetMs: 1 },
    ],
  },
  { offsetMs: -1 },
])("rejects invalid transforms atomically: %j", (spec) => {
  const doc = withTimes([
    [0, 1],
    [10, 20],
  ]);
  expect(() => transformSubtitle(doc, spec as Transform)).toThrow();
  expect(doc.cues.map((cue) => [cue.startMs, cue.endMs])).toEqual([
    [0, 1],
    [10, 20],
  ]);
});
it("keeps histories independent and previews relative to current state, with undo and redo", () => {
  const doc = parseSubtitle("1\n00:00:01,000 --> 00:00:02,000\nhello\n");
  const a = createHistory(doc);
  const b = createHistory(doc);
  expect(undo(a)).toBe(a);
  expect(redo(a)).toBe(a);
  expect(editCue(a, 0, doc.cues[0])).toBe(a);
  const once = preview(a, { offsetMs: 500 });
  const twice = preview(once, { offsetMs: 500 });
  expect(twice.preview?.cues[0].startMs).toBe(1500);
  expect(twice.past).toHaveLength(0);
  const applied = applyPreview(twice);
  expect(applied.present.cues[0].startMs).toBe(1500);
  expect(applied.preview).toBeNull();
  expect(undo(applied).present).toBe(doc);
  expect(redo(undo(applied)).present).toBe(applied.present);
  expect(b.present.cues[0].startMs).toBe(1000);
  const edited = editCue(undo(applied), 0, { ...doc.cues[0], text: "new" });
  expect(edited.future).toHaveLength(0);
  expect(edited.present.cues[0].id).toBe(doc.cues[0].id);
  expect(() => applyPreview(edited)).toThrow();
  expect(() => editCue(a, 99, doc.cues[0])).toThrow();
  expect(() => editCue(a, 0, { ...doc.cues[0], startMs: 0.5 })).toThrow();
});
it("bounds history and refuses empty, fractional or unsafe millisecond input", () => {
  let state = createHistory(withTimes([[0, 1000]]));
  for (let i = 1; i <= 60; i++)
    state = editCue(state, 0, { startMs: i, endMs: 1000, text: `line ${i}` });
  expect(state.past).toHaveLength(50);
  expect(integerMs("-250")).toBe(-250);
  for (const value of ["", " ", "1.5", "1e3", "NaN", "9007199254740992"])
    expect(() => integerMs(value)).toThrow();
});
