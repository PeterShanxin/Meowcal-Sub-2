const dom = {
  titleInput: document.getElementById("title-input"),
  sourceLanguageInput: document.getElementById("source-language-input"),
  targetLanguageInput: document.getElementById("target-language-input"),
  statusChip: document.getElementById("status-chip"),
  statusMessage: document.getElementById("status-message"),
  progressStage: document.getElementById("progress-stage"),
  progressMeta: document.getElementById("progress-meta"),
  progressFill: document.getElementById("progress-fill"),
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
  configForm: document.getElementById("config-form"),
};

const state = {
  snapshot: null,
  config: null,
  selectedSourceFileId: null,
  selectedTargetFileId: null,
  overlayWindow: null,
};

let socket;
let renderScheduled = false;

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
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail || response.statusText);
  }

  return response.json();
}

function setSaveState(label) {
  dom.saveState.textContent = label;
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
  const { opensubtitles, capture, translation, overlay } = config;
  document.getElementById("api-key-input").value = opensubtitles.apiKey || "";
  document.getElementById("translation-endpoint-input").value = translation.endpoint || "";
  document.getElementById("translation-model-input").value = translation.model || "";
  document.getElementById("ocr-language-input").value = capture.ocrLanguage || "";
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
  return {
    opensubtitles: {
      apiKey: document.getElementById("api-key-input").value,
    },
    languages: {
      source: dom.sourceLanguageInput.value.trim() || "en",
      target: dom.targetLanguageInput.value.trim() || "zh",
    },
    capture: {
      ocrLanguage: document.getElementById("ocr-language-input").value.trim() || "en",
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

function renderResults(container, results, selectedId) {
  if (!results.length) {
    container.className = "result-list empty-state";
    container.textContent = "No results available for this language.";
    return;
  }

  container.className = "result-list";
  container.innerHTML = results
    .map((result) => {
      const selected = result.fileId === selectedId ? "selected" : "";
      return `
        <button type="button" class="result-card ${selected}" data-file-id="${result.fileId}">
          <h4>${result.displayLabel}</h4>
          <p>${result.fileName}</p>
          <p>${result.downloadCount.toLocaleString()} downloads</p>
        </button>
      `;
    })
    .join("");
}

function renderTargetResults(container, results, selectedId) {
  const noneSelected = selectedId == null ? "selected" : "";
  const items = [
    `
      <button type="button" class="result-card ${noneSelected}" data-file-id="">
        <h4>Use local translation</h4>
        <p>No target subtitle file. Prepare by translating the source lines locally.</p>
      </button>
    `,
  ];

  items.push(
    ...results.map((result) => {
      const selected = result.fileId === selectedId ? "selected" : "";
      return `
        <button type="button" class="result-card ${selected}" data-file-id="${result.fileId}">
          <h4>${result.displayLabel}</h4>
          <p>${result.fileName}</p>
          <p>${result.downloadCount.toLocaleString()} downloads</p>
        </button>
      `;
    }),
  );

  container.className = "result-list";
  container.innerHTML = items.join("");
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
  dom.preparedSession.innerHTML = `
    <dl>
      <dt>Title</dt><dd>${preparedSession.title}</dd>
      <dt>Source File</dt><dd>${preparedSession.source_file_name}</dd>
      <dt>Target File</dt><dd>${preparedSession.target_file_name || "Generated via translation"}</dd>
      <dt>Source Lines</dt><dd>${preparedSession.source_line_count}</dd>
      <dt>Translated Lines</dt><dd>${preparedSession.translated_line_count}</dd>
      <dt>Mode</dt><dd>${preparedSession.used_translation ? "Local translation" : "Matched target subtitle"}</dd>
    </dl>
  `;
}

function render() {
  if (!state.snapshot || !state.config) {
    return;
  }

  const snapshot = state.snapshot;
  const sourceLanguage = snapshot.source_language || dom.sourceLanguageInput.value.trim();
  const targetLanguage = snapshot.target_language || dom.targetLanguageInput.value.trim();
  const searchResults = snapshot.search_results || [];
  const sourceResults = searchResults.filter((result) => result.language === sourceLanguage);
  const targetResults = searchResults.filter((result) => result.language === targetLanguage);
  const progress = snapshot.progress || {};
  const progressRatio = progress.total ? Math.min(progress.current / progress.total, 1) : 0;
  const selectedSource = state.selectedSourceFileId ?? snapshot.selected_source_file_id;
  const selectedTarget = state.selectedTargetFileId ?? snapshot.selected_target_file_id;

  dom.statusChip.textContent = snapshot.status || "idle";
  dom.statusChip.className = `status-chip ${snapshot.status || "idle"}`;
  dom.statusMessage.textContent =
    snapshot.error_message ||
    progress.message ||
    (snapshot.prepared_session ? "Session prepared. Start sync when the overlay is open." : "Ready for the next action.");
  dom.progressStage.textContent = progress.stage ? progress.stage.toUpperCase() : "No background work running";
  dom.progressMeta.textContent = progress.message || "Search and choose subtitle files to begin.";
  dom.progressFill.style.width = `${progressRatio * 100}%`;
  dom.sourceResultCount.textContent = `${sourceResults.length} results`;
  dom.targetResultCount.textContent = `${targetResults.length} results`;
  renderResults(dom.sourceResults, sourceResults, selectedSource);
  renderTargetResults(dom.targetResults, targetResults, selectedTarget);
  renderSessionSummary(snapshot.prepared_session);
  dom.currentSubtitle.textContent = snapshot.last_subtitle || "No subtitle broadcast yet.";
  dom.prepareButton.disabled = !selectedSource;
  dom.startButton.disabled = !(snapshot.prepared_session && snapshot.status !== "running");
  dom.stopButton.disabled = snapshot.status !== "running" && snapshot.status !== "stopping";
  dom.overlayLink.href = snapshot.overlay_url || "/overlay";
}

function bindResultSelection() {
  dom.sourceResults.addEventListener("click", (event) => {
    const card = event.target.closest("[data-file-id]");
    if (!card) {
      return;
    }
    state.selectedSourceFileId = Number(card.dataset.fileId);
    scheduleRender();
  });

  dom.targetResults.addEventListener("click", (event) => {
    const card = event.target.closest("[data-file-id]");
    if (!card) {
      return;
    }
    state.selectedTargetFileId = card.dataset.fileId ? Number(card.dataset.fileId) : null;
    scheduleRender();
  });
}

function connectSocket() {
  socket = new WebSocket(`ws://${location.host}/ws/app`);
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "state") {
      state.snapshot = message.state;
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

async function loadInitialState() {
  const [config, snapshot] = await Promise.all([
    fetchJson("/api/config"),
    fetchJson("/api/state"),
  ]);
  state.config = config;
  state.snapshot = snapshot;
  fillConfigForm(config);
  dom.sourceLanguageInput.value = config.languages.source;
  dom.targetLanguageInput.value = config.languages.target;
  scheduleRender();
}

dom.searchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setSaveState("Searching...");
  try {
    const payload = await fetchJson("/api/search", {
      method: "POST",
      body: JSON.stringify({
        title: dom.titleInput.value.trim(),
        sourceLanguage: dom.sourceLanguageInput.value.trim(),
        targetLanguage: dom.targetLanguageInput.value.trim(),
      }),
    });
    if (state.snapshot) {
      state.snapshot.search_results = payload.results;
      state.snapshot.title = dom.titleInput.value.trim();
      state.snapshot.source_language = dom.sourceLanguageInput.value.trim();
      state.snapshot.target_language = dom.targetLanguageInput.value.trim();
      state.snapshot.prepared_session = null;
    }
    state.selectedSourceFileId = null;
    state.selectedTargetFileId = null;
    setSaveState("Results ready");
    scheduleRender();
  } catch (error) {
    setSaveState(error.message);
  }
});

dom.prepareButton.addEventListener("click", async () => {
  const sourceFileId = state.selectedSourceFileId ?? state.snapshot?.selected_source_file_id;
  if (!sourceFileId) {
    setSaveState("Select a source subtitle first");
    return;
  }

  try {
    setSaveState("Preparing session...");
    const payload = await fetchJson("/api/session/prepare", {
      method: "POST",
      body: JSON.stringify({
        sourceFileId,
        targetFileId: state.selectedTargetFileId,
      }),
    });
    if (state.snapshot) {
      state.snapshot.prepared_session = payload.session;
      state.snapshot.selected_source_file_id = sourceFileId;
      state.snapshot.selected_target_file_id = state.selectedTargetFileId;
    }
    setSaveState("Session prepared");
    scheduleRender();
  } catch (error) {
    setSaveState(error.message);
  }
});

dom.startButton.addEventListener("click", async () => {
  const sessionId = state.snapshot?.prepared_session?.session_id;
  if (!sessionId) {
    setSaveState("Prepare a session before starting");
    return;
  }

  try {
    if (!state.overlayWindow || state.overlayWindow.closed) {
      state.overlayWindow = window.open("/overlay", "meowcal-overlay", "width=1280,height=320");
    }
    setSaveState("Starting sync...");
    await fetchJson("/api/session/start", {
      method: "POST",
      body: JSON.stringify({ sessionId }),
    });
    setSaveState("Sync running");
  } catch (error) {
    setSaveState(error.message);
  }
});

dom.stopButton.addEventListener("click", async () => {
  try {
    setSaveState("Stopping session...");
    await fetchJson("/api/session/stop", { method: "POST" });
    setSaveState("Session stopped");
  } catch (error) {
    setSaveState(error.message);
  }
});

dom.configForm.addEventListener("input", () => {
  setSaveState("Unsaved changes");
  applyStylePreview(currentOverlayConfigFromForm());
});

dom.configForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    setSaveState("Saving config...");
    const config = await fetchJson("/api/config", {
      method: "PUT",
      body: JSON.stringify(buildConfigPayload()),
    });
    state.config = config;
    fillConfigForm(config);
    setSaveState("Config saved");
    scheduleRender();
  } catch (error) {
    setSaveState(error.message);
  }
});

bindResultSelection();
loadInitialState().then(connectSocket).catch((error) => {
  setSaveState(error.message);
});
