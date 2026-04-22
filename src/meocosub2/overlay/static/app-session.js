import { dom } from "./app-dom.js";
import { state } from "./app-state.js";
import { TAURI, fetchJson } from "./app-api.js";
import {
  closeSettingsDrawer,
  scheduleRender,
  setSaveState,
  openCaptureRegionSelector,
  openSettingsDrawer,
} from "./app-shell.js";
import {
  currentLanguageValue,
  deriveOcrLanguage,
  isChineseFamily,
  languagePreferenceKey,
  normalizeLanguageCode,
  persistLanguagePreferences,
  renderFoundryStatus,
  syncCustomLanguageInput,
  updateDerivedOcrDisplay,
  updateLanguageTrigger,
} from "./app-language.js";
import {
  applyStylePreview,
  buildConfigPayload,
  currentFeatureId,
  currentOverlayConfigFromForm,
  currentSourceSelectionMode,
  currentTargetSelectionMode,
  currentVisibleResultsStep,
  fillConfigForm,
  hasCaptureRegion,
  numericSelectionValue,
  resultMatchesSelectedMatch,
  selectedSourceResultId,
  selectedTargetResultId,
  selectionValue,
} from "./app-render.js";

// Session actions own optimistic local state because the websocket echo arrives later.
export function bindResultSelection() {
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

export function bindSessionActions() {
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

  for (const button of document.querySelectorAll("[data-view-target]")) {
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
    const sourceSelectionMode = currentSourceSelectionMode(state.snapshot);
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
}
