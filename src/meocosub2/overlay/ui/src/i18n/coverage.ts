import ts from "typescript";

/**
 * Finds interface text that bypasses translation.
 *
 * Studio sources are read as TypeScript: visible JSX text, accessibility
 * attributes, rendered literals and every literal `t()` key. The hand-written
 * static pages are read as markup (`data-i18n` keys) and plain scripts (`t()`
 * keys and literal `textContent`). Text computed at runtime, such as subtitles,
 * file names and titles, is data and is not inspected.
 */

// Names, units, key caps, format examples and language endonyms read the same
// in both languages. Single letters are key caps.
export const INVARIANT_TEXT = new Set([
  "Windows",
  "Aa",
  "sk-xxx",
  "tmdb-v3-key",
  "en",
  "en-US",
  "zh-TW",
  "English",
  "简体中文",
  "OpenSubtitles",
  "OpenSubtitles.com",
  "SubDL",
  "ASSRT",
  "TMDb",
  "IMDb",
  "PP-OCRv6",
  "HY-MT1.5",
  "SRT",
  "WebVTT",
  "OCR",
  "AI",
  "API",
  "GitHub",
  "Tab",
  "Esc",
  "Enter",
  "Space",
  "Shift",
  "Ctrl",
  "Alt",
  "ms",
  "px",
  "MB",
  "GB",
  "×",
]);

// Attributes and component props that reach the screen or a screen reader.
const VISIBLE_ATTRIBUTES = new Set([
  "aria-label",
  "title",
  "placeholder",
  "alt",
  "label",
  "hint",
  "eyebrow",
  "note",
  "detail",
  "description",
]);
// Object fields that hold display copy, such as `{ label: "Compact" }`.
const VISIBLE_FIELDS = new Set(["label", "title", "hint", "note", "detail", "description", "text"]);
const VISIBLE_PROPERTIES = new Set(["textContent", "title", "placeholder", "ariaLabel"]);
// Messages kept in English until they are shown, where they are localized
// together with the backend's. Their wording must still be catalogued.
// The value is the index of the message argument.
const MESSAGE_CALLS = new Map([
  ["Error", 0],
  ["setError", 0],
  ["setNotice", 0],
  ["onError", 0],
  ["invalid", 0],
  ["fail", 2], // fail(document, code, message, line?)
  ["SubtitleError", 1], // new SubtitleError(code, message)
  ["add", 3], // add(code, severity, cues, message)
]);
const MESSAGE_FIELDS = new Set(["error", "message"]);
const expressionMarker = "";

const normalize = (text: string): string =>
  text.replaceAll(expressionMarker, " ").replace(/\s+/g, " ").trim();

function needsTranslation(text: string): boolean {
  const normalized = normalize(text);
  if (!/\p{L}/u.test(normalized) || INVARIANT_TEXT.has(normalized)) return false;
  // A run of key caps or symbols around invariant words, such as "⇧ Tab".
  return normalized
    .split(/[^\p{L}\d.-]+/u)
    .some((word) => /\p{L}/u.test(word) && word.length > 1 && !INVARIANT_TEXT.has(word));
}

/**
 * `hasKey` answers for t() and data-i18n keys; `hasMessage` for messages kept
 * in English until they are shown, where `{}` stands for a formatted value.
 */
export function checkSource(
  path: string,
  source: string,
  hasKey: (key: string) => boolean,
  hasMessage: (key: string) => boolean = hasKey,
): string[] {
  return path.endsWith(".html")
    ? checkMarkup(path, source, hasKey, hasMessage)
    : checkScript(path, source, hasKey, hasMessage);
}

function checkScript(
  path: string,
  source: string,
  hasKey: (key: string) => boolean,
  hasMessage: (key: string) => boolean,
): string[] {
  const problems: string[] = [];
  const kind = path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const file = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, kind);
  const lineOf = (node: ts.Node): number =>
    file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1;
  const reportText = (text: string, node: ts.Node): void => {
    if (needsTranslation(text)) {
      problems.push(
        `${path}:${lineOf(node)}: untranslated text ${JSON.stringify(normalize(text))}`,
      );
    }
  };

  // Template literals are checked against catalog templates: `${x}` reads as `{}`.
  function catalogued(node: ts.Expression): void {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      if (needsTranslation(node.text) && !hasMessage(node.text)) {
        problems.push(`${path}:${lineOf(node)}: uncatalogued message ${JSON.stringify(node.text)}`);
      }
    } else if (ts.isTemplateExpression(node)) {
      const text = [node.head.text, ...node.templateSpans.map((span) => span.literal.text)];
      const template = text.join("{}");
      if (needsTranslation(text.join(" ")) && !hasMessage(template)) {
        problems.push(`${path}:${lineOf(node)}: uncatalogued message ${JSON.stringify(template)}`);
      }
    } else if (ts.isConditionalExpression(node)) {
      catalogued(node.whenTrue);
      catalogued(node.whenFalse);
    } else if (ts.isBinaryExpression(node) || ts.isParenthesizedExpression(node)) {
      catalogued(ts.isBinaryExpression(node) ? node.right : node.expression);
    }
  }

  function rendered(node: ts.Expression): void {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
      reportText(node.text, node);
    } else if (ts.isTemplateExpression(node)) {
      const text = [node.head.text, ...node.templateSpans.map((span) => span.literal.text)];
      reportText(text.join(expressionMarker), node);
    } else if (ts.isConditionalExpression(node)) {
      rendered(node.whenTrue);
      rendered(node.whenFalse);
    } else if (
      ts.isBinaryExpression(node) &&
      [
        ts.SyntaxKind.QuestionQuestionToken,
        ts.SyntaxKind.BarBarToken,
        ts.SyntaxKind.AmpersandAmpersandToken,
      ].includes(node.operatorToken.kind)
    ) {
      rendered(node.right);
    } else if (ts.isParenthesizedExpression(node)) {
      rendered(node.expression);
    }
  }

  function visit(node: ts.Node): void {
    if (ts.isJsxText(node)) {
      reportText(node.text, node);
    } else if (ts.isJsxAttribute(node) && VISIBLE_ATTRIBUTES.has(node.name.getText(file))) {
      const value = node.initializer;
      if (value && ts.isStringLiteral(value)) reportText(value.text, value);
      else if (value && ts.isJsxExpression(value) && value.expression) rendered(value.expression);
    } else if (
      ts.isJsxExpression(node) &&
      node.expression &&
      (ts.isJsxElement(node.parent) || ts.isJsxFragment(node.parent))
    ) {
      rendered(node.expression);
    } else if (
      ts.isPropertyAssignment(node) &&
      ts.isIdentifier(node.name) &&
      VISIBLE_FIELDS.has(node.name.text)
    ) {
      rendered(node.initializer);
    } else if (
      ts.isPropertyAssignment(node) &&
      ts.isIdentifier(node.name) &&
      MESSAGE_FIELDS.has(node.name.text)
    ) {
      catalogued(node.initializer);
    } else if (
      (ts.isCallExpression(node) || ts.isNewExpression(node)) &&
      ts.isIdentifier(node.expression) &&
      MESSAGE_CALLS.has(node.expression.text)
    ) {
      const message = node.arguments?.[MESSAGE_CALLS.get(node.expression.text) ?? 0];
      if (message) catalogued(message);
    } else if (
      ts.isBinaryExpression(node) &&
      node.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
      ts.isPropertyAccessExpression(node.left) &&
      VISIBLE_PROPERTIES.has(node.left.name.text)
    ) {
      rendered(node.right);
    } else if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === "t" &&
      node.arguments.length > 0
    ) {
      const key = node.arguments[0];
      if (ts.isStringLiteral(key) || ts.isNoSubstitutionTemplateLiteral(key)) {
        if (!hasKey(key.text)) {
          problems.push(`${path}:${lineOf(node)}: missing translation ${JSON.stringify(key.text)}`);
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  return problems;
}

function checkMarkup(
  path: string,
  source: string,
  hasKey: (key: string) => boolean,
  hasMessage: (key: string) => boolean,
): string[] {
  const problems: string[] = [];
  for (const script of source.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)) {
    const offset = source.slice(0, script.index).split("\n").length - 1;
    const body = "\n".repeat(offset) + script[1];
    problems.push(
      ...checkScript(`${path}.js`, body, hasKey, hasMessage).map((problem) =>
        problem.replace(".html.js:", ".html:"),
      ),
    );
  }
  // Blank out what is not page text while keeping line numbers.
  const blank = (text: string): string => text.replace(/[^\n]/g, " ");
  const markup = source
    .replace(/<!--[\s\S]*?-->/g, blank)
    .replace(/<(script|style|head)\b[\s\S]*?<\/\1>/gi, blank);
  const lineAt = (index: number): number => markup.slice(0, index).split("\n").length;
  let openTag = "";
  for (const match of markup.matchAll(/<[^>]*>|[^<]+/g)) {
    const chunk = match[0];
    const line = lineAt(match.index ?? 0);
    if (!chunk.startsWith("<")) {
      if (needsTranslation(chunk) && !/\bdata-i18n=/.test(openTag)) {
        problems.push(`${path}:${line}: untranslated text ${JSON.stringify(normalize(chunk))}`);
      }
      continue;
    }
    if (!chunk.startsWith("</")) openTag = chunk;
    for (const [, name, , value] of chunk.matchAll(
      /\b(aria-label|title|placeholder|alt)\s*=\s*(["'])(.*?)\2/g,
    )) {
      if (needsTranslation(value) && !new RegExp(`\\bdata-i18n-${name}=`).test(chunk)) {
        problems.push(`${path}:${line}: untranslated ${name} ${JSON.stringify(value)}`);
      }
    }
    for (const [, , key] of chunk.matchAll(/\bdata-i18n(?:-[\w-]+)?\s*=\s*(["'])(.*?)\1/g)) {
      if (!hasKey(key))
        problems.push(`${path}:${line}: missing translation ${JSON.stringify(key)}`);
    }
  }
  return problems;
}

/** Placeholders a message names, so both languages can be compared. */
export function placeholders(text: string): string {
  return [...text.matchAll(/\{(\w+)\}/g)]
    .map((match) => match[1])
    .sort()
    .join(",");
}

/** Every entry translates to nonempty text naming the same placeholders. */
export function validateCatalog(entries: Iterable<[string, string, string]>): string[] {
  const problems: string[] = [];
  for (const [key, english, chinese] of entries) {
    if (!english.trim() || !chinese.trim()) problems.push(`${key}: empty message`);
    else if (placeholders(english) !== placeholders(chinese)) {
      problems.push(`${key}: placeholders differ between languages`);
    }
  }
  return problems;
}

/** Reads the static pages' catalog as data; the script is never run. */
export function readStaticCatalog(source: string): Record<string, { en: string; "zh-CN": string }> {
  const file = ts.createSourceFile("i18n.js", source, ts.ScriptTarget.Latest, true);
  let literal: ts.ObjectLiteralExpression | undefined;
  const find = (node: ts.Node): void => {
    if (
      ts.isVariableDeclaration(node) &&
      node.name.getText(file) === "messages" &&
      node.initializer &&
      ts.isObjectLiteralExpression(node.initializer)
    ) {
      literal = node.initializer;
    }
    ts.forEachChild(node, find);
  };
  find(file);
  if (!literal) throw new Error("i18n.js must declare a literal `messages` object");
  const text = (node: ts.Node): string => {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
    if (ts.isIdentifier(node)) return node.text;
    throw new Error(`i18n.js messages must be literal strings: ${node.getText(file)}`);
  };
  const entries = literal.properties.map((property) => {
    if (!ts.isPropertyAssignment(property) || !ts.isObjectLiteralExpression(property.initializer)) {
      throw new Error("i18n.js messages must be literal { en, zh-CN } objects");
    }
    const pairs = Object.fromEntries(
      property.initializer.properties.map((field) => {
        if (!ts.isPropertyAssignment(field)) throw new Error("i18n.js messages must be literal");
        return [text(field.name), text(field.initializer)];
      }),
    );
    return [text(property.name), { en: pairs.en ?? "", "zh-CN": pairs["zh-CN"] ?? "" }] as const;
  });
  return Object.fromEntries(entries);
}
