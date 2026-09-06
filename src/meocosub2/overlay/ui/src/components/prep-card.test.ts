import { describe, expect, it } from "vitest";
import { coverageLabel } from "./prep-card";
import type { BackendTargetAlignment } from "../lib/types";

const chosen: BackendTargetAlignment = {
  result_id: "result-2",
  file_name: "target.srt",
  unpaired_cues: 12,
  unpaired_ms: 47_000,
  chosen: true,
};

describe("coverageLabel", () => {
  it("says what the target file leaves for the model before anything is written", () => {
    expect(coverageLabel(chosen, null)).toBe("12 lines written on this device · 47s");
  });

  it("counts up while the model is writing them", () => {
    expect(coverageLabel(chosen, { filled: 5, total: 12, active: true })).toBe(
      "writing 5 of 12 lines on this device…",
    );
  });

  it("says so once every line has an answer", () => {
    expect(coverageLabel(chosen, { filled: 12, total: 12, active: false })).toBe(
      "every line answered",
    );
  });

  it("drops the seconds for a fill that stopped partway, which they no longer measure", () => {
    expect(coverageLabel(chosen, { filled: 9, total: 12, active: false })).toBe(
      "3 lines of 12 still to write on this device",
    );
  });
});
