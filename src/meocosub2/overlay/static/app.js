const dom = {
  appShell: document.getElementById("app-shell"),
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
  resultsSelectionSummary: document.getElementById("results-selection-summary"),
  sourceResults: document.getElementById("source-results"),
  targetResults: document.getElementById("target-results"),
  sourceResultCount: document.getElementById("source-result-count"),
  targetResultCount: document.getElementById("target-result-count"),
  preparedSession: document.getElementById("prepared-session"),
  sessionBadge: document.getElementById("session-badge"),
  currentSubtitle: document.getElementById("current-subtitle"),
  heroEyebrow: document.getElementById("hero-eyebrow"),
  heroTitleMain: document.getElementById("hero-title-main"),
  heroTitleAccent: document.getElementById("hero-title-accent"),
  heroSubcopy: document.getElementById("hero-subcopy"),
  dashboardSummaryMatches: document.getElementById("dashboard-summary-matches"),
  dashboardSummaryResults: document.getElementById("dashboard-summary-results"),
  dashboardSummarySession: document.getElementById("dashboard-summary-session"),
  resultsViewTitle: document.getElementById("results-view-title"),
  resultsViewCopy: document.getElementById("results-view-copy"),
  resultsFlow: document.getElementById("results-flow"),
  resultsBackButton: document.getElementById("results-back-button"),
  resultsStepPill: document.getElementById("results-step-pill"),
  resultsProviderPill: document.getElementById("results-provider-pill"),
  resultsPrepareButton: document.getElementById("results-prepare-button"),
  sourceStage: document.getElementById("source-stage"),
  targetStage: document.getElementById("target-stage"),
  sessionViewTitle: document.getElementById("session-view-title"),
  sessionViewCopy: document.getElementById("session-view-copy"),
  sessionPreviewLabel: document.getElementById("session-preview-label"),
  sessionFoundryState: document.getElementById("session-foundry-state"),
  sessionFoundryNote: document.getElementById("session-foundry-note"),
  sessionOcrState: document.getElementById("session-ocr-state"),
  sessionOcrNote: document.getElementById("session-ocr-note"),
  sessionCaptureState: document.getElementById("session-capture-state"),
  sessionSelectRegionButton: document.getElementById("session-select-region-button"),
  footerSessionStatus: document.getElementById("footer-session-status"),
  footerBackendStatus: document.getElementById("footer-backend-status"),
  footerOcrStatus: document.getElementById("footer-ocr-status"),
  prepareButton: document.getElementById("prepare-button"),
  startButton: document.getElementById("start-button"),
  stopButton: document.getElementById("stop-button"),
  windowMinimizeButton: document.getElementById("window-minimize-button"),
  windowMaximizeButton: document.getElementById("window-maximize-button"),
  windowCloseButton: document.getElementById("window-close-button"),
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
  targetSelectionMode: null,
  overlayWindow: null,
  activeLanguagePicker: null,
  ui: {
    settingsOpen: false,
    manualView: null,
    resultsStepOverride: null,
  },
  bootstrap: {
    ready: false,
    loading: false,
  },
  languagePersistence: {
    saving: false,
    pendingKey: null,
    lastSavedKey: null,
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
  scheduleRender();
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

function currentLanguagePreferences() {
  const source = currentLanguageValue(dom.sourceLanguageInput, dom.sourceLanguageCustomInput);
  const target = currentLanguageValue(dom.targetLanguageInput, dom.targetLanguageCustomInput);
  if (!source || !target) {
    return null;
  }
  return { source, target };
}

function languagePreferenceKey(languages) {
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

function persistLanguagePreferences() {
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

function assrtCoverageHint(sourceLanguage) {
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
  return "subtitle";
}

function currentResultsStep(snapshot) {
  if (!currentFeatureId(snapshot)) {
    return "title";
  }
  if (!selectedSourceResultId(snapshot) && currentSourceSelectionMode(snapshot, [], currentFeatureId(snapshot)) !== "ocr_fallback") {
    return "source";
  }
  return "target";
}

function currentVisibleResultsStep(snapshot) {
  const forcedStep = state.ui.resultsStepOverride;
  if (forcedStep === "source" && currentFeatureId(snapshot)) {
    return "source";
  }
  if (forcedStep === "title") {
    return "title";
  }
  return currentResultsStep(snapshot);
}

function currentTargetSelectionMode(snapshot) {
  if (state.targetSelectionMode) {
    return state.targetSelectionMode;
  }
  if (selectedTargetResultId(snapshot)) {
    return "file";
  }
  if (snapshot?.prepared_session) {
    return snapshot.prepared_session.target_match_mode === "subtitle_file" ? "file" : "local";
  }
  return null;
}

function hasCaptureRegion() {
  const region = parseRegion(document.getElementById("capture-region-input")?.value || "");
  return region.length === 4 && region[2] > 0 && region[3] > 0;
}

async function openCaptureRegionSelector() {
  if (!TAURI) {
    openSettingsDrawer();
    document.getElementById("capture-region-input")?.focus();
    return;
  }
  await TAURI.core.invoke("open_area_selector");
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
  const targetSelectionMode = currentTargetSelectionMode(snapshot);
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
  if (selectedSource && !targetSelectionMode) {
    return "Choose a target subtitle or confirm local translation";
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
  const targetSelectionMode = currentTargetSelectionMode(snapshot);
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
  if (selectedSource && !targetSelectionMode) {
    return "Choose a target subtitle or click local translation to confirm the target step.";
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
  const targetSelectionMode = currentTargetSelectionMode(snapshot);
  if (snapshot.progress?.message) {
    return snapshot.progress.message;
  }
  if (snapshot.prepared_session) {
    return snapshot.prepared_session.session_mode === "ocr_fallback"
      ? "Prepared OCR fallback session will translate live OCR and optionally align against target subtitles."
      : "Prepared session is ready for the next viewing run.";
  }
  if (selectedSource && !targetSelectionMode) {
    return "Confirm the target side before preparing the session.";
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

function navButtons() {
  return Array.from(document.querySelectorAll("[data-view-target]"));
}

function availableShellView(snapshot) {
  if (state.ui.settingsOpen) {
    return "settings";
  }
  if (snapshot.status === "running" || snapshot.status === "preparing" || snapshot.status === "stopping" || snapshot.prepared_session) {
    return "session";
  }
  if ((snapshot.search_matches || []).length || (snapshot.search_results || []).length) {
    return "results";
  }
  return "dashboard";
}

function currentShellView(snapshot) {
  if (state.ui.settingsOpen) {
    return "settings";
  }

  const preferred = state.ui.manualView;
  if (preferred === "dashboard") {
    return "dashboard";
  }
  if (preferred === "results" && ((snapshot.search_matches || []).length || (snapshot.search_results || []).length)) {
    return "results";
  }
  if (preferred === "session" && (snapshot.prepared_session || snapshot.status === "running" || snapshot.status === "preparing" || snapshot.status === "stopping")) {
    return "session";
  }
  return availableShellView(snapshot);
}

function renderShellChrome(view, snapshot, selectedMatch, sourceLanguage, targetLanguage) {
  dom.appShell?.setAttribute("data-view", view);
  document.body?.setAttribute("data-view", view);
  document.body.dataset.view = view;

  for (const button of navButtons()) {
    const target = button.dataset.viewTarget;
    const active = target === view;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  }

  const resultsReady = Boolean((snapshot.search_matches || []).length || (snapshot.search_results || []).length);
  const sessionReady = Boolean(snapshot.prepared_session || snapshot.status === "running" || snapshot.status === "preparing" || snapshot.status === "stopping");
  for (const button of navButtons()) {
    const target = button.dataset.viewTarget;
    if (target === "results") {
      button.disabled = !resultsReady && view !== "results";
    } else if (target === "session") {
      button.disabled = !sessionReady && view !== "session";
    } else {
      button.disabled = false;
    }
  }

  if (view === "results") {
    dom.heroEyebrow.textContent = "Search Results For";
    dom.heroTitleMain.textContent = selectedMatch?.displayLabel || snapshot.title || "Search results ";
    dom.heroTitleAccent.textContent = "ready";
    dom.heroSubcopy.textContent = "Select source and target files to begin your synchronization session.";
  } else if (view === "session") {
    dom.heroEyebrow.textContent = "Session Status";
    dom.heroTitleMain.textContent = "Session ";
    dom.heroTitleAccent.textContent = snapshot.status === "running" ? "live" : "ready";
    dom.heroSubcopy.textContent = sessionMessage(snapshot, selectedSourceResultId(snapshot), selectedTargetResultId(snapshot));
  } else {
    dom.heroEyebrow.textContent = "Console Mode";
    dom.heroTitleMain.textContent = "What do you want to ";
    dom.heroTitleAccent.textContent = "watch?";
    dom.heroSubcopy.textContent = "Search by title first, pick the best subtitle pair, then prepare a session before starting live sync.";
  }

  dom.dashboardSummaryMatches.textContent = String((snapshot.search_matches || []).length);
  dom.dashboardSummaryResults.textContent = String((snapshot.search_results || []).length);
  dom.dashboardSummarySession.textContent = statusLabel(snapshot.status || "idle");

  dom.sessionViewTitle.textContent = snapshot.status === "running" ? "Session Live" : "Session Ready";
  dom.sessionViewCopy.textContent =
    snapshot.prepared_session && !hasCaptureRegion()
      ? "Session prepared. Select the subtitle capture area next, then start sync."
      : sessionMessage(snapshot, selectedSourceResultId(snapshot), selectedTargetResultId(snapshot));
  dom.sessionPreviewLabel.textContent = snapshot.prepared_session?.session_mode === "ocr_fallback" ? "OCR Fallback" : "Subtitle Pair";
  dom.sessionFoundryState.textContent = dom.foundryStatusChip?.textContent || "Unchecked";
  dom.sessionFoundryNote.textContent = dom.foundryStatusNote?.textContent || "Waiting for status probe.";
  dom.sessionOcrState.textContent = dom.ocrLanguageDisplay?.textContent || "Follows source language";
  dom.sessionOcrNote.textContent = dom.ocrLanguageNote?.textContent || "Capture language follows the selected source language.";
  dom.sessionCaptureState.textContent = document.getElementById("capture-region-input")?.value?.trim() || "Not set";

  dom.footerSessionStatus.textContent = `Session: ${statusLabel(snapshot.status || "idle")}`;
  dom.footerBackendStatus.textContent = `Backend: ${state.bootstrap.ready ? "Connected" : "Starting"}`;
  dom.footerOcrStatus.textContent = `OCR: ${dom.ocrLanguageDisplay?.textContent || "Follows source language"}`;
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
  root.style.setProperty("--overlay-offset", `${overlay.offsetPct}%`);
  root.style.setProperty("--overlay-animation-ms", `${overlay.animationMs}ms`);
  const previewShell = document.getElementById("preview-shell");
  if (previewShell) {
    previewShell.dataset.position = overlay.position || "bottom";
  }
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

function setupTauriBridge() {
  if (!TAURI) {
    dom.windowMinimizeButton?.classList.add("hidden");
    dom.windowMaximizeButton?.classList.add("hidden");
    dom.windowCloseButton?.classList.add("hidden");
    return;
  }

  document.body.classList.add("tauri-shell");
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
    setSaveState(
      state.snapshot?.prepared_session ? "Capture area selected. You can start sync now." : "Capture area selected",
      "success",
    );
    scheduleRender();
  });

  dom.windowMinimizeButton?.addEventListener("click", async () => {
    try {
      await TAURI.core.invoke("minimize_main_window");
    } catch (error) {
      setSaveState(String(error), "error");
    }
  });

  dom.windowMaximizeButton?.addEventListener("click", async () => {
    try {
      const maximized = await TAURI.core.invoke("toggle_main_window_maximize");
      dom.windowMaximizeButton.dataset.maximized = String(Boolean(maximized));
    } catch (error) {
      setSaveState(String(error), "error");
    }
  });

  dom.windowCloseButton?.addEventListener("click", async () => {
    try {
      await TAURI.core.invoke("close_main_window");
    } catch (error) {
      setSaveState(String(error), "error");
    }
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
  tagName = "button",
  className = "",
  attrs = {},
  dataset = {},
}) {
  const classes = ["result-card"];
  if (className) {
    classes.push(className);
  }
  if (tagName !== "button") {
    classes.push("result-card-static");
  }
  if (selected) {
    classes.push("selected");
  }
  const cardAttrs = { ...attrs };
  if (tagName === "button") {
    cardAttrs.type = cardAttrs.type || "button";
  }
  const card = createElement(tagName, {
    className: classes.join(" "),
    attrs: cardAttrs,
    dataset: { resultId, kind: kind || undefined, ...dataset },
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

  if (fileText) {
    card.append(createElement("p", { className: "result-card-file", text: fileText }));
  }
  if (footText) {
    card.append(createElement("p", { className: "result-card-foot", text: footText }));
  }
  return card;
}

function buildTitleMatchCard(match, selected = false, options = {}) {
  const { tagName = "button", className = "", attrs = {}, dataset = {} } = options;
  const classes = ["title-match-card"];
  if (className) {
    classes.push(className);
  }
  if (tagName !== "button") {
    classes.push("result-card-static");
  }
  if (selected) {
    classes.push("selected");
  }
  const cardAttrs = { ...attrs };
  if (tagName === "button") {
    cardAttrs.type = cardAttrs.type || "button";
  }
  const card = createElement(tagName, {
    className: classes.join(" "),
    attrs: cardAttrs,
    dataset: { matchId: matchSelectionId(match) || match.id || "", ...dataset },
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

function resultDownloadFootText(result) {
  const providerLabel = providerLabelText(result);
  return `${result.downloadCount.toLocaleString()} downloads${providerLabel ? ` via ${providerLabel}` : ""}`;
}

function sourceResultBadges(result, requestedSourceLanguage = "") {
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
  return badges;
}

function targetResultBadges(result) {
  const providerLabel = providerLabelText(result);
  return providerLabel
    ? [{ text: providerLabel, className: providerBadgeClass(result.providerLabel || result.provider) }, languageLabel(result.language)]
    : [languageLabel(result.language)];
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
  const targetSelectionMode = currentTargetSelectionMode(state.snapshot);
  const coverageHint = assrtCoverageHint(sourceLanguage);
  if (!selectedMatch) {
    return "Pick a matched title first, then choose subtitles or OCR fallback.";
  }
  if (!sourceResults.length && !targetResults.length) {
    return `${selectedMatch.displayLabel || selectedMatch.title} matched, but no subtitle files fit the selected languages. OCR fallback is available.${coverageHint ? ` ${coverageHint}` : ""}`;
  }
  if (!sourceResults.length && sourceSelectionMode === "ocr_fallback") {
    return `${selectedMatch.displayLabel || selectedMatch.title} has no ${languageLabel(sourceLanguage)} source subtitle. OCR fallback is selected${targetResults.length ? " and can still align against target subtitles." : "."}${coverageHint ? ` ${coverageHint}` : ""}`;
  }
  if (!sourceResults.length) {
    return `${selectedMatch.displayLabel || selectedMatch.title} has no ${languageLabel(sourceLanguage)} source subtitle. Select OCR fallback to continue.${coverageHint ? ` ${coverageHint}` : ""}`;
  }
  if (!targetSelectionMode) {
    return `${selectedMatch.displayLabel || selectedMatch.title} is ready on the source side. Pick a target subtitle or click local translation to confirm the target step.${coverageHint ? ` ${coverageHint}` : ""}`;
  }
  if (!targetResults.length) {
    return `${selectedMatch.displayLabel || selectedMatch.title} has ${sourceResults.length} source subtitle choices across enabled sources. Target can fall back to local translation.`;
  }
  return `${selectedMatch.displayLabel || selectedMatch.title}: ${sourceResults.length} source matches and ${targetResults.length} target matches ready.`;
}

function renderSourceResults(container, results, selectedId, requestedSourceLanguage = "", options = {}) {
  const { selectedMatch = null, sourceSelectionMode = "subtitle" } = options;
  if (!results.length && selectedMatch) {
    const coverageHint = assrtCoverageHint(requestedSourceLanguage);
    container.className = "result-list";
    container.replaceChildren(
      buildResultCard({
        resultId: "",
        kind: "ocr-fallback",
        selected: sourceSelectionMode === "ocr_fallback",
        title: "Use OCR source language",
        tag: "Fallback",
        badges: [languageLabel(requestedSourceLanguage), "No source file"],
        fileText: `No source subtitle file matches this title and language.${coverageHint ? ` ${coverageHint}` : ""} Use OCR plus live AI translation instead.`,
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
      return buildResultCard({
        resultId: resultSelectionId(result),
        selected: sameSelectionValue(resultSelectionId(result), selectedId) && sourceSelectionMode !== "ocr_fallback",
        title: result.displayLabel || result.title,
        tag: index === 0 ? "Recommended" : "",
        badges: sourceResultBadges(result, requestedSourceLanguage),
        fileText: result.fileName,
        footText: resultDownloadFootText(result),
      });
    }),
  );
}

function renderTargetResults(container, results, selectedId, sourceSelectionMode = "subtitle", targetSelectionMode = null) {
  container.className = "result-list";
  container.replaceChildren(
    buildResultCard({
      resultId: "",
      kind: "local",
      selected: targetSelectionMode === "local",
      title: "Use local translation",
      tag: targetSelectionMode === "local" ? "Confirmed" : "Fallback",
      badges: ["No target file"],
      fileText:
        sourceSelectionMode === "ocr_fallback"
          ? "Prepare the session by translating live OCR text directly into the target language."
          : "Prepare the session by translating the selected source subtitle locally.",
      footText: targetSelectionMode === "local" ? "Local translation confirmed for this session." : "Click to confirm local translation when no matching target subtitle looks trustworthy.",
    }),
    ...results.map((result, index) =>
      (() => {
        return buildResultCard({
          resultId: resultSelectionId(result),
          selected: sameSelectionValue(resultSelectionId(result), selectedId) && targetSelectionMode === "file",
          title: result.displayLabel || result.title,
          tag: sameSelectionValue(resultSelectionId(result), selectedId) && targetSelectionMode === "file" ? "Selected" : index === 0 ? "Best match" : "",
          badges: targetResultBadges(result),
          fileText: result.fileName,
          footText: resultDownloadFootText(result),
        });
      })(),
    ),
  );
}

function buildResultsSummaryRow({ label, value, meta = "", status = "", statusKind = "pending", badges = [] }) {
  const row = createElement("section", { className: `results-summary-row is-${statusKind}` });
  const top = createElement("div", { className: "results-summary-row-top" });
  top.append(createElement("p", { className: "results-summary-row-label", text: label }));
  if (status) {
    top.append(createElement("span", { className: `results-summary-row-status is-${statusKind}`, text: status }));
  }
  row.append(top);
  row.append(createElement("p", { className: "results-summary-row-value", text: value }));
  if (meta) {
    row.append(createElement("p", { className: "results-summary-row-meta", text: meta }));
  }
  if (badges.length) {
    const badgeRow = createElement("div", { className: "results-summary-badges" });
    for (const badge of badges) {
      if (typeof badge === "string") {
        appendBadge(badgeRow, badge, "result-badge results-summary-badge");
      } else if (badge?.text) {
        appendBadge(badgeRow, badge.text, badge.className || "result-badge results-summary-badge");
      }
    }
    row.append(badgeRow);
  }
  return row;
}

function renderResultsFlow(resultsStep, sourceSelectionMode, targetSelectionMode) {
  if (!dom.resultsFlow) {
    return;
  }

  const steps = Array.from(dom.resultsFlow.querySelectorAll("[data-flow-step]"));
  const completed = {
    title: resultsStep !== "title",
    source: resultsStep === "target" || sourceSelectionMode === "ocr_fallback",
    target: Boolean(targetSelectionMode),
  };

  for (const step of steps) {
    const stepKey = step.dataset.flowStep;
    const isCurrent = stepKey === resultsStep;
    const isComplete = completed[stepKey] && !isCurrent;
    step.classList.toggle("is-current", isCurrent);
    step.classList.toggle("is-complete", isComplete);
    step.classList.toggle("is-pending", !isCurrent && !isComplete);
  }

  const dividers = Array.from(dom.resultsFlow.querySelectorAll(".results-flow-divider"));
  if (dividers[0]) {
    dividers[0].classList.toggle("is-complete", completed.title);
  }
  if (dividers[1]) {
    dividers[1].classList.toggle("is-complete", completed.source);
  }
}

function renderResultsSelectionSummary({
  snapshot,
  resultsStep,
  selectedMatch,
  selectedSourceResult,
  selectedTargetResult,
  searchMatches,
  filteredResults,
  sourceResults,
  targetResults,
  sourceSelectionMode,
  targetSelectionMode,
  sourceLanguage,
  targetLanguage,
}) {
  if (!dom.resultsSelectionSummary) {
    return;
  }

  const hasSearchState = Boolean(snapshot.title || searchMatches.length || filteredResults.length);
  if (!hasSearchState) {
    dom.resultsSelectionSummary.className = "results-selection-summary empty-state";
    dom.resultsSelectionSummary.textContent = "Search to review the active title and subtitle choices.";
    return;
  }

  let summaryRow;
  if (resultsStep === "title") {
    const titleBadges = selectedMatch
      ? [
          selectedMatch.mediaType || "title",
          `${(selectedMatch.subtitlesCount || 0).toLocaleString()} subtitle files`,
          `${(selectedMatch.providerCount || providerLabelsForMatch(selectedMatch).length).toLocaleString()} sources`,
        ].filter(Boolean)
      : [`${searchMatches.length} matches ready`];
    summaryRow = buildResultsSummaryRow({
      label: "Title",
      value: selectedMatch?.displayLabel || selectedMatch?.title || "Pick a matched title",
      meta: selectedMatch
        ? snapshot.title && selectedMatch.displayLabel !== snapshot.title
          ? `Search: ${snapshot.title}`
          : "Matched title selected"
        : "Choose the best title from the right pane to continue.",
      status: selectedMatch ? "Selected" : "Pending",
      statusKind: selectedMatch ? "selected" : "pending",
      badges: titleBadges.slice(0, 3),
    });
  } else if (resultsStep === "source") {
    const sourceBadges = selectedSourceResult
      ? sourceResultBadges(selectedSourceResult, sourceLanguage).slice(0, 2)
      : [languageLabel(sourceLanguage)];
    summaryRow = buildResultsSummaryRow({
      label: "Source",
      value: selectedSourceResult
        ? selectedSourceResult.displayLabel || selectedSourceResult.title
        : sourceSelectionMode === "ocr_fallback"
          ? "OCR source fallback"
          : "Choose a source subtitle",
      meta: selectedSourceResult
        ? `Title: ${selectedMatch?.displayLabel || selectedMatch?.title || snapshot.title || "Selected match"}`
        : sourceSelectionMode === "ocr_fallback"
          ? `Title: ${selectedMatch?.displayLabel || selectedMatch?.title || snapshot.title || "Selected match"}`
          : "Select a source subtitle from the right pane.",
      status: selectedSourceResult ? "Selected" : sourceSelectionMode === "ocr_fallback" ? "Fallback" : "Pending",
      statusKind: selectedSourceResult ? "selected" : sourceSelectionMode === "ocr_fallback" ? "fallback" : "pending",
      badges: sourceBadges,
    });
  } else {
    const targetBadges = selectedTargetResult
      ? targetResultBadges(selectedTargetResult).slice(0, 2)
      : [languageLabel(targetLanguage)];
    summaryRow = buildResultsSummaryRow({
      label: "Target",
      value: selectedTargetResult
        ? selectedTargetResult.displayLabel || selectedTargetResult.title
        : targetSelectionMode === "local"
          ? "Local translation"
          : "Choose a target subtitle",
      meta: selectedSourceResult
        ? `Source: ${selectedSourceResult.displayLabel || selectedSourceResult.title}`
        : sourceSelectionMode === "ocr_fallback"
          ? "Source: OCR fallback"
          : "Confirm the target side to enable session prep.",
      status: selectedTargetResult ? "Selected" : targetSelectionMode === "local" ? "Confirmed" : "Pending",
      statusKind: selectedTargetResult ? "selected" : targetSelectionMode === "local" ? "confirmed" : "pending",
      badges: targetBadges,
    });
  }

  dom.resultsSelectionSummary.className = "results-selection-summary";
  dom.resultsSelectionSummary.replaceChildren(summaryRow);
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
  const summary = createElement("div", { className: "session-summary-stack" });
  const hero = createElement("div", { className: "session-summary-hero" });
  hero.append(createElement("p", { className: "session-summary-label", text: preparedSession.title }));
  hero.append(
    createElement("h3", {
      className: "session-summary-title",
      text: preparedSession.session_mode === "ocr_fallback" ? "OCR Fallback Session" : "Subtitle Pair Ready",
    }),
  );
  hero.append(
    createElement("p", {
      className: "session-summary-copy",
      text:
        preparedSession.session_mode === "ocr_fallback"
          ? "Live OCR will translate on-screen text and align against a target file when possible."
          : "The selected subtitle files are calibrated and ready for the next viewing run.",
    }),
  );
  summary.append(hero);

  const chips = createElement("div", { className: "session-summary-chip-row" });
  chips.append(createElement("span", { className: "session-summary-chip", text: preparedSession.source_provider_label || preparedSession.sourceProviderLabel || "OCR source" }));
  chips.append(createElement("span", { className: "session-summary-chip", text: preparedSession.target_provider_label || preparedSession.targetProviderLabel || "Local translation" }));
  chips.append(createElement("span", { className: "session-summary-chip", text: preparedSession.session_id }));
  summary.append(chips);

  const grid = createElement("dl");
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
    grid.append(createElement("dt", { text: term }));
    grid.append(createElement("dd", { text: description }));
  }
  summary.append(grid);
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
  const sourceSelectionMode = currentSourceSelectionMode(snapshot, sourceResults, selectedFeatureId);
  const selectedSource = selectedSourceResultId(snapshot);
  const selectedTarget = selectedTargetResultId(snapshot);
  const targetSelectionMode = currentTargetSelectionMode(snapshot);
  const selectedSourceResult = filteredResults.find((result) => sameSelectionValue(resultSelectionId(result), selectedSource)) || null;
  const selectedTargetResult = filteredResults.find((result) => sameSelectionValue(resultSelectionId(result), selectedTarget)) || null;
  const fallbackSelected = sourceSelectionMode === "ocr_fallback" && !selectedSource;
  const progressIndeterminate = snapshot.status === "searching" || (progress.total === 0 && !!progress.message);
  const targetConfirmed = Boolean(targetSelectionMode);
  const captureRegionReady = hasCaptureRegion();
  const resultsStep = currentVisibleResultsStep(snapshot);
  const canPrepare = Boolean(selectedFeatureId) && (Boolean(selectedSource) || fallbackSelected) && targetConfirmed;
  const shellView = currentShellView(snapshot);
  const sourceCoverageHint = assrtCoverageHint(sourceLanguage);

  renderShellChrome(shellView, snapshot, selectedMatch, sourceLanguage, targetLanguage);
  document.body.dataset.resultsStep = resultsStep;
  dom.appShell?.setAttribute("data-results-step", resultsStep);

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
  renderResultsFlow(resultsStep, sourceSelectionMode, targetSelectionMode);
  if (resultsStep === "title") {
    dom.resultsViewTitle.textContent = snapshot.title ? `Matches For ${snapshot.title}` : "Choose a matched title";
    dom.resultsViewCopy.textContent = "Choose the right title from the list.";
    dom.resultsProviderPill.textContent = `${searchMatches.length} title matches`;
    dom.searchResultSummary.textContent = "Step 1 of 3. Pick a matched title first.";
  } else if (resultsStep === "source") {
    dom.resultsViewTitle.textContent = selectedMatch?.displayLabel || "Choose source subtitle";
    dom.resultsViewCopy.textContent = sourceCoverageHint
      ? `Select the source subtitle you want to sync against. ${sourceCoverageHint}`
      : "Select the source subtitle you want to sync against.";
    dom.resultsProviderPill.textContent = `${sourceResults.length} source choices`;
    dom.searchResultSummary.textContent = sourceCoverageHint
      ? `Step 2 of 3. If nothing fits, you can still use OCR fallback. ${sourceCoverageHint}`
      : "Step 2 of 3. If nothing fits, you can still use OCR fallback.";
  } else {
    dom.resultsViewTitle.textContent = selectedMatch?.displayLabel || "Choose target subtitle";
    dom.resultsViewCopy.textContent = "Choose a target subtitle or confirm local translation.";
    dom.resultsProviderPill.textContent = `${Math.max(targetResults.length, 1)} target choices`;
    dom.searchResultSummary.textContent = "Step 3 of 3. You can still go back and change the source side.";
  }
  if (dom.resultsStepPill) {
    dom.resultsStepPill.textContent =
      resultsStep === "title" ? "Step 1 · Match title" : resultsStep === "source" ? "Step 2 · Choose source" : "Step 3 · Choose target";
  }
  if (dom.resultsBackButton) {
    dom.resultsBackButton.classList.toggle("hidden", resultsStep === "title");
    dom.resultsBackButton.textContent = resultsStep === "target" ? "Back to source" : "Back to titles";
  }
  if (dom.resultsPrepareButton) {
    dom.resultsPrepareButton.classList.toggle("hidden", resultsStep !== "target");
  }
  renderResultsSelectionSummary({
    snapshot,
    resultsStep,
    selectedMatch,
    selectedSourceResult,
    selectedTargetResult,
    searchMatches,
    filteredResults,
    sourceResults,
    targetResults,
    sourceSelectionMode,
    targetSelectionMode,
    sourceLanguage,
    targetLanguage,
  });
  dom.sourceResultCount.textContent = `${sourceResults.length} results`;
  dom.targetResultCount.textContent = `${targetResults.length} results`;
  renderSourceResults(dom.sourceResults, sourceResults, selectedSource, sourceLanguage, {
    selectedMatch,
    sourceSelectionMode,
  });
  renderTargetResults(dom.targetResults, targetResults, selectedTarget, sourceSelectionMode, targetSelectionMode);
  renderSessionSummary(snapshot.prepared_session);
  dom.currentSubtitle.textContent = snapshot.last_subtitle || "No subtitle broadcast yet.";
  dom.prepareButton.disabled = !state.bootstrap.ready || !canPrepare;
  dom.startButton.disabled = !state.bootstrap.ready || !captureRegionReady || !(snapshot.prepared_session && snapshot.status !== "running");
  dom.stopButton.disabled = !state.bootstrap.ready || (snapshot.status !== "running" && snapshot.status !== "stopping");
  dom.prepareButton.textContent = snapshot.prepared_session ? "Prepare Again" : fallbackSelected ? "Prepare OCR Fallback" : "Prepare Session";
  if (dom.resultsPrepareButton) {
    dom.resultsPrepareButton.disabled = dom.prepareButton.disabled;
    dom.resultsPrepareButton.textContent = dom.prepareButton.textContent;
  }
  if (dom.sessionSelectRegionButton) {
    dom.sessionSelectRegionButton.classList.toggle("hidden", !TAURI && captureRegionReady);
    dom.sessionSelectRegionButton.textContent = captureRegionReady ? "Update Capture Area" : "Select Capture Area";
  }
  dom.overlayLink.href = snapshot.overlay_url || apiUrl("/overlay");
}

function bindResultSelection() {
  dom.titleMatchResults.addEventListener("click", (event) => {
    const card = event.target.closest("[data-match-id], [data-feature-id]");
    if (!card) {
      return;
    }
    state.ui.resultsStepOverride = null;
    state.selectedFeatureId = selectionValue(card.dataset.matchId || card.dataset.featureId);
    if (state.snapshot) {
      state.snapshot.selected_match_id = state.selectedFeatureId;
      state.snapshot.selected_feature_id = numericSelectionValue(state.selectedFeatureId);
    }
    state.selectedSourceFileId = null;
    state.selectedTargetFileId = null;
    state.sourceSelectionMode = null;
    state.targetSelectionMode = null;
    scheduleRender();
  });

  dom.sourceResults.addEventListener("click", (event) => {
    const card = event.target.closest("[data-kind], [data-result-id], [data-file-id]");
    if (!card) {
      return;
    }
    state.ui.resultsStepOverride = null;
    if (card.dataset.kind === "ocr-fallback") {
      state.selectedSourceFileId = null;
      state.sourceSelectionMode = "ocr_fallback";
      state.selectedTargetFileId = null;
      state.targetSelectionMode = null;
      scheduleRender();
      return;
    }
    state.selectedSourceFileId = selectionValue(card.dataset.resultId || card.dataset.fileId);
    state.sourceSelectionMode = "subtitle";
    state.selectedTargetFileId = null;
    state.targetSelectionMode = null;
    scheduleRender();
  });

  dom.targetResults.addEventListener("click", (event) => {
    const card = event.target.closest("[data-kind], [data-result-id], [data-file-id]");
    if (!card) {
      return;
    }
    state.ui.resultsStepOverride = null;
    if (card.dataset.kind === "local") {
      state.selectedTargetFileId = null;
      state.targetSelectionMode = "local";
      scheduleRender();
      return;
    }
    state.selectedTargetFileId = selectionValue(card.dataset.resultId || card.dataset.fileId);
    state.targetSelectionMode = "file";
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
        state.selectedFeatureId = currentFeatureId(message.state);
        state.selectedSourceFileId = null;
        state.selectedTargetFileId = null;
        state.sourceSelectionMode = null;
        state.targetSelectionMode = null;
        state.ui.resultsStepOverride = null;
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
    if (message.type === "debug") {
      appendDebugEntry(message.data);
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
  state.languagePersistence.lastSavedKey = languagePreferenceKey(config.languages);
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

dom.resultsPrepareButton?.addEventListener("click", () => {
  dom.prepareButton.click();
});

dom.resultsBackButton?.addEventListener("click", () => {
  if (!state.bootstrap.ready) {
    return;
  }
  const step = currentVisibleResultsStep(state.snapshot || {});
  if (step === "target") {
    state.selectedTargetFileId = null;
    state.targetSelectionMode = null;
    state.ui.resultsStepOverride = "source";
    if (state.snapshot) {
      state.snapshot.selected_target_result_id = null;
      state.snapshot.selected_target_file_id = null;
    }
  } else {
    state.selectedFeatureId = null;
    state.ui.resultsStepOverride = null;
    if (state.snapshot) {
      state.snapshot.selected_match_id = null;
      state.snapshot.selected_feature_id = null;
    }
    state.selectedSourceFileId = null;
    state.selectedTargetFileId = null;
    state.sourceSelectionMode = null;
    state.targetSelectionMode = null;
  }
  scheduleRender();
});

dom.sessionSelectRegionButton?.addEventListener("click", async () => {
  if (!state.bootstrap.ready) {
    return;
  }
  try {
    setSaveState("Open the selector and drag around the subtitle band.", "busy");
    await openCaptureRegionSelector();
  } catch (error) {
    setSaveState(String(error), "error");
  }
});

for (const button of navButtons()) {
  button.addEventListener("click", () => {
    const target = button.dataset.viewTarget;
    if (!target) {
      return;
    }
    if (target === "settings") {
      openSettingsDrawer();
      return;
    }
    state.ui.manualView = target;
    scheduleRender();
  });
}

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
      state.snapshot.status = "idle";
      state.snapshot.progress = { stage: "", message: "", current: 0, total: 0 };
      state.snapshot.search_results = payload.results;
      state.snapshot.search_matches = payload.matches;
      state.snapshot.title = dom.titleInput.value.trim();
      state.snapshot.source_language = sourceLanguage;
      state.snapshot.target_language = targetLanguage;
      state.snapshot.selected_match_id = null;
      state.snapshot.selected_feature_id = null;
      state.snapshot.prepared_session = null;
    }
    state.selectedFeatureId = null;
    state.selectedSourceFileId = null;
    state.selectedTargetFileId = null;
    state.sourceSelectionMode = null;
    state.targetSelectionMode = null;
    state.ui.resultsStepOverride = null;
    state.ui.manualView = "results";
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
  const sourceSelectionMode = currentSourceSelectionMode(state.snapshot, sourceResults, featureId);
  const sourceFileId = selectedSourceResultId(state.snapshot);
  const mode = sourceFileId ? "subtitle_pair" : sourceSelectionMode === "ocr_fallback" ? "ocr_fallback" : "";
  if (!featureId) {
    setSaveState("Select a matched title first", "error");
    return;
  }
  if (!currentTargetSelectionMode(state.snapshot)) {
    setSaveState("Choose a target subtitle or confirm local translation first", "error");
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
      state.snapshot.status = "idle";
      state.snapshot.progress = { stage: "", message: "", current: 0, total: 0 };
      state.snapshot.prepared_session = payload.session;
      state.snapshot.selected_match_id = featureId;
      state.snapshot.selected_feature_id = numericSelectionValue(featureId);
      state.snapshot.selected_source_result_id = sourceFileId;
      state.snapshot.selected_source_file_id = numericSelectionValue(sourceFileId);
      state.snapshot.selected_target_result_id = selectedTargetResultId(state.snapshot);
      state.snapshot.selected_target_file_id = numericSelectionValue(selectedTargetResultId(state.snapshot));
    }
    state.ui.manualView = "session";
    if (!hasCaptureRegion()) {
      setSaveState("Session prepared. Select the capture area next.", "busy");
      try {
        await openCaptureRegionSelector();
      } catch (selectorError) {
        setSaveState(`Session prepared. ${String(selectorError)}`, "error");
      }
    } else {
      setSaveState("Session prepared", "success");
    }
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
  if (!hasCaptureRegion()) {
    setSaveState("Select the capture area before starting sync", "error");
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
    state.ui.manualView = "session";
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
    state.ui.manualView = "session";
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
    persistLanguagePreferences();
    scheduleRender();
  });
  customInput.addEventListener("input", () => {
    if (!state.bootstrap.ready) {
      return;
    }
    updateLanguageTrigger(selectEl);
    updateDerivedOcrDisplay(deriveOcrLanguage(currentLanguageValue(dom.sourceLanguageInput, dom.sourceLanguageCustomInput)));
    scheduleRender();
  });
  customInput.addEventListener("change", () => {
    if (!state.bootstrap.ready) {
      return;
    }
    updateLanguageTrigger(selectEl);
    updateDerivedOcrDisplay(deriveOcrLanguage(currentLanguageValue(dom.sourceLanguageInput, dom.sourceLanguageCustomInput)));
    persistLanguagePreferences();
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
    state.languagePersistence.lastSavedKey = languagePreferenceKey(config.languages);
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

// ---- Debug Panel ----

const debugLog = [];
const DEBUG_MAX = 20;

function escapeHtml(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function appendDebugEntry(data) {
  debugLog.unshift(data);
  if (debugLog.length > DEBUG_MAX) debugLog.length = DEBUG_MAX;
  renderDebugPanel();
}

function renderDebugPanel() {
  let panel = document.getElementById("debug-panel");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "debug-panel";
    panel.style.cssText = [
      "position:fixed", "bottom:8px", "right:8px", "width:500px",
      "max-height:440px", "overflow-y:auto",
      "background:rgba(15,23,42,0.93)", "color:#e2e8f0",
      "font-family:ui-monospace,monospace", "font-size:11px",
      "border-radius:10px", "padding:10px",
      "box-shadow:0 4px 24px rgba(0,0,0,.5)",
      "z-index:99999", "pointer-events:auto",
    ].join(";");
    const hdr = document.createElement("div");
    hdr.style.cssText = "display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;color:#64748b;font-size:10px;text-transform:uppercase;letter-spacing:.06em";
    hdr.innerHTML = '<span>OCR Debug</span><button id="debug-panel-close" style="background:none;border:none;color:#64748b;cursor:pointer;font-size:16px;line-height:1;padding:0">&times;</button>';
    panel.appendChild(hdr);
    const summary = document.createElement("div");
    summary.id = "debug-panel-summary";
    panel.appendChild(summary);
    const body = document.createElement("div");
    body.id = "debug-panel-body";
    panel.appendChild(body);
    document.body.appendChild(panel);
    document.getElementById("debug-panel-close").addEventListener("click", () => panel.remove());
  }

  const summary = document.getElementById("debug-panel-summary");
  const body = document.getElementById("debug-panel-body");
  if (!summary || !body) return;

  const misses = debugLog.filter((e) => e.matchIdx === null).length;
  const avgMs = debugLog.length ? Math.round(debugLog.reduce((s, e) => s + (e.elapsedMs || 0), 0) / debugLog.length) : 0;
  summary.style.cssText = "margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid #1e293b;color:#94a3b8;font-size:10px";
  summary.textContent = `Last ${debugLog.length} — Misses: ${misses}/${debugLog.length} — Avg: ${avgMs}ms`;

  body.innerHTML = "";
  for (const entry of debugLog) {
    const hit = entry.matchIdx !== null;
    const row = document.createElement("div");
    row.style.cssText = `margin-bottom:3px;padding:3px 5px;border-radius:4px;background:${hit ? "rgba(34,197,94,.07)" : "rgba(239,68,68,.07)"}`;
    row.innerHTML = [
      `<span style="color:${hit ? "#4ade80" : "#f87171"};font-weight:bold">${hit ? "HIT" : "MISS"}</span>`,
      hit ? ` <span style="color:#94a3b8">idx=</span><b>${entry.matchIdx}</b> <span style="color:#94a3b8">score=</span><b>${entry.matchScore}</b>` : "",
      ` <span style="color:#475569">(${entry.elapsedMs}ms)</span>`,
      `<br><span style="color:#64748b">${escapeHtml(entry.ocrText || "(empty)")}</span>`,
      hit && entry.matchSrc ? `<br><span style="color:#475569">→ ${escapeHtml(entry.matchSrc)}</span>` : "",
    ].join("");
    body.appendChild(row);
  }
}

bootstrapApp();
