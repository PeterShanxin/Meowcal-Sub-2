export type SubtitleFormat = "srt" | "vtt";
export interface Cue {
  id: string;
  index: number;
  startMs: number;
  endMs: number;
  text: string;
  sourceLine: number;
  sequence?: string;
  identifier?: string;
  settings?: string;
}
export interface SubtitleDocument {
  filename: string;
  format: SubtitleFormat;
  cues: Cue[];
  hadBom: boolean;
  headerSuffix?: string;
  blocks: ({ kind: "cue"; id: string } | { kind: "note"; text: string })[];
}
export interface Issue {
  code: string;
  severity: "error" | "warning";
  cueIndices: number[];
  message: string;
}
export type Transform =
  | { offsetMs: number }
  | { anchors: [{ sourceMs: number; targetMs: number }, { sourceMs: number; targetMs: number }] };
export class SubtitleError extends Error {
  code: string;
  filename: string;
  line: number;
  column: number;
  constructor(code: string, message: string, { filename = "subtitle", line = 1, column = 1 } = {}) {
    super(`${filename}:${line}:${column}: ${message}`);
    this.name = "SubtitleError";
    this.code = code;
    this.filename = filename;
    this.line = line;
    this.column = column;
  }
}

export function fail(
  document: SubtitleDocument,
  code: string,
  message: string,
  line = 1,
  column = 1,
): never {
  throw new SubtitleError(code, message, { filename: document.filename, line, column });
}
