const TAURI = window.__TAURI__;
const API_BASE = "http://127.0.0.1:8765";

const frame = document.getElementById("capture-frame");
const statusChip = document.getElementById("hud-status-chip");
const statusNote = document.getElementById("hud-status-note");
const controls = document.getElementById("hud-controls");
const stopButton = document.getElementById("hud-stop-button");
const settingsButton = document.getElementById("hud-settings-button");
const subtitleShell = document.getElementById("subtitle-shell");
const subtitleText = document.getElementById("subtitle-text");

const state = {
  topMargin: 120,
  frameWidth: 0,
  frameHeight: 0,
  subtitlePosition: "above",
  fadeTimer: null,
};

function wsUrl(path) {
  const url = new URL(API_BASE);
  return `ws://${url.host}${path}`;
}

function setStatus(snapshot, progress = null) {
  const status = snapshot?.status || "idle";
  const note =
    snapshot?.error_message ||
    snapshot?.warning_message ||
    progress?.message ||
    snapshot?.last_subtitle ||
    "Waiting to start.";

  statusChip.textContent = status.replace(/^\w/, (ch) => ch.toUpperCase());
  statusChip.className = `status-chip ${status}`;
  statusNote.textContent = note;
}

function applyStyle(style) {
  const root = document.documentElement;
  if (style.fontSize) root.style.setProperty("--overlay-font-size", `${style.fontSize}px`);
  if (style.fontFamily) root.style.setProperty("--overlay-font-family", style.fontFamily);
  if (style.textColor) root.style.setProperty("--overlay-text-color", style.textColor);
}

function renderRegion(payload) {
  if (!payload) return;
  state.topMargin = payload.topMargin;
  state.frameWidth = payload.width;
  state.frameHeight = payload.height;
  state.subtitlePosition = payload.subtitlePosition;

  frame.style.left = `${payload.frameLeft}px`;
  frame.style.top = `${payload.frameTop}px`;
  frame.style.width = `${payload.width}px`;
  frame.style.height = `${payload.height}px`;

  subtitleShell.classList.remove("above", "below");
  subtitleShell.classList.add(payload.subtitlePosition === "below" ? "below" : "above");
}

function clearFadeTimer() {
  if (state.fadeTimer) {
    clearTimeout(state.fadeTimer);
    state.fadeTimer = null;
  }
}

function enterShowcase(durationMs = 4000) {
  clearFadeTimer();
  frame.classList.remove("dormant");
  frame.classList.add("showcase");
  state.fadeTimer = setTimeout(() => {
    frame.classList.remove("showcase");
    frame.classList.add("dormant");
  }, durationMs);
}

function renderSubtitle(text) {
  if (!text) {
    subtitleShell.classList.add("hidden");
    subtitleText.textContent = "";
    return;
  }
  subtitleText.textContent = text;
  subtitleShell.classList.remove("hidden");
}

async function connect() {
  const socket = new WebSocket(wsUrl("/ws/app"));
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "state") setStatus(message.state);
    if (message.type === "progress") setStatus(null, message.progress);
    if (message.type === "subtitle") renderSubtitle(message.text || "");
    if (message.type === "style") applyStyle(message.style || {});
    if (message.type === "error") {
      statusChip.textContent = "Error";
      statusChip.className = "status-chip error";
      statusNote.textContent = message.message || "Unknown error";
    }
  };
  socket.onclose = () => setTimeout(connect, 1200);
}

TAURI.event.listen("capture-hud-region", (event) => renderRegion(event.payload));
TAURI.event.listen("capture-hud-hover", (event) => {
  const hovering = Boolean(event.payload?.hovering);
  frame.classList.toggle("hovering", hovering);
  controls.classList.toggle("hidden", !hovering);
  if (hovering) {
    clearFadeTimer();
    frame.classList.remove("dormant");
    frame.classList.add("showcase");
  } else {
    enterShowcase(1800);
  }
});
TAURI.event.listen("capture-hud-pulse", () => {
  frame.classList.remove("pulse");
  void frame.offsetWidth;
  frame.classList.add("pulse");
  enterShowcase(4000);
});

stopButton.addEventListener("click", async () => {
  await TAURI.core.invoke("stop_translation");
});

settingsButton.addEventListener("click", async () => {
  await TAURI.core.invoke("show_main_window");
});

connect();
