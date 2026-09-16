import type { Cue, Issue, SubtitleDocument, SubtitleFormat } from "./types";
export function settingsAreValid(settings: string) {
  if (settings.includes("-->")) return false;
  // Keep each setting verbatim. Unknown setting names are outside this subset.
  const seen = new Set();
  const percent = (value: string) =>
    /^\d+(?:\.\d+)?%$/.test(value) && Number(value.slice(0, -1)) <= 100;
  for (const token of settings
    .trim()
    .split(/[ \t]+/)
    .filter(Boolean)) {
    const split = token.indexOf(":");
    if (split < 1) return false;
    const key = token.slice(0, split);
    const value = token.slice(split + 1);
    if (seen.has(key)) return false;
    seen.add(key);
    const [position, alignment, extra] = value.split(",");
    if (extra !== undefined) return false;
    if (key === "vertical" && /^(rl|lr)$/.test(value)) continue;
    if (key === "align" && /^(start|center|end|left|right)$/.test(value)) continue;
    if (key === "size" && percent(value)) continue;
    if (
      key === "position" &&
      percent(position) &&
      (alignment === undefined || /^(line-left|center|line-right|auto)$/.test(alignment))
    )
      continue;
    if (
      key === "line" &&
      (/^-?\d+$/.test(position) || position === "auto" || percent(position)) &&
      (alignment === undefined || /^(start|center|end)$/.test(alignment))
    )
      continue;
    return false;
  }
  return true;
}

export function textRepresentationProblem(text: string, format: SubtitleFormat) {
  if (typeof text !== "string") return "Cue text must be a string.";
  if (/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(text))
    return "Cue text contains an incomplete Unicode character and cannot be encoded as UTF-8 without data loss.";
  if (text.includes("\0")) return "NUL characters cannot be stored in subtitles.";
  if (text.includes("\r")) return "Cue text contains a carriage return; use LF line endings.";
  if (text !== "" && text.split("\n").some((line) => line === ""))
    return "Blank lines inside cue text cannot be represented without splitting the cue.";
  if (text.trim() !== "" && text.split("\n").some((line) => /^[ \t]+$/.test(line)))
    return "Whitespace-only lines inside cue text may split cues in subtitle readers and are unsupported.";
  if (format === "vtt" && text.includes("-->")) return "WebVTT cue text cannot contain -->.";
  if (format === "srt" && text.split("\n").some((line) => /^\s*\d+[\d:,.]*\s*-->/.test(line))) {
    return "Cue text contains an ambiguous timing line; a cue separator may be missing.";
  }
  return null;
}

export function diagnose(document: SubtitleDocument): Issue[] {
  const issues: Issue[] = [];
  const add = (code: string, severity: Issue["severity"], cues: Cue[], message: string) =>
    issues.push({ code, severity, cueIndices: cues.map((cue) => cue.index), message });
  const valid: Cue[] = [];
  const duplicates = new Map<string, Cue[]>();
  const ids = new Set();
  for (let i = 0; i < document.cues.length; i++) {
    const cue = document.cues[i];
    if (typeof cue.text === "string" && cue.text.trim() === "")
      add("EMPTY_TEXT", "error", [cue], `Cue ${cue.index} has an empty body.`);
    const problem = textRepresentationProblem(cue.text, document.format);
    if (problem) add("UNREPRESENTABLE_TEXT", "error", [cue], `Cue ${cue.index}: ${problem}`);
    const timeValid =
      Number.isSafeInteger(cue.startMs) &&
      Number.isSafeInteger(cue.endMs) &&
      cue.startMs >= 0 &&
      cue.endMs > cue.startMs;
    if (!timeValid)
      add(
        "INVALID_INTERVAL",
        "error",
        [cue],
        `Cue ${cue.index} needs safe integer times with 0 <= start < end.`,
      );
    else valid.push(cue);
    if (i > 0 && Number.isFinite(cue.startMs) && cue.startMs < document.cues[i - 1].startMs) {
      add(
        "OUT_OF_ORDER",
        "warning",
        [document.cues[i - 1], cue],
        `Cue ${cue.index} starts before the preceding cue.`,
      );
    }
    const key = JSON.stringify([cue.startMs, cue.endMs, cue.text]);
    if (!duplicates.has(key)) duplicates.set(key, []);
    duplicates.get(key)?.push(cue);
    if (typeof cue.id !== "string" || !cue.id || ids.has(cue.id))
      add("INVALID_ID", "error", [cue], `Cue ${cue.index} must have a unique stable id.`);
    ids.add(cue.id);
    if (!Number.isSafeInteger(cue.index) || cue.index !== i + 1)
      add(
        "INVALID_SEQUENCE",
        "error",
        [cue],
        "Cue indices must match their original 1-based order.",
      );
    if (document.format === "vtt") {
      if (
        cue.identifier !== undefined &&
        (typeof cue.identifier !== "string" ||
          !cue.identifier ||
          /[\r\n]|-->/.test(cue.identifier) ||
          /^(NOTE|STYLE|REGION)(?:[ \t]|$)/.test(cue.identifier))
      )
        add(
          "INVALID_IDENTIFIER",
          "error",
          [cue],
          `Cue ${cue.index} has an unrepresentable WebVTT identifier.`,
        );
      if (
        typeof (cue.settings ?? "") !== "string" ||
        /[\r\n]/.test(cue.settings ?? "") ||
        ((cue.settings ?? "") !== "" && !/^[ \t]/.test(cue.settings ?? "")) ||
        !settingsAreValid(cue.settings ?? "")
      )
        add(
          "INVALID_SETTINGS",
          "error",
          [cue],
          `Cue ${cue.index} has unsupported or malformed WebVTT settings.`,
        );
    }
  }
  for (const group of duplicates.values()) {
    if (group.length > 1)
      add(
        "DUPLICATE",
        "warning",
        group,
        `${group.length} cues have identical start, end, and text.`,
      );
  }
  // Connected interval groups cover every overlap without enumerating O(n²) pairs.
  valid.sort((a, b) => a.startMs - b.startMs || a.endMs - b.endMs || a.index - b.index);
  let group: Cue[] = [];
  let end = -1;
  const finishGroup = () => {
    if (group.length > 1)
      add(
        "OVERLAP",
        "warning",
        [...group].sort((a, b) => a.index - b.index),
        `${group.length} cues form an overlapping time group (not every pair necessarily overlaps).`,
      );
  };
  for (const cue of valid) {
    if (cue.startMs >= end) {
      finishGroup();
      group = [];
      end = -1;
    }
    group.push(cue);
    end = Math.max(end, cue.endMs);
  }
  finishGroup();
  return issues;
}
