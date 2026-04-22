import { dom } from "./app-dom.js";
import { state } from "./app-state.js";
import { TAURI } from "./app-api.js";

let renderScheduled = false;
let renderCallback = () => {};
let closeLanguagePickerCallback = () => {};

export function configureShell({ render, closeLanguagePicker }) {
  if (typeof render === "function") {
    renderCallback = render;
  }
  if (typeof closeLanguagePicker === "function") {
    closeLanguagePickerCallback = closeLanguagePicker;
  }
}

export function scheduleRender() {
  if (renderScheduled) {
    return;
  }

  renderScheduled = true;
  requestAnimationFrame(() => {
    renderScheduled = false;
    renderCallback();
  });
}

export function setSaveState(label, kind = "neutral") {
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

export function setControlsDisabled(disabled) {
  if (disabled && state.activeLanguagePicker) {
    closeLanguagePickerCallback({ restoreFocus: false });
  }
  if (disabled && state.ui.settingsOpen) {
    setSettingsDrawerOpen(false);
  }
  for (const control of interactiveControls()) {
    control.disabled = disabled;
  }
  setOverlayLinkDisabled(disabled);
}

export function setBootstrapLoading(title, message) {
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

export function setBootstrapError(message) {
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

export function waitForNextPaint() {
  return new Promise((resolve) => {
    requestAnimationFrame(() => {
      requestAnimationFrame(resolve);
    });
  });
}

export function setSettingsDrawerOpen(open) {
  state.ui.settingsOpen = open;
  dom.settingsDrawer?.classList.toggle("is-open", open);
  dom.settingsDrawer?.setAttribute("aria-hidden", String(!open));
  dom.settingsBackdrop?.classList.toggle("hidden", !open);
  document.body.classList.toggle("drawer-open", open);
  scheduleRender();
}

export function openSettingsDrawer() {
  if (!state.bootstrap.ready) {
    return;
  }
  setSettingsDrawerOpen(true);
}

export function closeSettingsDrawer() {
  setSettingsDrawerOpen(false);
}

export async function openCaptureRegionSelector() {
  if (!TAURI) {
    openSettingsDrawer();
    document.getElementById("capture-region-input")?.focus();
    return;
  }
  await TAURI.core.invoke("open_area_selector");
}

// Keep all Tauri shell hooks together so browser-only smoke checks can ignore them.
export function setupTauriBridge() {
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

export function dismissLoadingOverlay() {
  if (!dom.loadingOverlay) {
    return;
  }
  dom.loadingSpinner?.classList.add("hidden");
  dom.loadingOverlay.remove();
  dom.loadingOverlay = null;
}
