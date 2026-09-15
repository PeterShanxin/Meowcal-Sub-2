import { describe, expect, it } from "vitest";
import { diagnose } from "./diagnostics";
import { parseSubtitle, serializeSubtitle } from "./document";
import { formatTimestamp, parseTimestamp, transformSubtitle } from "./timing";
import type { SubtitleDocument } from "./types";

const srt =
  "01\r\n00:00:01,000 --> 00:00:02,000\r\n你好 🐱\r\n  second line  \r\n\r\n7\r\n00:00:03,000 --> 00:00:04,000\r\nlast\r\n";
const vtt =
  "WEBVTT - test\n\nNOTE before\n猫\n\nintro\n00:01.005 --> 00:02.006  align:start position:10%,line-left\n你好\n第二行\n\nNOTE between\n\n00:03.000 --> 00:04.000\nend\n\nNOTE after\n";

describe("subtitle document", () => {
  it("preserves BOM, whitespace and Unicode while normalizing line endings and SRT numbering", () => {
    const doc = parseSubtitle(`\uFEFF${srt}`, { filename: "中文.srt" });
    expect(doc.cues[0].text).toBe("你好 🐱\n  second line  ");
    expect(doc.cues[0].sequence).toBe("01");
    expect(diagnose(doc)).toEqual([]);
    expect(serializeSubtitle(doc)).toBe(
      `\uFEFF${srt.replaceAll("\r\n", "\n").replace(/^01\n/, "1\n").replace(/\n7\n/, "\n2\n")}`,
    );
  });
  it("preserves VTT identifiers, notes, exact settings and header through editing and retiming", () => {
    const doc = parseSubtitle(vtt);
    const output = serializeSubtitle(transformSubtitle(doc, { offsetMs: 100 }));
    expect(output).toContain(
      "intro\n00:00:01.105 --> 00:00:02.106  align:start position:10%,line-left\n你好\n第二行",
    );
    const parsed = parseSubtitle(output);
    expect(parsed.blocks).toEqual(doc.blocks);
    expect(parsed.headerSuffix).toBe(" - test");
    expect(parsed.cues.map((cue) => cue.text)).toEqual(doc.cues.map((cue) => cue.text));
  });
  it.each([
    "WEBVTT\nLanguage: en\n\n00:00.000 --> 00:01.000\nhi",
    "WEBVTT\n\nNOTE no cues\n",
    "WEBVTT\n\nSTYLE\n::cue { color:red }",
    "WEBVTT\n\nREGION\nid:r1",
    "WEBVTT\n\nNOTE x\n00:00.000 --> 00:01.000\nhi",
    "WEBVTT\n\n00:00.000 --> 00:01.000 garbage\nhi",
    "1\n00:00:01,000 --> 00:00:02,000\na\n2\n00:00:03,000 --> 00:00:04,000\nb",
    "1\n00:00:01.000 --> 00:00:02.000\na",
    "1\r00:00:01,000 --> 00:00:02,000\ra",
    "1\n00:00:01,000 --> 00:00:02,000\na\n \nb",
    "no subtitles",
  ])("rejects unsupported or ambiguous syntax with file and line", (source) => {
    expect(() => parseSubtitle(source, { filename: "broken.srt" })).toThrow(/broken.srt:\d+:\d+:/);
  });
  it.each(["", "   "])("keeps empty cues available for repair, blocks export: %j", (text) => {
    const doc = parseSubtitle(`1\n00:00:01,000 --> 00:00:02,000\n${text}\n`);
    expect(diagnose(doc).some((issue) => issue.code === "EMPTY_TEXT")).toBe(true);
    expect(() => serializeSubtitle(doc)).toThrow("Export blocked");
    expect(transformSubtitle(doc, { offsetMs: 1 }).cues[0].text).toBe(text);
  });
  it.each([
    "a\n\nb",
    "\na",
    "a\n",
    "a\rb",
    "a\n \nb",
    "unfinished \uD800",
    "\uDC00",
    "a\0b",
    "00:00:01,000 --> 00:00:02,000",
  ])("blocks lossy edited text %j", (text) => {
    const doc = parseSubtitle(srt);
    doc.cues[0].text = text;
    expect(() => serializeSubtitle(doc)).toThrow("Export blocked");
  });
  it("blocks ambiguous VTT payload and corrupted export metadata", () => {
    const mutations: ((doc: SubtitleDocument) => void)[] = [
      (doc) => {
        doc.cues.reverse();
      },
      (doc) => {
        doc.cues[0].identifier = "NOTE reserved";
      },
      (doc) => {
        doc.cues[0].settings = "align:start";
      },
      (doc) => {
        doc.cues[0].settings = " align:start align:end";
      },
      (doc) => {
        doc.cues[0].text = "a --> b";
      },
      (doc) => {
        doc.blocks = [];
      },
      (doc) => {
        doc.blocks[0] = { kind: "note", text: "NOTE\n\nbody" };
      },
      (doc) => {
        doc.headerSuffix = "\nLanguage: en";
      },
    ];
    for (const mutate of mutations) {
      const doc = parseSubtitle(vtt);
      mutate(doc);
      expect(() => serializeSubtitle(doc)).toThrow();
    }
  });
  it.each([
    " vertical:rl line:-1,end position:25.5%,line-right size:80% align:center",
    "\tvertical:lr\tline:auto position:0%,auto align:left",
    " line:100%,start position:100%,center align:right",
  ])("preserves supported VTT settings %s", (settings) => {
    const doc = parseSubtitle(`WEBVTT\n\n00:00.000 --> 00:01.000${settings}\ntext`);
    expect(diagnose(doc)).toEqual([]);
    expect(parseSubtitle(serializeSubtitle(doc)).cues[0].settings).toBe(settings);
  });
  it.each([
    " line:foo",
    " position:101%",
    " vertical:down",
    " bogus:yes",
    " size:10% size:20%",
    " line:1,bottom",
    " position:1%,center,auto",
  ])("rejects malformed settings %s", (settings) => {
    expect(() => parseSubtitle(`WEBVTT\n\n00:00.000 --> 00:01.000${settings}\ntext`)).toThrow();
  });
  it("round trips safe integer timestamp boundaries", () => {
    for (const format of ["srt", "vtt"] as const) {
      for (const ms of [0, 1, 59999, 60000, 3600000, Number.MAX_SAFE_INTEGER])
        expect(parseTimestamp(formatTimestamp(ms, format), format)).toBe(ms);
      for (const ms of [-1, 1.1, NaN, Infinity])
        expect(() => formatTimestamp(ms, format)).toThrow();
    }
    for (const value of [
      "1:02.345",
      "60:02.345",
      "00:60.000",
      "00:00,000",
      "00:00.1",
      "99999999999999:00:00.000",
    ])
      expect(() => parseTimestamp(value, "vtt")).toThrow();
  });
});
