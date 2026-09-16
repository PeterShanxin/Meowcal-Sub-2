import { type Cue, type SubtitleDocument, SubtitleError, fail } from "./types";
import { parseTimestamp, formatTimestamp, timingPatterns } from "./timing";
import { diagnose, settingsAreValid, textRepresentationProblem } from "./diagnostics";
export function parseSubtitle(source: string, { filename = "subtitle" } = {}): SubtitleDocument {
  const document: SubtitleDocument = {
    filename,
    format: "srt",
    cues: [],
    hadBom: false,
    blocks: [],
  };
  if (typeof source !== "string")
    fail(document, "INVALID_SOURCE", "Subtitle source must be decoded UTF-8 text.");
  document.hadBom = source.startsWith("\uFEFF");
  if (document.hadBom) source = source.slice(1);
  const normalized = source.replace(/\r\n/g, "\n");
  if (normalized.includes("\r")) {
    const prefix = normalized.slice(0, normalized.indexOf("\r")).split("\n");
    fail(
      document,
      "INVALID_LINE_ENDING",
      "Bare carriage returns are unsupported.",
      prefix.length,
      (prefix.at(-1)?.length ?? 0) + 1,
    );
  }
  const lines = normalized.split("\n");
  let cursor = 0;
  if (/^WEBVTT(?:[ \t]|$)/.test(lines[0])) {
    document.format = "vtt";
    document.headerSuffix = lines[0].slice(6);
    if (document.headerSuffix.includes("-->"))
      fail(document, "INVALID_HEADER", "WebVTT header cannot contain -->.");
    cursor = 1;
    if (cursor < lines.length && lines[cursor] !== "") {
      fail(
        document,
        "UNSUPPORTED_HEADER",
        "WebVTT header metadata is unsupported; expected a blank line.",
        cursor + 1,
      );
    }
  }
  while (cursor < lines.length) {
    while (cursor < lines.length && lines[cursor] === "") cursor++;
    if (cursor === lines.length) break;
    const blockStart = cursor;
    while (cursor < lines.length && lines[cursor] !== "") cursor++;
    const block = lines.slice(blockStart, cursor);
    if (document.format === "vtt" && /^NOTE(?:[ \t]|$)/.test(block[0])) {
      if (block.some((line) => line.includes("-->")))
        fail(document, "AMBIGUOUS_NOTE", "NOTE blocks cannot contain -->.", blockStart + 1);
      document.blocks.push({ kind: "note", text: block.join("\n") });
      continue;
    }
    if (document.format === "vtt" && /^(STYLE|REGION)(?:[ \t]|$)/.test(block[0])) {
      fail(
        document,
        "UNSUPPORTED_BLOCK",
        "WebVTT STYLE and REGION blocks are unsupported.",
        blockStart + 1,
      );
    }
    let timingOffset = 0;
    let identifier: string | undefined;
    let sequence: string | undefined;
    if (document.format === "srt") {
      if (!/^\d+$/.test(block[0]))
        fail(document, "INVALID_SEQUENCE", "Expected a numbered SRT cue.", blockStart + 1);
      sequence = block[0];
      timingOffset = 1;
    } else if (!block[0].includes("-->")) {
      identifier = block[0];
      timingOffset = 1;
    }
    const timingLine = block[timingOffset];
    const match =
      typeof timingLine === "string" ? timingPatterns[document.format].exec(timingLine) : null;
    const sourceLine = blockStart + timingOffset + 1;
    if (!match) fail(document, "INVALID_TIMING", "Expected a valid cue timing line.", sourceLine);
    let startMs: number;
    let endMs: number;
    try {
      startMs = parseTimestamp(match[1], document.format);
      endMs = parseTimestamp(match[2], document.format);
    } catch (error) {
      if (!(error instanceof SubtitleError)) throw error;
      fail(document, error.code, "Cue timestamp exceeds the safe millisecond range.", sourceLine);
    }
    const settings = document.format === "vtt" ? match[3] : undefined;
    if (document.format === "vtt" && !settingsAreValid(settings ?? ""))
      fail(
        document,
        "INVALID_SETTINGS",
        "Unsupported or malformed WebVTT timing settings.",
        sourceLine,
        timingLine.indexOf(match[2]) + match[2].length + 1,
      );
    const text = block.slice(timingOffset + 1).join("\n");
    const problem = textRepresentationProblem(text, document.format);
    if (problem) {
      const badOffset = block
        .slice(timingOffset + 1)
        .findIndex(
          (line) => /^[ \t]+$/.test(line) || textRepresentationProblem(line, document.format),
        );
      fail(document, "AMBIGUOUS_TEXT", problem, sourceLine + 1 + Math.max(badOffset, 0));
    }
    const index = document.cues.length + 1;
    const cue: Cue = { id: `cue-${index}`, index, startMs, endMs, text, sourceLine };
    if (sequence !== undefined) cue.sequence = sequence;
    if (identifier !== undefined) cue.identifier = identifier;
    if (settings !== undefined) cue.settings = settings;
    document.cues.push(cue);
    document.blocks.push({ kind: "cue", id: cue.id });
  }
  if (!document.cues.length)
    fail(
      document,
      "EMPTY_DOCUMENT",
      "No subtitles found. A playback track needs at least one subtitle.",
    );
  return document;
}

export function serializeSubtitle(document: SubtitleDocument): string {
  const errors = diagnose(document).filter((issue) => issue.severity === "error");
  if (errors.length) fail(document, "SEMANTIC_ERROR", `Export blocked: ${errors[0].message}`);
  if (!["srt", "vtt"].includes(document.format))
    fail(document, "SEMANTIC_ERROR", "Unsupported document format.");
  const renderCue = (cue: Cue) => {
    const timing = `${formatTimestamp(cue.startMs, document.format)} --> ${formatTimestamp(cue.endMs, document.format)}${document.format === "vtt" ? (cue.settings ?? "") : ""}`;
    const prefix =
      document.format === "srt"
        ? `${cue.index}\n`
        : cue.identifier === undefined
          ? ""
          : `${cue.identifier}\n`;
    return `${prefix}${timing}\n${cue.text}`;
  };
  let body: string;
  if (document.format === "vtt") {
    const headerSuffix = document.headerSuffix ?? "";
    if (
      typeof headerSuffix !== "string" ||
      /[\r\n]|-->/.test(headerSuffix) ||
      (headerSuffix !== "" && !/^[ \t]/.test(headerSuffix))
    )
      fail(document, "SEMANTIC_ERROR", "Invalid WebVTT header suffix.");
    const blocks =
      document.blocks ?? document.cues.map((cue) => ({ kind: "cue" as const, id: cue.id }));
    const byId = new Map(document.cues.map((cue) => [cue.id, cue]));
    const cueOrder = blocks.filter((block) => block.kind === "cue").map((block) => block.id);
    if (
      cueOrder.length !== document.cues.length ||
      cueOrder.some((id, i) => id !== document.cues[i].id)
    )
      fail(document, "SEMANTIC_ERROR", "WebVTT block order does not match cue order.");
    const rendered = blocks.map((block) => {
      if (block.kind === "cue") return renderCue(byId.get(block.id) as Cue);
      if (
        block.kind !== "note" ||
        typeof block.text !== "string" ||
        !/^NOTE(?:[ \t]|\n|$)/.test(block.text) ||
        /\r|-->|\n\n/.test(block.text) ||
        block.text.endsWith("\n")
      )
        fail(document, "SEMANTIC_ERROR", "Invalid preserved WebVTT NOTE block.");
      return block.text;
    });
    body = `WEBVTT${headerSuffix}\n\n${rendered.join("\n\n")}${rendered.length ? "\n" : ""}`;
  } else {
    body = `${document.cues.map(renderCue).join("\n\n")}\n`;
  }
  return `${document.hadBom ? "\uFEFF" : ""}${body}`;
}
