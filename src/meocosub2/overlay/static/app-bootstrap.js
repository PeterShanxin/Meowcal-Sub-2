import { dom } from "./app-dom.js";
import { state } from "./app-state.js";
import { fetchJson, wsUrl } from "./app-api.js";
import { appendDebugEntry } from "./app-debug.js";
import {
  configureShell,
  dismissLoadingOverlay,
  scheduleRender,
  setBootstrapError,
  setBootstrapLoading,
  setControlsDisabled,
  setSaveState,
  setupTauriBridge,
  waitForNextPaint,
} from "./app-shell.js";
import {
  closeLanguagePicker,
  languagePreferenceKey,
  populateLanguageSelect,
  renderFoundryStatus,
  setupLanguagePicker,
  updateDerivedOcrDisplay,
} from "./app-language.js";
import {
  applyStylePreview,
  currentFeatureId,
  fillConfigForm,
  matchSelectionId,
  render,
  sameSelectionValue,
} from "./app-render.js";
import { bindResultSelection, bindSessionActions } from "./app-session.js";

let socket;
let bootstrapPromise = null;

configureShell({ render, closeLanguagePicker });

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

bindResultSelection();
setupLanguagePicker();
setupTauriBridge();
bindSessionActions();
setControlsDisabled(true);

dom.loadingRetry.addEventListener("click", () => {
  bootstrapApp();
});

bootstrapApp();
