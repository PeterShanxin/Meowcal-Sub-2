import { dom } from "./app-dom.js";
import { state } from "./app-state.js";
import { fetchJson } from "./app-api.js";
import {
  closeSettingsDrawer,
  openSettingsDrawer,
  scheduleRender,
  setSaveState,
} from "./app-shell.js";

export const CUSTOM_LANGUAGE = "__custom__";

export function languageControls() {
  return [
    {
      key: "source",
      fieldEl: dom.sourceLanguageField,
      selectEl: dom.sourceLanguageInput,
      triggerEl: dom.sourceLanguageTrigger,
      pickerEl: dom.sourceLanguagePicker,
      optionsEl: dom.sourceLanguageOptions,
      customInput: dom.sourceLanguageCustomInput,
      label: "Source language",
    },
    {
      key: "target",
      fieldEl: dom.targetLanguageField,
      selectEl: dom.targetLanguageInput,
      triggerEl: dom.targetLanguageTrigger,
      pickerEl: dom.targetLanguagePicker,
      optionsEl: dom.targetLanguageOptions,
      customInput: dom.targetLanguageCustomInput,
      label: "Target language",
    },
  ];
}

function languageControlForSelect(selectEl) {
  return languageControls().find((control) => control.selectEl === selectEl) || null;
}

function activeLanguageControl() {
  return languageControls().find((control) => control.key === state.activeLanguagePicker) || null;
}

function selectedLanguageLabel(control) {
  if (control.selectEl.value === CUSTOM_LANGUAGE) {
    return control.customInput.value.trim() || "Custom…";
  }
  return control.selectEl.selectedOptions[0]?.textContent?.trim() || "Select language";
}

export function updateLanguageTrigger(selectEl) {
  const control = languageControlForSelect(selectEl);
  if (!control) {
    return;
  }
  const label = selectedLanguageLabel(control);
  const textNode = control.triggerEl.querySelector(".language-trigger-text");
  if (textNode) {
    textNode.textContent = label;
    return;
  }
  control.triggerEl.textContent = label;
}

function renderLanguagePickerOptions(control) {
  if (!control.optionsEl) {
    return;
  }
  const options = Array.from(control.selectEl.options).map((option) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `language-picker-option${option.selected ? " is-selected" : ""}`;
    button.setAttribute("role", "option");
    button.dataset.value = option.value;
    button.setAttribute("aria-selected", option.selected ? "true" : "false");
    button.textContent = option.textContent;
    return button;
  });
  control.optionsEl.replaceChildren(...options);
}

export function closeLanguagePicker({ restoreFocus = true } = {}) {
  const control = activeLanguageControl();
  if (!control) {
    return;
  }
  control.fieldEl?.classList.remove("is-open");
  control.pickerEl?.classList.add("hidden");
  control.optionsEl?.replaceChildren();
  control.triggerEl.setAttribute("aria-expanded", "false");
  state.activeLanguagePicker = null;
  if (restoreFocus) {
    control.triggerEl.focus();
  }
}

function openLanguagePicker(control) {
  if (control.triggerEl.disabled) {
    return;
  }
  if (state.activeLanguagePicker === control.key) {
    closeLanguagePicker();
    return;
  }
  closeLanguagePicker({ restoreFocus: false });
  state.activeLanguagePicker = control.key;
  control.fieldEl?.classList.add("is-open");
  renderLanguagePickerOptions(control);
  control.pickerEl?.classList.remove("hidden");
  control.triggerEl.setAttribute("aria-expanded", "true");
  requestAnimationFrame(() => {
    const selectedOption = control.optionsEl?.querySelector(".is-selected");
    const firstOption = control.optionsEl?.querySelector(".language-picker-option");
    (selectedOption || firstOption)?.focus();
  });
}

export function normalizeLanguageCode(code) {
  const lowered = (code || "").trim().toLowerCase();
  const aliases = {
    "en-us": "en",
    "en-gb": "en",
    en: "en",
    zh: "zh",
    "zh-cn": "zh",
    "zh-hans": "zh",
    "zh-hans-cn": "zh",
    zhs: "zh",
    zht: "zht",
    "zh-tw": "zht",
    "zh-hant": "zht",
    "zh-hant-tw": "zht",
    ja: "ja",
    "ja-jp": "ja",
    ko: "ko",
    "ko-kr": "ko",
    es: "es",
    "es-es": "es",
    fr: "fr",
    "fr-fr": "fr",
    de: "de",
    "de-de": "de",
  };
  return aliases[lowered] || lowered;
}

export function isChineseFamily(code) {
  const normalized = normalizeLanguageCode(code);
  return normalized === "zh" || normalized === "zht" || normalized.startsWith("zh");
}

export function deriveOcrLanguage(sourceLanguage) {
  const normalized = normalizeLanguageCode(sourceLanguage);
  if (normalized === "zht") return "zh-TW";
  if (normalized === "zh") return "zh-CN";
  if (normalized === "ja") return "ja-JP";
  if (normalized === "ko") return "ko-KR";
  if (normalized === "es") return "es-ES";
  if (normalized === "fr") return "fr-FR";
  if (normalized === "de") return "de-DE";
  return "en-US";
}

export function currentLanguageValue(selectEl, customInput) {
  if (selectEl.value === CUSTOM_LANGUAGE) {
    return customInput.value.trim();
  }
  return selectEl.value.trim();
}

function currentLanguagePreferences() {
  const source = currentLanguageValue(dom.sourceLanguageInput, dom.sourceLanguageCustomInput);
  const target = currentLanguageValue(dom.targetLanguageInput, dom.targetLanguageCustomInput);
  if (!source || !target) {
    return null;
  }
  return { source, target };
}

export function languagePreferenceKey(languages) {
  if (!languages?.source || !languages?.target) {
    return null;
  }
  return `${languages.source}::${languages.target}`;
}

function buildLanguagePreferencePayload() {
  const languages = currentLanguagePreferences();
  if (!languages || !state.config) {
    return null;
  }
  return {
    ...state.config,
    languages: {
      ...(state.config.languages || {}),
      source: languages.source,
      target: languages.target,
    },
    capture: {
      ...(state.config.capture || {}),
      ocrLanguage: deriveOcrLanguage(languages.source),
    },
  };
}

async function flushLanguagePreferenceSave() {
  if (state.languagePersistence.saving) {
    return;
  }
  state.languagePersistence.saving = true;
  try {
    while (state.languagePersistence.pendingKey) {
      const payload = buildLanguagePreferencePayload();
      if (!payload) {
        state.languagePersistence.pendingKey = null;
        break;
      }
      const currentKey = languagePreferenceKey(payload.languages);
      state.languagePersistence.pendingKey = null;
      if (
        state.config?.languages?.source === payload.languages.source &&
        state.config?.languages?.target === payload.languages.target
      ) {
        state.languagePersistence.lastSavedKey = currentKey;
        continue;
      }
      setSaveState("Saving language preference...", "busy");
      const config = await fetchJson("/api/config", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      state.config = config;
      state.languagePersistence.lastSavedKey = languagePreferenceKey(config.languages);
      setSaveState("Language preference saved", "success");
      scheduleRender();
    }
  } catch (error) {
    setSaveState(error.message, "error");
  } finally {
    state.languagePersistence.saving = false;
    if (
      state.languagePersistence.pendingKey &&
      state.languagePersistence.pendingKey !== state.languagePersistence.lastSavedKey
    ) {
      void flushLanguagePreferenceSave();
    }
  }
}

export function persistLanguagePreferences() {
  if (!state.bootstrap.ready || !state.config) {
    return;
  }
  const languages = currentLanguagePreferences();
  const nextKey = languagePreferenceKey(languages);
  if (!nextKey) {
    return;
  }
  if (
    !state.languagePersistence.saving &&
    state.config?.languages?.source === languages.source &&
    state.config?.languages?.target === languages.target
  ) {
    state.languagePersistence.lastSavedKey = nextKey;
    return;
  }
  state.languagePersistence.pendingKey = nextKey;
  void flushLanguagePreferenceSave();
}

export function providerConfig(config) {
  const subtitleSources = config?.subtitleSources || {};
  const legacyOpenSubtitles = config?.opensubtitles || {};
  return {
    opensubtitles: {
      enabled: subtitleSources.opensubtitles?.enabled ?? legacyOpenSubtitles.enabled ?? true,
      apiKey: subtitleSources.opensubtitles?.apiKey ?? legacyOpenSubtitles.apiKey ?? "",
      enableOrgFallback:
        subtitleSources.opensubtitles?.enableOrgFallback ?? legacyOpenSubtitles.enableOrgFallback ?? false,
    },
    subdl: {
      enabled: subtitleSources.subdl?.enabled ?? true,
    },
    assrt: {
      enabled: subtitleSources.assrt?.enabled ?? false,
      token: subtitleSources.assrt?.token ?? "",
    },
  };
}

export function assrtCoverageHint(sourceLanguage) {
  if (!sourceLanguage || !isChineseFamily(sourceLanguage)) {
    return "";
  }
  const assrt = providerConfig(state.config).assrt;
  if (assrt.enabled && (assrt.token || "").trim()) {
    return "";
  }
  return assrt.enabled
    ? "ASSRT is not configured, so Chinese subtitle coverage may be thin."
    : "ASSRT is disabled, so Chinese subtitle coverage may be thin.";
}

export function syncCustomLanguageInput(selectEl, customInput) {
  customInput.classList.toggle("hidden", selectEl.value !== CUSTOM_LANGUAGE);
}

export function populateLanguageSelect(selectEl, customInput, options, currentValue) {
  const normalized = normalizeLanguageCode(currentValue);
  const known = options.some((option) => option.code === normalized);
  const optionNodes = options.map((option) => {
    const optionEl = document.createElement("option");
    optionEl.value = option.code;
    optionEl.textContent = option.label;
    return optionEl;
  });
  const customOption = document.createElement("option");
  customOption.value = CUSTOM_LANGUAGE;
  customOption.textContent = "Custom…";
  selectEl.replaceChildren(...optionNodes, customOption);
  if (known) {
    selectEl.value = normalized;
    customInput.value = "";
  } else {
    selectEl.value = CUSTOM_LANGUAGE;
    customInput.value = currentValue || "";
  }
  syncCustomLanguageInput(selectEl, customInput);
  updateLanguageTrigger(selectEl);
  const control = languageControlForSelect(selectEl);
  if (control && state.activeLanguagePicker === control.key) {
    renderLanguagePickerOptions(control);
  }
}

export function renderFoundryStatus(status) {
  state.foundryStatus = status;
  if (!status) {
    dom.foundryStatusChip.textContent = "Unknown";
    dom.foundryStatusChip.className = "status-chip error";
    dom.foundryStatusNote.textContent = "Could not load Foundry Local status.";
    scheduleRender();
    return;
  }

  const phase = (status.phase || "error").toString();
  const labelMap = {
    unchecked: "Unchecked",
    ready: "Ready",
    preparing: "Preparing",
    notRunning: "Not Running",
    noModels: "No Models",
    notInstalled: "Not Installed",
    error: "Error",
  };
  const classMap = {
    unchecked: "idle",
    ready: "running",
    preparing: "searching",
    notRunning: "error",
    noModels: "error",
    notInstalled: "error",
    error: "error",
  };

  dom.foundryStatusChip.textContent = labelMap[phase] || "Unknown";
  dom.foundryStatusChip.className = `status-chip ${classMap[phase] || "error"}`;
  dom.foundryStatusNote.textContent = status.notes || "Foundry Local status loaded.";
  scheduleRender();
}

export function languageLabel(code) {
  const normalized = normalizeLanguageCode(code);
  return (
    state.languageCatalog?.sourceTarget?.find((option) => option.code === normalized)?.label ||
    state.languageCatalog?.sourceTarget?.find((option) => option.code === code)?.label ||
    (code || "Unknown").toUpperCase()
  );
}

export function updateDerivedOcrDisplay(ocrLanguage) {
  const resolved = ocrLanguage || deriveOcrLanguage(currentLanguageValue(dom.sourceLanguageInput, dom.sourceLanguageCustomInput));
  dom.ocrLanguageDisplay.textContent = resolved;

  const entry = state.languageCatalog?.ocr?.find((option) => option.code === resolved);
  const installed = entry ? entry.installed : false;
  if (installed) {
    dom.ocrLanguageNote.textContent = "OCR follows the selected source language automatically.";
    dom.ocrInstallButton.classList.add("hidden");
    dom.ocrInstallButton.dataset.languageTag = "";
    scheduleRender();
    return;
  }

  const simplifiedFallback =
    resolved === "zh-TW" && state.languageCatalog?.ocr?.find((option) => option.code === "zh-CN")?.installed;
  dom.ocrLanguageNote.textContent = simplifiedFallback
    ? `${resolved} is not installed. Start Sync will fall back to zh-CN OCR, or you can install the Traditional pack.`
    : `${resolved} is not installed. Install the OCR pack or switch the source language.`;
  dom.ocrInstallButton.classList.remove("hidden");
  dom.ocrInstallButton.dataset.languageTag = resolved;
  scheduleRender();
}

export function setupLanguagePicker() {
  for (const control of languageControls()) {
    control.triggerEl.addEventListener("click", () => {
      if (!state.bootstrap.ready) {
        return;
      }
      openLanguagePicker(control);
    });
    control.triggerEl.addEventListener("keydown", (event) => {
      if (!state.bootstrap.ready) {
        return;
      }
      if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openLanguagePicker(control);
      }
    });
    control.optionsEl.addEventListener("click", (event) => {
      const option = event.target.closest("[data-value]");
      if (!option) {
        return;
      }
      control.selectEl.value = option.dataset.value;
      control.selectEl.dispatchEvent(new Event("change", { bubbles: true }));
      closeLanguagePicker();
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.activeLanguagePicker) {
      event.preventDefault();
      closeLanguagePicker();
      return;
    }
    if (event.key === "Escape" && state.ui.settingsOpen) {
      event.preventDefault();
      closeSettingsDrawer();
    }
  });

  document.addEventListener("click", (event) => {
    const control = activeLanguageControl();
    if (!control || control.fieldEl?.contains(event.target)) {
      return;
    }
    closeLanguagePicker({ restoreFocus: false });
  });
}
