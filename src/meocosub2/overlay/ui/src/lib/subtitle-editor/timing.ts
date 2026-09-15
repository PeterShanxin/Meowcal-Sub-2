import {
  type SubtitleDocument,
  type SubtitleFormat,
  type Transform,
  SubtitleError,
  fail,
} from "./types";
const MAX_MS = BigInt(Number.MAX_SAFE_INTEGER);
const SRT_TIME = String.raw`\d{2,}:[0-5]\d:[0-5]\d,\d{3}`;
const VTT_TIME = String.raw`(?:\d{2,}:)?[0-5]\d:[0-5]\d\.\d{3}`;
export const timingPatterns = {
  srt: new RegExp(`^[ \\t]*(${SRT_TIME})[ \\t]+-->[ \\t]+(${SRT_TIME})[ \\t]*$`),
  vtt: new RegExp(`^[ \\t]*(${VTT_TIME})[ \\t]+-->[ \\t]+(${VTT_TIME})((?:[ \\t]+[^\\r\\n]*)?)$`),
};

export function parseTimestamp(value: string, format: SubtitleFormat) {
  if (typeof value !== "string" || !["srt", "vtt"].includes(format)) {
    throw new SubtitleError("INVALID_TIMESTAMP", "Expected a timestamp and srt or vtt format.");
  }
  const pattern = format === "srt" ? SRT_TIME : VTT_TIME;
  if (!new RegExp(`^${pattern}$`).test(value)) {
    throw new SubtitleError(
      "INVALID_TIMESTAMP",
      `Invalid ${format.toUpperCase()} timestamp: ${value}`,
    );
  }
  const parts = value.replace(",", ".").split(/[:.]/).map(BigInt);
  if (parts.length === 3) parts.unshift(0n);
  const [hours, minutes, seconds, millis] = parts;
  const result = ((hours * 60n + minutes) * 60n + seconds) * 1000n + millis;
  if (result > MAX_MS)
    throw new SubtitleError("INVALID_TIMESTAMP", "Timestamp exceeds the safe millisecond range.");
  return Number(result);
}

export function formatTimestamp(ms: number, format: SubtitleFormat = "vtt") {
  if (!Number.isSafeInteger(ms) || ms < 0 || !["srt", "vtt"].includes(format)) {
    throw new SubtitleError(
      "INVALID_TIMESTAMP",
      "Timestamp must be nonnegative safe integer milliseconds.",
    );
  }
  const time = BigInt(ms);
  const pad = (n: bigint, length = 2) => n.toString().padStart(length, "0");
  return `${pad(time / 3600000n)}:${pad((time / 60000n) % 60n)}:${pad((time / 1000n) % 60n)}${format === "srt" ? "," : "."}${pad(time % 1000n, 3)}`;
}

function roundRatio(numerator: bigint, denominator: bigint) {
  let quotient = numerator / denominator;
  let remainder = numerator % denominator;
  if (remainder < 0n) {
    quotient--;
    remainder += denominator;
  }
  return remainder * 2n >= denominator ? quotient + 1n : quotient;
}

export function transformSubtitle(document: SubtitleDocument, spec: Transform): SubtitleDocument {
  const invalid = (message: string, line = 1): never =>
    fail(document, "INVALID_TRANSFORM", message, line);
  if (!spec || typeof spec !== "object") invalid("Expected offsetMs or two anchors.");
  const hasOffset = Object.hasOwn(spec, "offsetMs");
  const hasAnchors = Object.hasOwn(spec, "anchors");
  if (hasOffset === hasAnchors) invalid("Provide exactly one of offsetMs or anchors.");
  let map: (time: number) => bigint;
  if ("offsetMs" in spec) {
    if (!Number.isSafeInteger(spec.offsetMs))
      invalid("Offset must be a safe integer number of milliseconds.");
    map = (time) => BigInt(time) + BigInt(spec.offsetMs);
  } else {
    if (
      !Array.isArray(spec.anchors) ||
      spec.anchors.length !== 2 ||
      spec.anchors.some(
        (a) => !a || !Number.isSafeInteger(a.sourceMs) || !Number.isSafeInteger(a.targetMs),
      )
    )
      invalid("Provide exactly two safe integer source/target anchors.");
    const [first, second] = spec.anchors;
    if (first.sourceMs >= second.sourceMs || first.targetMs >= second.targetMs)
      invalid("Both source and target anchors must be strictly increasing.");
    const source = BigInt(first.sourceMs);
    const target = BigInt(first.targetMs);
    const denominator = BigInt(second.sourceMs) - source;
    const numerator = BigInt(second.targetMs) - target;
    map = (time) =>
      roundRatio(target * denominator + (BigInt(time) - source) * numerator, denominator);
  }
  const cues = document.cues.map((cue) => {
    if (!Number.isSafeInteger(cue.startMs) || !Number.isSafeInteger(cue.endMs))
      invalid(`Cue ${cue.index} has unsafe input times.`, cue.sourceLine);
    const start = map(cue.startMs);
    const end = map(cue.endMs);
    if (start < 0n || end <= start || end > MAX_MS)
      invalid(`Cue ${cue.index} would have invalid times; no cues were changed.`, cue.sourceLine);
    return { ...cue, startMs: Number(start), endMs: Number(end) };
  });
  return { ...document, cues };
}
