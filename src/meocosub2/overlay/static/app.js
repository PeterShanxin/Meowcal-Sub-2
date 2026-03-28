const dom = {
  commandBar: document.getElementById("command-bar"),
  statusStrip: document.getElementById("status-strip"),
  settingsOpenButton: document.getElementById("settings-open-button"),
  settingsInlineButton: document.getElementById("settings-inline-button"),
  settingsCloseButton: document.getElementById("settings-close-button"),
  settingsDrawer: document.getElementById("settings-drawer"),
  settingsBackdrop: document.getElementById("settings-backdrop"),
  titleInput: document.getElementById("title-input"),
  sourceLanguageField: document.getElementById("source-language-field"),
  sourceLanguageTrigger: document.getElementById("source-language-trigger"),
  sourceLanguagePicker: document.getElementById("source-language-picker"),
  sourceLanguageOptions: document.getElementById("source-language-options"),
  sourceLanguageInput: document.getElementById("source-language-input"),
  sourceLanguageCustomInput: document.getElementById("source-language-custom"),
  targetLanguageField: document.getElementById("target-language-field"),
  targetLanguageTrigger: document.getElementById("target-language-trigger"),
  targetLanguagePicker: document.getElementById("target-language-picker"),
  targetLanguageOptions: document.getElementById("target-language-options"),
  targetLanguageInput: document.getElementById("target-language-input"),
  targetLanguageCustomInput: document.getElementById("target-language-custom"),
  statusChip: document.getElementById("status-chip"),
  statusMessage: document.getElementById("status-message"),
  progressStage: document.getElementById("progress-stage"),
  progressMeta: document.getElementById("progress-meta"),
  progressFill: document.getElementById("progress-fill"),
  titleMatchStrip: document.getElementById("title-match-strip"),
  titleMatchResults: document.getElementById("title-match-results"),
  titleMatchCount: document.getElementById("title-match-count"),
  searchResultSummary: document.getElementById("search-result-summary"),
  sourceResults: document.getElementById("source-results"),
  targetResults: document.getElementById("target-results"),
  sourceResultCount: document.getElementById("source-result-count"),
  targetResultCount: document.getElementById("target-result-count"),
  preparedSession: document.getElementById("prepared-session"),
  sessionBadge: document.getElementById("session-badge"),
  currentSubtitle: document.getElementById("current-subtitle"),
  prepareButton: document.getElementById("prepare-button"),
  startButton: document.getElementById("start-button"),
  stopButton: document.getElementById("stop-button"),
  saveState: document.getElementById("save-state"),
  overlayLink: document.getElementById("overlay-link"),
  searchForm: document.getElementById("search-form"),
  searchSubmitButton: document.getElementById("search-submit-button"),
  configForm: document.getElementById("config-form"),
  opensubtitlesEnabledInput: document.getElementById("source-opensubtitles-enabled-input"),
  opensubtitlesApiKeyInput: document.getElementById("source-opensubtitles-api-key-input"),
  opensubtitlesOrgFallbackInput: document.getElementById("source-opensubtitles-org-fallback-input"),
  subdlEnabledInput: document.getElementById("source-subdl-enabled-input"),
  assrtEnabledInput: document.getElementById("source-assrt-enabled-input"),
  assrtTokenInput: document.getElementById("source-assrt-token-input"),
  foundryStatusChip: document.getElementById("foundry-status-chip"),
  foundryStatusNote: document.getElementById("foundry-status-note"),
  ocrLanguageDisplay: document.getElementById("ocr-language-display"),
  ocrLanguageNote: document.getElementById("ocr-language-note"),
  ocrInstallButton: document.getElementById("ocr-install-button"),
  selectRegionButton: document.getElementById("select-region-button"),
  loadingOverlay: document.getElementById("loading-overlay"),
  loadingSpinner: document.getElementById("loading-spinner"),
  loadingTitle: document.getElementById("loading-title"),
  loadingMessage: document.getElementById("loading-message"),
  loadingRetry: document.getElementById("loading-retry"),
};

const state = {
  snapshot: null,
  config: null,
  languageCatalog: null,
  foundryStatus: null,
  selectedFeatureId: null,
  selectedSourceFileId: null,
  selectedTargetFileId: null,
  sourceSelectionMode: null,
  overlayWindow: null,
  activeLanguagePicker: null,
  ui: {
    settingsOpen: false,
  },
  bootstrap: {
    ready: false,
    loading: false,
  },
};

let socket;
let renderScheduled = false;
let bootstrapPromise = null;
const TAURI = window.__TAURI__?.core?.invoke ? window.__TAURI__ : null;
const API_BASE = /^https?:$/i.test(window.location.protocol) ? window.location.origin : "";

function apiUrl(path) {
  return `${API_BASE}${path}`;
}

function wsUrl(path) {
  if (!API_BASE) {
    return `ws://${location.host}${path}`;
  }
  const url = new URL(API_BASE);
  return `ws://${url.host}${path}`;
}

function scheduleRender() {
  if (renderScheduled) {
    return;
  }

  renderScheduled = true;
  requestAnimationFrame(() => {
    renderScheduled = false;
    render();
  });
}

async function fetchJson(url, options = {}) {
  const response = await fetch(apiUrl(url), {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail || response.statusText);
  }

  return response.json();
}

function setSaveState(label, kind = "neutral") {
  dom.saveState.textContent = label;
  dom.saveState.dataset.state = kind;
}

function interactiveControls() {
  return [
    ...document.querySelectorAll("#search-form input, #search-form select, #search-form button"),
    ...document.querySelectorAll("#config-form input, #config-form select, #config-form button"),
    dom.prepareButton,
    dom.startButton,
    dom.stopButton,
    dom.settingsOpenButton,
    dom.settingsInlineButton,
    dom.settingsCloseButton,
  ].filter(Boolean);
}

function setOverlayLinkDisabled(disabled) {
  dom.overlayLink.classList.toggle("is-disabled", disabled);
  dom.overlayLink.setAttribute("aria-disabled", String(disabled));
  dom.overlayLink.tabIndex = disabled ? -1 : 0;
}

function setControlsDisabled(disabled) {
  if (disabled && state.activeLanguagePicker) {
    closeLanguagePicker({ restoreFocus: false });
  }
  if (disabled && state.ui.settingsOpen) {
    setSettingsDrawerOpen(false);
  }
  for (const control of interactiveControls()) {
    control.disabled = disabled;
  }
  setOverlayLinkDisabled(disabled);
}

function setBootstrapLoading(title, message) {
  state.bootstrap.loading = true;
  state.bootstrap.ready = false;
  setControlsDisabled(true);
  if (!dom.loadingOverlay) {
    return;
  }
  dom.loadingOverlay.classList.remove("fade-out", "is-error");
  dom.loadingTitle.textContent = title;
  dom.loadingMessage.textContent = message;
  dom.loadingRetry.classList.add("hidden");
  dom.loadingSpinner.classList.remove("hidden");
}

function setBootstrapError(message) {
  state.bootstrap.loading = false;
  state.bootstrap.ready = false;
  setControlsDisabled(true);
  if (!dom.loadingOverlay) {
    return;
  }
  dom.loadingOverlay.classList.remove("fade-out");
  dom.loadingOverlay.classList.add("is-error");
  dom.loadingTitle.textContent = "Studio startup incomplete";
  dom.loadingMessage.textContent = message;
  dom.loadingRetry.classList.remove("hidden");
  dom.loadingSpinner.classList.add("hidden");
}

function waitForNextPaint() {
  return new Promise((resolve) => {
    requestAnimationFrame(() => {
      requestAnimationFrame(resolve);
    });
  });
}

function setSettingsDrawerOpen(open) {
  state.ui.settingsOpen = open;
  dom.settingsDrawer?.classList.toggle("is-open", open);
  dom.settingsDrawer?.setAttribute("aria-hidden", String(!open));
  dom.settingsBackdrop?.classList.toggle("hidden", !open);
  document.body.classList.toggle("drawer-open", open);
}

function openSettingsDrawer() {
  if (!state.bootstrap.ready) {
    return;
  }
  setSettingsDrawerOpen(true);
}

function closeSettingsDrawer() {
  setSettingsDrawerOpen(false);
}

const CUSTOM_LANGUAGE = "__custom__";

function languageControls() {
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

function updateLanguageTrigger(selectEl) {
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

function closeLanguagePicker({ restoreFocus = true } = {}) {
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

function normalizeLanguageCode(code) {
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

function isChineseFamily(code) {
  const normalized = normalizeLanguageCode(code);
  return normalized === "zh" || normalized === "zht" || normalized.startsWith("zh");
}

function deriveOcrLanguage(sourceLanguage) {
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

function currentLanguageValue(selectEl, customInput) {
  if (selectEl.value === CUSTOM_LANGUAGE) {
    return customInput.value.trim();
  }
  return selectEl.value.trim();
}

function providerConfig(config) {
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

function selectionValue(value) {
  if (value == null || value === "") {
    return null;
  }
  return String(value);
}

function sameSelectionValue(left, right) {
  return selectionValue(left) === selectionValue(right);
}

function numericSelectionValue(value) {
  const normalized = selectionValue(value);
  return normalized && /^\d+$/.test(normalized) ? Number(normalized) : null;
}

function matchSelectionId(match) {
  if (!match) {
    return null;
  }
  return selectionValue(match.matchId ?? match.id);
}

function resultSelectionId(result) {
  if (!result) {
    return null;
  }
  return selectionValue(result.resultId ?? result.fileId ?? result.id);
}

function providerLabelText(entry) {
  return entry?.providerLabel || entry?.provider_label || entry?.provider || "";
}

function providerLabelsForMatch(match) {
  if (Array.isArray(match?.providerLabels) && match.providerLabels.length) {
    return match.providerLabels;
  }
  if (Array.isArray(match?.providers) && match.providers.length) {
    return match.providers;
  }
  return match?.providerLabel ? [match.providerLabel] : [];
}

function resultMatchesFeature(result, featureId) {
  const numericFeatureId = numericSelectionValue(featureId);
  if (numericFeatureId == null) {
    return true;
  }
  return [result.parentFeatureId, result.featureId].some((value) => Number(value) === numericFeatureId);
}

function resultMatchesSelectedMatch(result, matchId) {
  if (!matchId) {
    return true;
  }
  if (result.matchId != null) {
    return sameSelectionValue(result.matchId, matchId);
  }
  return resultMatchesFeature(result, matchId);
}

function currentFeatureId(snapshot) {
  return (
    state.selectedFeatureId ??
    selectionValue(snapshot?.selected_match_id) ??
    selectionValue(snapshot?.selected_feature_id) ??
    matchSelectionId(snapshot?.search_matches?.[0]) ??
    null
  );
}

function selectedSourceResultId(snapshot) {
  return state.selectedSourceFileId ?? selectionValue(snapshot?.selected_source_result_id) ?? selectionValue(snapshot?.selected_source_file_id);
}

function selectedTargetResultId(snapshot) {
  return state.selectedTargetFileId ?? selectionValue(snapshot?.selected_target_result_id) ?? selectionValue(snapshot?.selected_target_file_id);
}

function currentSourceSelectionMode(snapshot, sourceResults, featureId) {
  if (state.sourceSelectionMode) {
    return state.sourceSelectionMode;
  }
  if (snapshot?.prepared_session?.session_mode) {
    return snapshot.prepared_session.session_mode === "ocr_fallback" ? "ocr_fallback" : "subtitle";
  }
  if (featureId && sourceResults.length === 0 && (snapshot?.search_matches || []).length) {
    return "ocr_fallback";
  }
  return "subtitle";
}

function syncCustomLanguageInput(selectEl, customInput) {
  customInput.classList.toggle("hidden", selectEl.value !== CUSTOM_LANGUAGE);
}

function populateLanguageSelect(selectEl, customInput, options, currentValue) {
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

function renderFoundryStatus(status) {
  state.foundryStatus = status;
  if (!status) {
    dom.foundryStatusChip.textContent = "Unknown";
    dom.foundryStatusChip.className = "status-chip error";
    dom.foundryStatusNote.textContent = "Could not load Foundry Local status.";
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
}

function languageLabel(code) {
  const normalized = normalizeLanguageCode(code);
  return (
    state.languageCatalog?.sourceTarget?.find((option) => option.code === normalized)?.label ||
    state.languageCatalog?.sourceTarget?.find((option) => option.code === code)?.label ||
    (code || "Unknown").toUpperCase()
  );
}

function statusLabel(status) {
  const labels = {
    idle: "Idle",
    searching: "Searching",
    preparing: "Preparing",
    running: "Running",
    stopping: "Stopping",
    error: "Error",
  };
  return labels[status] || "Idle";
}

function sessionHeadline(snapshot, selectedSource, selectedTarget) {
  if (snapshot.status === "searching") {
    return snapshot.title ? `Finding subtitle sources for ${snapshot.title}` : "Finding subtitle matches";
  }
  if (snapshot.status === "preparing") {
    return "Preparing your subtitle session";
  }
  if (snapshot.status === "running") {
    return "Live sync is active";
  }
  if (snapshot.status === "stopping") {
    return "Stopping live sync";
  }
  if (snapshot.error_message) {
    return "Something needs attention";
  }
  if (snapshot.prepared_session) {
    return snapshot.prepared_session.session_mode === "ocr_fallback"
      ? "OCR fallback session prepared. Start sync when playback begins."
      : "Session prepared. Start sync when the video is ready.";
  }
  if (selectedSource && selectedTarget != null) {
    return "Subtitle pair selected. Prepare the session next.";
  }
  if (selectedSource) {
    return "Source selected. Keep local translation or choose a target subtitle.";
  }
  if ((snapshot.search_matches || []).length) {
    return "Choose a matched title, then pick subtitles from the merged source list or use OCR fallback.";
  }
  if ((snapshot.search_results || []).length) {
    return "Choose the subtitle pair for this session.";
  }
  return "Search for a title to begin";
}

function sessionMessage(snapshot, selectedSource, selectedTarget) {
  if (snapshot.error_message) {
    return snapshot.error_message;
  }
  if (snapshot.warning_message) {
    return snapshot.warning_message;
  }
  if (snapshot.status === "running") {
    return snapshot.prepared_session?.session_mode === "ocr_fallback"
      ? "Live OCR text is being translated and aligned against target subtitles when possible."
      : "The OCR loop is matching on-screen subtitles and sending lines to the overlay.";
  }
  if (snapshot.prepared_session) {
    return snapshot.prepared_session.session_mode === "ocr_fallback"
      ? "Foundry-backed OCR fallback is ready. Open the overlay and start sync when playback begins."
      : "Your subtitle files are ready. Open the overlay and start sync when playback begins.";
  }
  if (selectedSource && selectedTarget == null) {
    return "No target subtitle is selected yet. You can still prepare with local translation.";
  }
  if ((snapshot.search_matches || []).length) {
    return "Review the matched titles below. Provider badges show where each subtitle came from, and OCR fallback remains available.";
  }
  if ((snapshot.search_results || []).length) {
    return "Review the merged results below. The source subtitle choice drives the rest of the flow.";
  }
  return "Ready for a title search.";
}

function progressSummary(snapshot, selectedSource) {
  if (snapshot.progress?.message) {
    return snapshot.progress.message;
  }
  if (snapshot.prepared_session) {
    return snapshot.prepared_session.session_mode === "ocr_fallback"
      ? "Prepared OCR fallback session will translate live OCR and optionally align against target subtitles."
      : "Prepared session is ready for the next viewing run.";
  }
  if (selectedSource) {
    return "Prepare the session once the subtitle choice looks right.";
  }
  if ((snapshot.search_matches || []).length) {
    return "Pick a title first, then choose source subtitles from the merged source list or OCR fallback.";
  }
  if ((snapshot.search_results || []).length) {
    return "Select a source subtitle and confirm the target side.";
  }
  return "Search and choose subtitle files to begin.";
}

function regionToString(region) {
  return Array.isArray(region) ? region.join(",") : "";
}

function parseRegion(value) {
  if (!value.trim()) {
    return [];
  }
  return value
    .split(",")
    .map((part) => Number(part.trim()))
    .filter((item) => Number.isFinite(item));
}

function applyStylePreview(overlay) {
  if (!overlay) {
    return;
  }

  const root = document.documentElement;
  root.style.setProperty("--overlay-font-size", `${overlay.fontSize}px`);
  root.style.setProperty("--overlay-font-family", overlay.fontFamily);
  root.style.setProperty("--overlay-text-color", overlay.textColor);
  root.style.setProperty("--overlay-bg-color", overlay.bgColor);
  root.style.setProperty("--overlay-radius", `${overlay.radiusPx}px`);
  root.style.setProperty("--overlay-padding", `${overlay.paddingPx}px`);
  root.style.setProperty("--overlay-max-width", `${overlay.maxWidthVw}vw`);
  root.style.setProperty("--overlay-blur", `${overlay.blurPx}px`);
  root.style.setProperty("--overlay-shadow-strength", overlay.shadowStrength);
}

function fillConfigForm(config) {
  const { capture, translation, overlay } = config;
  const subtitleSources = providerConfig(config);
  dom.opensubtitlesEnabledInput.checked = subtitleSources.opensubtitles.enabled !== false;
  dom.opensubtitlesApiKeyInput.value = subtitleSources.opensubtitles.apiKey || "";
  dom.opensubtitlesOrgFallbackInput.checked = subtitleSources.opensubtitles.enableOrgFallback === true;
  dom.subdlEnabledInput.checked = subtitleSources.subdl.enabled !== false;
  dom.assrtEnabledInput.checked = subtitleSources.assrt.enabled === true;
  dom.assrtTokenInput.value = subtitleSources.assrt.token || "";
  document.getElementById("translation-endpoint-input").value = translation.endpoint || "";
  document.getElementById("translation-model-input").value = translation.model || "";
  document.getElementById("capture-interval-input").value = capture.intervalMs ?? 1500;
  document.getElementById("capture-region-input").value = regionToString(capture.region);
  document.getElementById("overlay-theme-input").value = overlay.theme;
  document.getElementById("overlay-position-input").value = overlay.position;
  document.getElementById("overlay-font-family-input").value = overlay.fontFamily;
  document.getElementById("overlay-font-size-input").value = overlay.fontSize;
  document.getElementById("overlay-text-color-input").value = overlay.textColor;
  document.getElementById("overlay-bg-color-input").value = overlay.bgColor;
  document.getElementById("overlay-radius-input").value = overlay.radiusPx;
  document.getElementById("overlay-padding-input").value = overlay.paddingPx;
  document.getElementById("overlay-max-width-input").value = overlay.maxWidthVw;
  document.getElementById("overlay-blur-input").value = overlay.blurPx;
  document.getElementById("overlay-shadow-input").value = overlay.shadowStrength;
  document.getElementById("overlay-offset-input").value = overlay.offsetPct;
  document.getElementById("overlay-animation-input").value = overlay.animationMs;
  updateDerivedOcrDisplay(capture.ocrLanguage || deriveOcrLanguage(config.languages.source));
  applyStylePreview(overlay);
}

function currentOverlayConfigFromForm() {
  return {
    theme: document.getElementById("overlay-theme-input").value,
    position: document.getElementById("overlay-position-input").value,
    fontFamily: document.getElementById("overlay-font-family-input").value,
    fontSize: Number(document.getElementById("overlay-font-size-input").value || 28),
    textColor: document.getElementById("overlay-text-color-input").value,
    bgColor: document.getElementById("overlay-bg-color-input").value,
    radiusPx: Number(document.getElementById("overlay-radius-input").value || 28),
    paddingPx: Number(document.getElementById("overlay-padding-input").value || 20),
    maxWidthVw: Number(document.getElementById("overlay-max-width-input").value || 78),
    blurPx: Number(document.getElementById("overlay-blur-input").value || 20),
    shadowStrength: Number(document.getElementById("overlay-shadow-input").value || 0.45),
    offsetPct: Number(document.getElementById("overlay-offset-input").value || 10),
    animationMs: Number(document.getElementById("overlay-animation-input").value || 220),
  };
}

function buildConfigPayload() {
  const sourceLanguage = currentLanguageValue(dom.sourceLanguageInput, dom.sourceLanguageCustomInput) || "en";
  const targetLanguage = currentLanguageValue(dom.targetLanguageInput, dom.targetLanguageCustomInput) || "zh";
  const opensubtitles = {
    enabled: dom.opensubtitlesEnabledInput.checked,
    apiKey: dom.opensubtitlesApiKeyInput.value.trim(),
    enableOrgFallback: dom.opensubtitlesOrgFallbackInput.checked,
  };
  return {
    subtitleSources: {
      opensubtitles,
      subdl: {
        enabled: dom.subdlEnabledInput.checked,
      },
      assrt: {
        enabled: dom.assrtEnabledInput.checked,
        token: dom.assrtTokenInput.value.trim(),
      },
    },
    opensubtitles,
    languages: {
      source: sourceLanguage,
      target: targetLanguage,
    },
    capture: {
      ocrLanguage: deriveOcrLanguage(sourceLanguage),
      intervalMs: Number(document.getElementById("capture-interval-input").value || 1500),
      region: parseRegion(document.getElementById("capture-region-input").value),
    },
    translation: {
      endpoint: document.getElementById("translation-endpoint-input").value.trim(),
      model: document.getElementById("translation-model-input").value.trim(),
      timeoutS: state.config?.translation?.timeoutS ?? 30,
      batchSize: state.config?.translation?.batchSize ?? 5,
    },
    matching: {
      fuzzyThreshold: state.config?.matching?.fuzzyThreshold ?? 65,
      windowSize: state.config?.matching?.windowSize ?? 30,
    },
    overlay: {
      port: state.config?.overlay?.port ?? 8765,
      ...currentOverlayConfigFromForm(),
    },
  };
}

function updateDerivedOcrDisplay(ocrLanguage) {
  const resolved = ocrLanguage || deriveOcrLanguage(currentLanguageValue(dom.sourceLanguageInput, dom.sourceLanguageCustomInput));
  dom.ocrLanguageDisplay.textContent = resolved;

  const entry = state.languageCatalog?.ocr?.find((option) => option.code === resolved);
  const installed = entry ? entry.installed : false;
  if (installed) {
    dom.ocrLanguageNote.textContent = "OCR follows the selected source language automatically.";
    dom.ocrInstallButton.classList.add("hidden");
    dom.ocrInstallButton.dataset.languageTag = "";
    return;
  }

  const simplifiedFallback =
    resolved === "zh-TW" && state.languageCatalog?.ocr?.find((option) => option.code === "zh-CN")?.installed;
  dom.ocrLanguageNote.textContent = simplifiedFallback
    ? `${resolved} is not installed. Start Sync will fall back to zh-CN OCR, or you can install the Traditional pack.`
    : `${resolved} is not installed. Install the OCR pack or switch the source language.`;
  dom.ocrInstallButton.classList.remove("hidden");
  dom.ocrInstallButton.dataset.languageTag = resolved;
}

function setupTauriBridge() {
  if (!TAURI) {
    return;
  }
  dom.selectRegionButton.classList.remove("hidden");
  dom.selectRegionButton.addEventListener("click", async () => {
    try {
      await TAURI.core.invoke("open_area_selector");
    } catch (error) {
      setSaveState(String(error), "error");
    }
  });
  TAURI.event.listen("capture-region-selected", (event) => {
    const region = event.payload;
    if (!region) {
      return;
    }
    document.getElementById("capture-region-input").value = `${region.x},${region.y},${region.width},${region.height}`;
    setSaveState("Capture area selected", "success");
  });
}

function createElement(tagName, options = {}) {
  const element = document.createElement(tagName);
  if (options.className) {
    element.className = options.className;
  }
  if (options.text != null) {
    element.textContent = String(options.text);
  }
  if (options.attrs) {
    for (const [name, value] of Object.entries(options.attrs)) {
      if (value != null) {
        element.setAttribute(name, String(value));
      }
    }
  }
  if (options.dataset) {
    for (const [name, value] of Object.entries(options.dataset)) {
      if (value != null) {
        element.dataset[name] = String(value);
      }
    }
  }
  return element;
}

function appendBadge(container, text, className = "result-badge") {
  container.append(createElement("span", { className, text }));
}

function providerBadgeClass(provider) {
  const normalized = (provider || "source").toString().trim().toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return `result-badge provider-badge provider-${normalized}`;
}

function buildResultCard({
  resultId = "",
  selected = false,
  kind = "",
  title,
  tag = "",
  badges = [],
  fileText,
  footText,
}) {
  const classes = ["result-card"];
  if (selected) {
    classes.push("selected");
  }
  const card = createElement("button", {
    className: classes.join(" "),
    attrs: { type: "button" },
    dataset: { resultId, kind: kind || undefined },
  });

  const top = createElement("div", { className: "result-card-top" });
  top.append(createElement("h4", { className: "result-card-title", text: title }));
  if (tag) {
    top.append(createElement("span", { className: "result-card-tag", text: tag }));
  }
  card.append(top);

  if (badges.length) {
    const meta = createElement("div", { className: "result-card-meta" });
    for (const badge of badges) {
      if (typeof badge === "string") {
        appendBadge(meta, badge);
      } else if (badge && typeof badge === "object") {
        appendBadge(meta, badge.text, badge.className || "result-badge");
      }
    }
    card.append(meta);
  }

  card.append(createElement("p", { className: "result-card-file", text: fileText }));
  card.append(createElement("p", { className: "result-card-foot", text: footText }));
  return card;
}

function buildTitleMatchCard(match, selected = false) {
  const classes = ["title-match-card"];
  if (selected) {
    classes.push("selected");
  }
  const card = createElement("button", {
    className: classes.join(" "),
    attrs: { type: "button" },
    dataset: { matchId: matchSelectionId(match) || match.id || "" },
  });
  const top = createElement("div", { className: "result-card-top" });
  top.append(createElement("h4", { className: "result-card-title", text: match.displayLabel || match.title }));
  if (selected) {
    top.append(createElement("span", { className: "result-card-tag", text: "Selected" }));
  }
  card.append(top);
  const meta = createElement("div", { className: "result-card-meta" });
  appendBadge(meta, match.mediaType || "title");
  appendBadge(meta, `${(match.subtitlesCount || 0).toLocaleString()} subtitle files`);
  if (match.providerCount || providerLabelsForMatch(match).length) {
    appendBadge(meta, `${(match.providerCount || providerLabelsForMatch(match).length).toLocaleString()} sources`);
  }
  for (const label of providerLabelsForMatch(match).slice(0, 3)) {
    appendBadge(meta, label, providerBadgeClass(label));
  }
  card.append(meta);
  card.append(createElement("p", { className: "result-card-foot", text: "Use this title to scope source and target subtitle choices across enabled sources." }));
  return card;
}

function renderTitleMatches(matches, selectedFeatureId) {
  if (!matches.length) {
    dom.titleMatchResults.className = "title-match-results empty-state";
    dom.titleMatchResults.textContent = "Search to load matched shows and movies.";
    dom.titleMatchCount.textContent = "0 titles";
    return;
  }

  dom.titleMatchCount.textContent = `${matches.length} titles`;
  dom.titleMatchResults.className = "title-match-results";
  dom.titleMatchResults.replaceChildren(
    ...matches.map((match) => buildTitleMatchCard(match, sameSelectionValue(matchSelectionId(match), selectedFeatureId))),
  );
}

function buildSearchResultSummary(selectedMatch, sourceResults, targetResults, sourceSelectionMode, sourceLanguage) {
  if (!selectedMatch) {
    return "Pick a matched title first, then choose subtitles or OCR fallback.";
  }
  if (!sourceResults.length && !targetResults.length) {
    return `${selectedMatch.displayLabel || selectedMatch.title} matched, but no subtitle files fit the selected languages. OCR fallback is available.`;
  }
  if (!sourceResults.length && sourceSelectionMode === "ocr_fallback") {
    return `${selectedMatch.displayLabel || selectedMatch.title} has no ${languageLabel(sourceLanguage)} source subtitle. OCR fallback is selected${targetResults.length ? " and can still align against target subtitles." : "."}`;
  }
  if (!sourceResults.length) {
    return `${selectedMatch.displayLabel || selectedMatch.title} has no ${languageLabel(sourceLanguage)} source subtitle. Select OCR fallback to continue.`;
  }
  if (!targetResults.length) {
    return `${selectedMatch.displayLabel || selectedMatch.title} has ${sourceResults.length} source subtitle choices across enabled sources. Target can fall back to local translation.`;
  }
  return `${selectedMatch.displayLabel || selectedMatch.title}: ${sourceResults.length} source matches and ${targetResults.length} target matches ready.`;
}

function renderSourceResults(container, results, selectedId, requestedSourceLanguage = "", options = {}) {
  const { selectedMatch = null, sourceSelectionMode = "subtitle" } = options;
  if (!results.length && selectedMatch) {
    container.className = "result-list";
    container.replaceChildren(
      buildResultCard({
        resultId: "",
        kind: "ocr-fallback",
        selected: sourceSelectionMode === "ocr_fallback",
        title: "Use OCR source language",
        tag: "Fallback",
        badges: [languageLabel(requestedSourceLanguage), "No source file"],
        fileText: "No source subtitle file matches this title and language. Use OCR plus live AI translation instead.",
        footText: "If a target subtitle is selected, the live translation will try to align against it.",
      }),
    );
    return;
  }

  if (!results.length) {
    container.className = "result-list empty-state";
    container.textContent = "No results available for this language.";
    return;
  }

  container.className = "result-list";
  container.replaceChildren(
    ...results.map((result, index) => {
      const providerLabel = providerLabelText(result);
      const badges = providerLabel
        ? [{ text: providerLabel, className: providerBadgeClass(result.providerLabel || result.provider) }, languageLabel(result.language)]
        : [languageLabel(result.language)];
      if (normalizeLanguageCode(result.language) === normalizeLanguageCode(requestedSourceLanguage)) {
        badges.push("Exact language");
      }
      if (
        requestedSourceLanguage &&
        normalizeLanguageCode(result.language) !== normalizeLanguageCode(requestedSourceLanguage) &&
        isChineseFamily(requestedSourceLanguage) &&
        isChineseFamily(result.language)
      ) {
        badges.push("Chinese-family fallback");
      }
      return buildResultCard({
        resultId: resultSelectionId(result),
        selected: sameSelectionValue(resultSelectionId(result), selectedId) && sourceSelectionMode !== "ocr_fallback",
        title: result.displayLabel || result.title,
        tag: index === 0 ? "Recommended" : "",
        badges,
        fileText: result.fileName,
        footText: `${result.downloadCount.toLocaleString()} downloads${providerLabel ? ` via ${providerLabel}` : ""}`,
      });
    }),
  );
}

function renderTargetResults(container, results, selectedId, sourceSelectionMode = "subtitle") {
  container.className = "result-list";
  container.replaceChildren(
    buildResultCard({
      resultId: "",
      kind: "local",
      selected: selectedId == null,
      title: "Use local translation",
      tag: "Fallback",
      badges: ["No target file"],
      fileText:
        sourceSelectionMode === "ocr_fallback"
          ? "Prepare the session by translating live OCR text directly into the target language."
          : "Prepare the session by translating the selected source subtitle locally.",
      footText: "Best when no matching target subtitle looks trustworthy.",
    }),
    ...results.map((result, index) =>
      (() => {
        const providerLabel = providerLabelText(result);
        return buildResultCard({
          resultId: resultSelectionId(result),
          selected: sameSelectionValue(resultSelectionId(result), selectedId),
          title: result.displayLabel || result.title,
          tag: index === 0 ? "Best match" : "",
          badges: providerLabel
            ? [{ text: providerLabel, className: providerBadgeClass(result.providerLabel || result.provider) }, languageLabel(result.language)]
            : [languageLabel(result.language)],
          fileText: result.fileName,
          footText: `${result.downloadCount.toLocaleString()} downloads${providerLabel ? ` via ${providerLabel}` : ""}`,
        });
      })(),
    ),
  );
}

function renderSessionSummary(preparedSession) {
  if (!preparedSession) {
    dom.preparedSession.className = "session-summary empty-state";
    dom.preparedSession.textContent = "No session has been prepared yet.";
    dom.sessionBadge.textContent = "None";
    return;
  }

  dom.sessionBadge.textContent = preparedSession.session_id;
  dom.preparedSession.className = "session-summary";
  const summary = createElement("dl");
  const modeLabelMap = {
    subtitle_file: "Matched target subtitle",
    local_translation: "Local translation",
    target_subtitle_match: "OCR fallback + target subtitle match",
    direct_translation: "OCR fallback + direct AI translation",
  };
  const rows = [
    ["Title", preparedSession.title],
    ["Session Mode", preparedSession.session_mode === "ocr_fallback" ? "OCR fallback" : "Subtitle pair"],
    [
      "Source Provider",
      preparedSession.source_provider_label || preparedSession.sourceProviderLabel || "OCR source language",
    ],
    ["Source File", preparedSession.source_file_name || "OCR source language"],
    [
      "Target Provider",
      preparedSession.target_provider_label || preparedSession.targetProviderLabel || "Local translation",
    ],
    ["Target File", preparedSession.target_file_name || "Generated via translation"],
    [
      "Resolved Source",
      `${preparedSession.resolved_source_language}${preparedSession.source_language_mode !== "exact" ? " (fallback)" : ""}`,
    ],
    ["Source Lines", preparedSession.source_line_count],
    ["Translated Lines", preparedSession.translated_line_count],
    ["Mode", modeLabelMap[preparedSession.target_match_mode] || "Matched target subtitle"],
  ];
  for (const [term, description] of rows) {
    summary.append(createElement("dt", { text: term }));
    summary.append(createElement("dd", { text: description }));
  }
  dom.preparedSession.replaceChildren(summary);
}

function render() {
  if (!state.snapshot || !state.config) {
    return;
  }

  const snapshot = state.snapshot;
  const sourceLanguage =
    snapshot.source_language || currentLanguageValue(dom.sourceLanguageInput, dom.sourceLanguageCustomInput);
  const targetLanguage =
    snapshot.target_language || currentLanguageValue(dom.targetLanguageInput, dom.targetLanguageCustomInput);
  const searchResults = snapshot.search_results || [];
  const searchMatches = snapshot.search_matches || [];
  const selectedFeatureId = currentFeatureId(snapshot);
  const selectedMatch = searchMatches.find((match) => sameSelectionValue(matchSelectionId(match), selectedFeatureId)) || null;
  const filteredResults = searchResults.filter((result) => resultMatchesSelectedMatch(result, selectedFeatureId));
  const sourceResults = filteredResults
    .filter((result) => {
      if (normalizeLanguageCode(result.language) === normalizeLanguageCode(sourceLanguage)) {
        return true;
      }
      return isChineseFamily(sourceLanguage) && isChineseFamily(result.language);
    })
    .sort((left, right) => {
      const leftExact = normalizeLanguageCode(left.language) === normalizeLanguageCode(sourceLanguage) ? 0 : 1;
      const rightExact = normalizeLanguageCode(right.language) === normalizeLanguageCode(sourceLanguage) ? 0 : 1;
      return leftExact - rightExact;
    });
  const targetResults = filteredResults.filter(
    (result) => normalizeLanguageCode(result.language) === normalizeLanguageCode(targetLanguage),
  );
  const progress = snapshot.progress || {};
  const progressRatio = progress.total ? Math.min(progress.current / progress.total, 1) : 0;
  const selectedSource = selectedSourceResultId(snapshot);
  const selectedTarget = selectedTargetResultId(snapshot);
  const sourceSelectionMode = currentSourceSelectionMode(snapshot, sourceResults, selectedFeatureId);
  const fallbackSelected = sourceSelectionMode === "ocr_fallback" && !selectedSource;
  const progressIndeterminate = snapshot.status === "searching" || (progress.total === 0 && !!progress.message);
  const canPrepare = Boolean(selectedFeatureId) && (Boolean(selectedSource) || fallbackSelected);

  dom.statusChip.textContent = statusLabel(snapshot.status || "idle");
  dom.statusChip.className = `status-chip ${snapshot.status || "idle"}`;
  dom.statusMessage.textContent = sessionMessage(snapshot, selectedSource, selectedTarget);
  dom.progressStage.textContent = sessionHeadline(snapshot, selectedSource, selectedTarget);
  dom.progressMeta.textContent = progressSummary(snapshot, selectedSource);
  dom.progressFill.classList.toggle("is-indeterminate", progressIndeterminate);
  dom.progressFill.style.width = progressIndeterminate ? "42%" : `${progressRatio * 100}%`;
  dom.searchSubmitButton.disabled = !state.bootstrap.ready || snapshot.status === "searching";
  dom.searchSubmitButton.textContent = snapshot.status === "searching" ? "Searching…" : "Find Subtitles";
  dom.titleMatchStrip.classList.toggle("has-results", searchMatches.length > 0);
  renderTitleMatches(searchMatches, selectedFeatureId);
  dom.searchResultSummary.textContent = buildSearchResultSummary(
    selectedMatch,
    sourceResults,
    targetResults,
    sourceSelectionMode,
    sourceLanguage,
  );
  dom.sourceResultCount.textContent = `${sourceResults.length} results`;
  dom.targetResultCount.textContent = `${targetResults.length} results`;
  renderSourceResults(dom.sourceResults, sourceResults, selectedSource, sourceLanguage, {
    selectedMatch,
    sourceSelectionMode,
  });
  renderTargetResults(dom.targetResults, targetResults, selectedTarget, sourceSelectionMode);
  renderSessionSummary(snapshot.prepared_session);
  dom.currentSubtitle.textContent = snapshot.last_subtitle || "No subtitle broadcast yet.";
  dom.prepareButton.disabled = !state.bootstrap.ready || !canPrepare;
  dom.startButton.disabled = !state.bootstrap.ready || !(snapshot.prepared_session && snapshot.status !== "running");
  dom.stopButton.disabled = !state.bootstrap.ready || (snapshot.status !== "running" && snapshot.status !== "stopping");
  dom.prepareButton.textContent = snapshot.prepared_session ? "Prepare Again" : fallbackSelected ? "Prepare OCR Fallback" : "Prepare Session";
  dom.overlayLink.href = snapshot.overlay_url || apiUrl("/overlay");
}

function bindResultSelection() {
  dom.titleMatchResults.addEventListener("click", (event) => {
    const card = event.target.closest("[data-match-id], [data-feature-id]");
    if (!card) {
      return;
    }
    state.selectedFeatureId = selectionValue(card.dataset.matchId || card.dataset.featureId);
    state.selectedSourceFileId = null;
    state.selectedTargetFileId = null;
    state.sourceSelectionMode = null;
    scheduleRender();
  });

  dom.sourceResults.addEventListener("click", (event) => {
    const card = event.target.closest("[data-kind], [data-result-id], [data-file-id]");
    if (!card) {
      return;
    }
    if (card.dataset.kind === "ocr-fallback") {
      state.selectedSourceFileId = null;
      state.sourceSelectionMode = "ocr_fallback";
      scheduleRender();
      return;
    }
    state.selectedSourceFileId = selectionValue(card.dataset.resultId || card.dataset.fileId);
    state.sourceSelectionMode = "subtitle";
    scheduleRender();
  });

  dom.targetResults.addEventListener("click", (event) => {
    const card = event.target.closest("[data-result-id], [data-file-id]");
    if (!card) {
      return;
    }
    state.selectedTargetFileId = selectionValue(card.dataset.resultId || card.dataset.fileId);
    scheduleRender();
  });
}

function connectSocket() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  socket = new WebSocket(wsUrl("/ws/app"));
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "state") {
      state.snapshot = message.state;
      const matches = message.state.search_matches || [];
      const localFeatureStillValid = matches.some((match) => sameSelectionValue(matchSelectionId(match), state.selectedFeatureId));
      if (!localFeatureStillValid) {
        state.selectedFeatureId = currentFeatureId(message.state) ?? matchSelectionId(matches[0]) ?? null;
      }
    }
    if (message.type === "progress" && state.snapshot) {
      state.snapshot.progress = message.progress;
    }
    if (message.type === "subtitle" && state.snapshot) {
      state.snapshot.last_subtitle = message.text || "";
    }
    if (message.type === "style") {
      if (state.config) {
        state.config.overlay = { ...state.config.overlay, ...message.style };
      }
      applyStylePreview(message.style);
    }
    if (message.type === "error") {
      dom.statusMessage.textContent = message.message;
    }
    scheduleRender();
  };
  socket.onclose = () => {
    setTimeout(connectSocket, 1800);
  };
}

function ensureLanguageCatalog(catalog) {
  if (!catalog || !Array.isArray(catalog.sourceTarget) || catalog.sourceTarget.length === 0) {
    throw new Error("Language options failed to load. Retry startup.");
  }
}

async function loadInitialState() {
  const [config, snapshot, catalog] = await Promise.all([
    fetchJson("/api/config"),
    fetchJson("/api/state"),
    fetchJson("/api/languages"),
  ]);
  ensureLanguageCatalog(catalog);
  state.languageCatalog = catalog;
  state.config = config;
  state.snapshot = snapshot;
  fillConfigForm(config);
  populateLanguageSelect(dom.sourceLanguageInput, dom.sourceLanguageCustomInput, catalog.sourceTarget, config.languages.source);
  populateLanguageSelect(dom.targetLanguageInput, dom.targetLanguageCustomInput, catalog.sourceTarget, config.languages.target);
  updateDerivedOcrDisplay(config.capture.ocrLanguage);
  scheduleRender();
}

function setupLanguagePicker() {
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

for (const button of [dom.settingsOpenButton, dom.settingsInlineButton]) {
  button?.addEventListener("click", openSettingsDrawer);
}

dom.settingsCloseButton?.addEventListener("click", closeSettingsDrawer);
dom.settingsBackdrop?.addEventListener("click", closeSettingsDrawer);

dom.searchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.bootstrap.ready) {
    return;
  }
  setSaveState("Searching...", "busy");
  const sourceLanguage = currentLanguageValue(dom.sourceLanguageInput, dom.sourceLanguageCustomInput) || "en";
  const targetLanguage = currentLanguageValue(dom.targetLanguageInput, dom.targetLanguageCustomInput) || "zh";
  if (state.snapshot) {
    state.snapshot.status = "searching";
    state.snapshot.progress = { stage: "search", message: "Searching subtitle sources...", current: 0, total: 0 };
    scheduleRender();
  }
  try {
    const payload = await fetchJson("/api/search", {
      method: "POST",
      body: JSON.stringify({
        title: dom.titleInput.value.trim(),
        sourceLanguage,
        targetLanguage,
      }),
    });
    if (state.snapshot) {
      state.snapshot.search_results = payload.results;
      state.snapshot.search_matches = payload.matches;
      state.snapshot.title = dom.titleInput.value.trim();
      state.snapshot.source_language = sourceLanguage;
      state.snapshot.target_language = targetLanguage;
      state.snapshot.selected_match_id = matchSelectionId(payload.matches?.[0]);
      state.snapshot.selected_feature_id = numericSelectionValue(matchSelectionId(payload.matches?.[0]));
      state.snapshot.prepared_session = null;
    }
    state.selectedFeatureId = matchSelectionId(payload.matches?.[0]);
    state.selectedSourceFileId = null;
    state.selectedTargetFileId = null;
    state.sourceSelectionMode = null;
    setSaveState("Results ready", "success");
    scheduleRender();
  } catch (error) {
    setSaveState(error.message, "error");
  }
});

dom.prepareButton.addEventListener("click", async () => {
  if (!state.bootstrap.ready) {
    return;
  }
  const featureId = currentFeatureId(state.snapshot);
  const snapshotResults = (state.snapshot?.search_results || []).filter((result) => resultMatchesSelectedMatch(result, featureId));
  const sourceLanguage =
    state.snapshot?.source_language || currentLanguageValue(dom.sourceLanguageInput, dom.sourceLanguageCustomInput) || "en";
  const sourceResults = snapshotResults.filter((result) => {
    if (normalizeLanguageCode(result.language) === normalizeLanguageCode(sourceLanguage)) {
      return true;
    }
    return isChineseFamily(sourceLanguage) && isChineseFamily(result.language);
  });
  const sourceFileId = selectedSourceResultId(state.snapshot);
  const sourceSelectionMode = currentSourceSelectionMode(state.snapshot, sourceResults, featureId);
  const mode = sourceFileId ? "subtitle_pair" : sourceSelectionMode === "ocr_fallback" ? "ocr_fallback" : "";
  if (!featureId) {
    setSaveState("Select a matched title first", "error");
    return;
  }
  if (!mode) {
    setSaveState("Select a source subtitle or OCR fallback first", "error");
    return;
  }

  try {
    setSaveState("Preparing session...", "busy");
    const payload = await fetchJson("/api/session/prepare", {
      method: "POST",
      body: JSON.stringify({
        mode,
        matchId: featureId,
        featureId: numericSelectionValue(featureId),
        sourceResultId: sourceFileId,
        sourceFileId: numericSelectionValue(sourceFileId),
        targetResultId: selectedTargetResultId(state.snapshot),
        targetFileId: numericSelectionValue(selectedTargetResultId(state.snapshot)),
      }),
    });
    if (state.snapshot) {
      state.snapshot.prepared_session = payload.session;
      state.snapshot.selected_match_id = featureId;
      state.snapshot.selected_feature_id = numericSelectionValue(featureId);
      state.snapshot.selected_source_result_id = sourceFileId;
      state.snapshot.selected_source_file_id = numericSelectionValue(sourceFileId);
      state.snapshot.selected_target_result_id = selectedTargetResultId(state.snapshot);
      state.snapshot.selected_target_file_id = numericSelectionValue(selectedTargetResultId(state.snapshot));
    }
    setSaveState("Session prepared", "success");
    scheduleRender();
  } catch (error) {
    setSaveState(error.message, "error");
  }
});

dom.startButton.addEventListener("click", async () => {
  if (!state.bootstrap.ready) {
    return;
  }
  const sessionId = state.snapshot?.prepared_session?.session_id;
  if (!sessionId) {
    setSaveState("Prepare a session before starting", "error");
    return;
  }

  try {
    if (!TAURI && (!state.overlayWindow || state.overlayWindow.closed)) {
      state.overlayWindow = window.open("/overlay", "meowcal-overlay", "width=1280,height=320");
    }
    setSaveState("Starting sync...", "busy");
    await fetchJson("/api/session/start", {
      method: "POST",
      body: JSON.stringify({ sessionId }),
    });
    if (TAURI) {
      await TAURI.core.invoke("show_capture_hud");
      await TAURI.core.invoke("hide_main_window");
    }
    setSaveState("Sync running", "success");
  } catch (error) {
    setSaveState(error.message, "error");
  }
});

dom.stopButton.addEventListener("click", async () => {
  if (!state.bootstrap.ready) {
    return;
  }
  try {
    setSaveState("Stopping session...", "busy");
    await fetchJson("/api/session/stop", { method: "POST" });
    setSaveState("Session stopped", "success");
  } catch (error) {
    setSaveState(error.message, "error");
  }
});

dom.configForm.addEventListener("input", () => {
  if (!state.bootstrap.ready) {
    return;
  }
  setSaveState("Unsaved changes", "neutral");
  applyStylePreview(currentOverlayConfigFromForm());
});

for (const [selectEl, customInput] of [
  [dom.sourceLanguageInput, dom.sourceLanguageCustomInput],
  [dom.targetLanguageInput, dom.targetLanguageCustomInput],
]) {
  selectEl.addEventListener("change", () => {
    if (!state.bootstrap.ready) {
      return;
    }
    syncCustomLanguageInput(selectEl, customInput);
    updateLanguageTrigger(selectEl);
    updateDerivedOcrDisplay(deriveOcrLanguage(currentLanguageValue(dom.sourceLanguageInput, dom.sourceLanguageCustomInput)));
    setSaveState("Unsaved changes", "neutral");
    scheduleRender();
  });
  customInput.addEventListener("input", () => {
    if (!state.bootstrap.ready) {
      return;
    }
    updateLanguageTrigger(selectEl);
    updateDerivedOcrDisplay(deriveOcrLanguage(currentLanguageValue(dom.sourceLanguageInput, dom.sourceLanguageCustomInput)));
    setSaveState("Unsaved changes", "neutral");
    scheduleRender();
  });
}

dom.ocrInstallButton.addEventListener("click", async () => {
  if (!state.bootstrap.ready) {
    return;
  }
  const languageTag = dom.ocrInstallButton.dataset.languageTag;
  if (!languageTag) {
    return;
  }
  try {
    setSaveState("Launching OCR installer...", "busy");
    const payload = await fetchJson("/api/ocr/install", {
      method: "POST",
      body: JSON.stringify({ languageTag }),
    });
    const catalog = await fetchJson("/api/languages");
    state.languageCatalog = catalog;
    updateDerivedOcrDisplay(languageTag);
    setSaveState(payload.message, payload.installed ? "success" : "error");
  } catch (error) {
    setSaveState(error.message, "error");
  }
});

dom.configForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.bootstrap.ready) {
    return;
  }
  try {
    setSaveState("Saving config...", "busy");
    const config = await fetchJson("/api/config", {
      method: "PUT",
      body: JSON.stringify(buildConfigPayload()),
    });
    state.config = config;
    fillConfigForm(config);
    renderFoundryStatus(await fetchJson("/api/foundry/status"));
    setSaveState("Config saved", "success");
    scheduleRender();
  } catch (error) {
    setSaveState(error.message, "error");
  }
});

bindResultSelection();
setupLanguagePicker();
setupTauriBridge();
setControlsDisabled(true);

function dismissLoadingOverlay() {
  if (!dom.loadingOverlay) {
    return;
  }
  dom.loadingSpinner?.classList.add("hidden");
  dom.loadingOverlay.remove();
  dom.loadingOverlay = null;
}

function probeFoundryStatus() {
  renderFoundryStatus({
    phase: "unchecked",
    notes: "Checking Foundry Local status...",
  });
  fetchJson("/api/foundry/status?probe=true")
    .then(renderFoundryStatus)
    .catch(() => renderFoundryStatus(null));
}

async function bootstrapApp() {
  if (bootstrapPromise) {
    return bootstrapPromise;
  }
  bootstrapPromise = (async () => {
    setBootstrapLoading("Loading studio...", "Preparing languages and saved settings.");
    setSaveState("Loading studio...", "busy");
    try {
      await loadInitialState();
      render();
      await waitForNextPaint();
      state.bootstrap.loading = false;
      state.bootstrap.ready = true;
      setControlsDisabled(false);
      render();
      await waitForNextPaint();
      dismissLoadingOverlay();
      connectSocket();
      probeFoundryStatus();
      setSaveState("Studio ready", "success");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setBootstrapError(message);
      setSaveState(message, "error");
      renderFoundryStatus({
        phase: "unchecked",
        notes: "Foundry status will be checked after startup completes.",
      });
    } finally {
      bootstrapPromise = null;
    }
  })();
  return bootstrapPromise;
}

dom.loadingRetry.addEventListener("click", () => {
  bootstrapApp();
});

bootstrapApp();
