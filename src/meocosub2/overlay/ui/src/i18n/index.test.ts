import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getLocale,
  localizeError,
  localizeMessage,
  normalizePreference,
  resolveLocale,
  setUiLanguage,
  subscribeLocale,
  t,
} from "./index";

afterEach(() => setUiLanguage("en"));

describe("interface language", () => {
  it("follows a Chinese display language unless a language was chosen", () => {
    expect(resolveLocale("system", ["zh-TW", "en"])).toBe("zh-CN");
    expect(resolveLocale("system", ["zh"])).toBe("zh-CN");
    expect(resolveLocale("system", ["en-SG", "zh-CN"])).toBe("en");
    expect(resolveLocale("system", [])).toBe("en");
    expect(resolveLocale("en", ["zh-CN"])).toBe("en");
    expect(resolveLocale("zh-CN", ["en-US"])).toBe("zh-CN");
  });

  it("treats an unknown saved value as following the system", () => {
    expect(normalizePreference("zh-CN")).toBe("zh-CN");
    expect(normalizePreference("fr")).toBe("system");
    expect(normalizePreference(undefined)).toBe("system");
  });

  it("switches live and tells subscribers once per change", () => {
    const listener = vi.fn();
    const stop = subscribeLocale(listener);
    setUiLanguage("zh-CN");
    setUiLanguage("zh-CN");
    expect(getLocale()).toBe("zh-CN");
    expect(listener).toHaveBeenCalledTimes(1);
    expect(t("Settings")).toBe("设置");
    setUiLanguage("en");
    expect(t("Settings")).toBe("Settings");
    stop();
    setUiLanguage("zh-CN");
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("fills named values in either language", () => {
    expect(t("{count} sources", { count: 3 })).toBe("3 sources");
    setUiLanguage("zh-CN");
    expect(t("{count} sources", { count: 3 })).toBe("3 个来源");
  });
});

describe("backend messages", () => {
  it("are shown as written in English", () => {
    expect(localizeMessage("Session prepared.")).toBe("Session prepared.");
    expect(localizeError("Provider exploded.")).toBe("Provider exploded.");
  });

  it("translate whole, by template, and inside a template's values", () => {
    setUiLanguage("zh-CN");
    expect(localizeMessage("Session prepared.")).toBe("会话已准备好。");
    expect(localizeMessage("SubDL: could not be reached.")).toBe("SubDL：无法连接。");
    expect(localizeMessage("Export blocked: Cue 4 has an empty body.")).toBe(
      "无法导出：第 4 条字幕没有文字。",
    );
  });

  it("translate joined warnings only when every sentence is known", () => {
    setUiLanguage("zh-CN");
    expect(
      localizeMessage(
        "PP-OCRv6 is unavailable. Using Windows OCR. ASSRT is disabled, so Chinese subtitle coverage may be thin.",
      ),
    ).toBe("PP-OCRv6 不可用，改用 Windows OCR。ASSRT 已停用，中文字幕可能较少。");
    const mixed = "Session prepared. Something nobody catalogued.";
    expect(localizeMessage(mixed)).toBe(mixed);
  });

  it("keep an unknown failure readable as a detail", () => {
    setUiLanguage("zh-CN");
    expect(localizeError("Provider exploded.")).toBe("出现问题。详细信息：Provider exploded.");
    expect(localizeError("设置已保存。")).toBe("设置已保存。");
  });
});
