import { useSyncExternalStore } from "react";
import chinese from "./en-zh.json";
import messageChinese from "./messages-zh.json";

export type UiLanguage = "system" | "en" | "zh-CN";
export type Locale = Exclude<UiLanguage, "system">;
export type Parameters = Record<string, string | number>;

// English source text is the lookup key, so an untranslated key still reads.
// Interface text goes through t(). Messages written before they are shown, by
// the backend or by a failed edit, have their own catalog: their templates are
// matched against whole sentences, and an interface label such as "S{number}"
// would claim any message that starts with an S.
const catalog: Readonly<Record<string, string>> = chinese;
const messageCatalog: Readonly<Record<string, string>> = messageChinese;

export function normalizePreference(value: unknown): UiLanguage {
  return value === "en" || value === "zh-CN" ? value : "system";
}

/** "system" follows the display language: any Chinese variant reads Simplified Chinese. */
export function resolveLocale(preference: UiLanguage, languages: readonly string[]): Locale {
  if (preference !== "system") return preference;
  return /^zh(?:-|$)/i.test(languages[0] ?? "") ? "zh-CN" : "en";
}

function systemLanguages(): readonly string[] {
  return typeof navigator === "undefined" ? [] : navigator.languages;
}

// The served page carries the saved preference, so the first paint is already
// in the right language.
const bootstrap =
  typeof window === "undefined"
    ? undefined
    : (window as { __MEOWCAL__?: { uiLanguage?: unknown } }).__MEOWCAL__?.uiLanguage;
let preference = normalizePreference(bootstrap);
let locale = resolveLocale(preference, systemLanguages());
const listeners = new Set<() => void>();

export function getLocale(): Locale {
  return locale;
}

export function getUiLanguage(): UiLanguage {
  return preference;
}

export function setUiLanguage(value: unknown): void {
  preference = normalizePreference(value);
  const next = resolveLocale(preference, systemLanguages());
  if (typeof document !== "undefined") {
    document.documentElement.lang = next;
    document.title = next === "zh-CN" ? catalog["Meowcal Sub 2"] : "Meowcal Sub 2";
  }
  if (next === locale) return;
  locale = next;
  for (const listener of listeners) listener();
}

export function subscribeLocale(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Re-renders the caller when the interface language changes. */
export function useLocale(): Locale {
  return useSyncExternalStore(subscribeLocale, getLocale);
}

if (typeof window !== "undefined") {
  window.addEventListener("languagechange", () => setUiLanguage(preference));
}

function fill(template: string, parameters: Parameters): string {
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    Object.hasOwn(parameters, name) ? String(parameters[name]) : match,
  );
}

export function t(key: string, parameters: Parameters = {}): string {
  return fill(locale === "zh-CN" ? (catalog[key] ?? key) : key, parameters);
}

interface Template {
  pattern: RegExp;
  names: string[];
  chinese: string;
  fixed: number;
}

// Backend messages with values in them are catalogued as templates such as
// "Downloading the {asset} failed: {reason}"; the values are read back out of
// the English text. The template with the most fixed text is tried first, so
// "{file}: {reason}" never claims a message a more specific template fits.
const templates: Template[] = Object.entries(messageCatalog)
  .filter(([english]) => english.includes("{"))
  .map(([english, chinese]) => {
    const names: string[] = [];
    const source = english
      .split(/(\{\w+\})/)
      .map((part) => {
        const name = /^\{(\w+)\}$/.exec(part)?.[1];
        if (!name) return part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        names.push(name);
        return "(.+?)";
      })
      .join("");
    return { pattern: new RegExp(`^${source}$`, "s"), names, chinese, fixed: source.length };
  })
  .sort((a, b) => b.fixed - a.fixed);
const translations = new Set([...Object.values(catalog), ...Object.values(messageCatalog)]);

function translateSentence(text: string): string | null {
  if (Object.hasOwn(messageCatalog, text)) return messageCatalog[text];
  for (const { pattern, names, chinese } of templates) {
    const match = pattern.exec(text);
    if (match) {
      // A value can itself be a catalogued message, such as the reason an
      // export was blocked.
      const values = Object.fromEntries(
        names.map((name, index) => [name, translateSentence(match[index + 1]) ?? match[index + 1]]),
      );
      return fill(chinese, values);
    }
  }
  return null;
}

/**
 * Text the backend wrote for the viewer, in the interface language.
 *
 * The backend joins several warnings into one line, so a message that is not
 * catalogued whole is read sentence by sentence. A message with any sentence
 * the catalog does not know is shown as written rather than half translated.
 */
export function localizeMessage(message: string): string {
  const text = message.trim();
  if (locale === "en" || !text || translations.has(text)) return message;
  const whole = translateSentence(text);
  if (whole !== null) return whole;
  const translated: string[] = [];
  let pending = "";
  for (const sentence of text.split(/(?<=[.!?;])\s+/)) {
    pending = pending ? `${pending} ${sentence}` : sentence;
    const hit = translateSentence(pending.replace(/;$/, ""));
    if (hit !== null) {
      translated.push(hit);
      pending = "";
    }
  }
  return pending ? message : translated.join("");
}

/** A failure for the viewer: catalogued text, or the backend's wording as a detail. */
export function localizeError(message: string): string {
  const localized = localizeMessage(message);
  if (locale === "en" || localized !== message || translations.has(message.trim())) {
    return localized;
  }
  return t("Something went wrong. Details: {details}", { details: message.trim() });
}
