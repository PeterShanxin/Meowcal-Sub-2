// The hand-maintained pages (splash, capture selector, subtitle plate) share this
// catalog; the studio's is in ui/src/i18n. Elements marked data-i18n take their
// text from it, and scripts call MeowcalI18n.t.
(() => {
  const messages = {
    "brand.name": { en: "Meowcal Sub 2", "zh-CN": "妙影2" },
    "splash.starting": { en: "Starting backend...", "zh-CN": "正在启动后台…" },
    "splash.checking": { en: "Checking backend...", "zh-CN": "正在检查后台…" },
    "splash.startingPython": { en: "Starting Python backend...", "zh-CN": "正在启动 Python 后台…" },
    "splash.waiting": {
      en: "Waiting for backend (up to 60s)...",
      "zh-CN": "正在等待后台（最多 60 秒）…",
    },
    "splash.retrying": { en: "Retrying...", "zh-CN": "正在重试…" },
    "splash.failed": { en: "Backend did not start", "zh-CN": "后台未能启动" },
    "splash.failedDetail": {
      en: "Local Python backend failed to respond within the timeout.",
      "zh-CN": "本地 Python 后台在限定时间内没有响应。",
    },
    "splash.retry": { en: "Retry", "zh-CN": "重试" },
    "selector.title": { en: "Capture Selector", "zh-CN": "选择捕获区域" },
    "selector.switchDisplay": { en: "Switch display", "zh-CN": "切换显示器" },
    "selector.confirm": { en: "Confirm", "zh-CN": "确认" },
    "selector.cancel": { en: "Cancel", "zh-CN": "取消" },
    "selector.instructions": {
      en: "Drag to select the subtitle capture area.",
      "zh-CN": "拖动鼠标，框选要捕获的字幕区域。",
    },
    "selector.reselect": {
      en: "Drag again to reselect, or confirm this area.",
      "zh-CN": "再次拖动可重新框选，或确认这个区域。",
    },
    "selector.saveFailed": {
      en: "Could not save this area: {error}",
      "zh-CN": "无法保存这个区域：{error}",
    },
    "selector.switchFailed": {
      en: "Could not switch display: {error}",
      "zh-CN": "无法切换显示器：{error}",
    },
    "overlay.translated": { en: "AI", "zh-CN": "AI" },
    "overlay.subtitle": { en: "SUB", "zh-CN": "字幕" },
  };

  // "system" follows the display language, as in the studio.
  const resolve = (preference) => {
    if (preference === "en" || preference === "zh-CN") return preference;
    return /^zh(?:-|$)/i.test(navigator.languages?.[0] ?? "") ? "zh-CN" : "en";
  };
  let locale = resolve("system");

  function t(key, parameters = {}) {
    const text = messages[key]?.[locale] ?? messages[key]?.en ?? key;
    return text.replace(/\{(\w+)\}/g, (match, name) =>
      Object.hasOwn(parameters, name) ? String(parameters[name]) : match,
    );
  }

  function apply() {
    document.documentElement.lang = locale;
    for (const element of document.querySelectorAll("[data-i18n]")) {
      element.textContent = t(element.dataset.i18n);
    }
  }

  window.MeowcalI18n = {
    t,
    setPreference(preference) {
      locale = resolve(preference);
      apply();
    },
  };
  apply();
})();
