import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { checkSource, readStaticCatalog, validateCatalog } from "./coverage";
import chinese from "./en-zh.json";
import messageChinese from "./messages-zh.json";

const keys = new Set(["Retry", "Retry {count}", "Could not save {file}."]);
const canonical = (key: string): string => key.replace(/\{\w+\}/g, "{}");
const known = (key: string): boolean =>
  keys.has(key) || [...keys].some((entry) => canonical(entry) === key);
const check = (source: string, path = "src/example.tsx"): string[] =>
  checkSource(path, source, known);

describe("translation coverage gate", () => {
  it("accepts translated text, data and invariant names", () => {
    expect(
      check(`<button title={t("Retry")} aria-label={t("Retry")}>{t("Retry")}</button>`),
    ).toEqual([]);
    expect(
      check(`<p>{subtitle} {file.name}</p><Kbd>Tab</Kbd><option>简体中文</option><b>PP-OCRv6</b>`),
    ).toEqual([]);
    expect(check(`<Field label={t("Retry")} hint={busy ? t("Retry") : null} />`)).toEqual([]);
  });

  it("fails visible text that bypasses t()", () => {
    expect(check("<button>Retry</button>")).toEqual([
      'src/example.tsx:1: untranslated text "Retry"',
    ]);
    expect(check(`<button>{busy ? "Wait" : t("Retry")}</button>`)).toHaveLength(1);
    expect(check(`<p>{\`\${count} lines\`}</p>`)).toHaveLength(1);
    expect(check(`<Field label="API key" />`)).toHaveLength(1);
    expect(check(`<input placeholder="Search" aria-label={"Search"} />`)).toHaveLength(2);
    expect(check(`const row = { id: "x", label: "Movie", note: \`\${n} lines\` };`)).toHaveLength(
      2,
    );
    expect(check(`<span><Kbd dim>Tab</Kbd> switch</span>`)).toHaveLength(1);
  });

  it("fails a t() key the catalog does not have", () => {
    expect(check(`t("Missing"); t(\`Missing too\`);`)).toEqual([
      'src/example.tsx:1: missing translation "Missing"',
      'src/example.tsx:1: missing translation "Missing too"',
    ]);
  });

  it("requires messages kept for later display to be catalogued", () => {
    expect(check(`setError("Retry"); throw new Error(\`Could not save \${name}.\`);`)).toEqual([]);
    expect(check(`setError("Unknown failure");`)).toHaveLength(1);
    expect(check(`throw new Error(\`Lost \${name}.\`);`)).toHaveLength(1);
    expect(check(`store.set({ error: "Unknown failure" });`)).toHaveLength(1);
    expect(check(`fail(document, "INVALID_CODE", "Unknown failure", 3);`)).toEqual([
      'src/example.tsx:1: uncatalogued message "Unknown failure"',
    ]);
  });

  it("checks static markup and plain scripts", () => {
    expect(
      checkSource(
        "static/page.html",
        `<head><title>Raw</title></head><!-- <p>Old</p> -->\n<p data-i18n="Retry">Retry</p><button title="Close">×</button>`,
        known,
      ),
    ).toEqual(['static/page.html:2: untranslated title "Close"']);
    expect(
      checkSource("static/page.html", `<p>Loading</p><p data-i18n="Gone"></p>`, known),
    ).toEqual([
      'static/page.html:1: untranslated text "Loading"',
      'static/page.html:1: missing translation "Gone"',
    ]);
    expect(
      checkSource("static/page.js", `label.textContent = "Loading"; t("Retry");`, known),
    ).toHaveLength(1);
  });

  it("requires both languages to name the same placeholders", () => {
    expect(validateCatalog([["a", "Hi {name}", "你好 {name}"]])).toEqual([]);
    expect(
      validateCatalog([
        ["a", "Hi {name}", "你好 {value}"],
        ["b", "Hi", " "],
      ]),
    ).toHaveLength(2);
  });

  it("reads the static catalog as data without running it", () => {
    const parsed = readStaticCatalog(
      `throw new Error("never runs"); const messages = { "a.b": { en: "Retry", "zh-CN": "重试" } };`,
    );
    expect(parsed).toEqual({ "a.b": { en: "Retry", "zh-CN": "重试" } });
    expect(() => readStaticCatalog("const messages = { ...other };")).toThrow();
    expect(() => readStaticCatalog("const other = {};")).toThrow();
  });
});

describe("the studio and static pages", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const ui = join(here, "..", "..");
  const pages = join(ui, "..", "static");
  const read = (path: string): string => readFileSync(path, "utf8");
  const studioKeys = new Set(Object.keys(chinese));
  const studioKnown = (key: string): boolean => studioKeys.has(key);
  const messageKeys = new Set(Object.keys(messageChinese).map(canonical));
  const messageKnown = (key: string): boolean => messageKeys.has(canonical(key));
  const staticCatalog = readStaticCatalog(read(join(pages, "i18n.js")));

  it("translates every catalogued message completely", () => {
    const entries = [
      ...[...Object.entries(chinese), ...Object.entries(messageChinese)].map(
        ([en, zh]): [string, string, string] => [en, en, zh],
      ),
      ...Object.entries(staticCatalog).map(([key, message]): [string, string, string] => [
        key,
        message.en,
        message["zh-CN"],
      ]),
    ];
    expect(validateCatalog(entries)).toEqual([]);
  });

  it("routes all interface text through the catalogs", () => {
    const studio = readdirSync(join(ui, "src"), { recursive: true })
      .map(String)
      .filter((name) => /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name))
      .filter((name) => !name.startsWith("i18n"));
    const problems = studio.flatMap((name) =>
      checkSource(`src/${name}`, read(join(ui, "src", name)), studioKnown, messageKnown),
    );
    problems.push(...checkSource("index.html", read(join(ui, "index.html")), studioKnown));
    for (const name of [
      "splash.html",
      "selector.html",
      "overlay.html",
      "selector.js",
      "overlay.js",
    ]) {
      problems.push(
        ...checkSource(`static/${name}`, read(join(pages, name)), (key) =>
          Object.hasOwn(staticCatalog, key),
        ),
      );
    }
    expect(problems).toEqual([]);
  });
});
