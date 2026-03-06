const subtitleEl = document.getElementById("subtitle-text");
const shellEl = document.getElementById("subtitle-shell");

let socket;
let fadeTimer;
let pendingSubtitle = "";
let renderRequested = false;

function applyStyle(style) {
  if (!style) {
    return;
  }

  const root = document.documentElement;
  root.style.setProperty("--overlay-font-size", `${style.fontSize}px`);
  root.style.setProperty("--overlay-font-family", style.fontFamily);
  root.style.setProperty("--overlay-text-color", style.textColor);
  root.style.setProperty("--overlay-bg-color", style.bgColor);
  root.style.setProperty("--overlay-radius", `${style.radiusPx}px`);
  root.style.setProperty("--overlay-padding", `${style.paddingPx}px`);
  root.style.setProperty("--overlay-max-width", `${style.maxWidthVw}vw`);
  root.style.setProperty("--overlay-blur", `${style.blurPx}px`);
  root.style.setProperty("--overlay-shadow-strength", style.shadowStrength);
  root.style.setProperty("--overlay-offset", `${style.offsetPct}%`);
  root.style.setProperty("--overlay-animation-ms", `${style.animationMs}ms`);
  shellEl.classList.toggle("top", style.position === "top");
}

async function loadStyle() {
  try {
    const response = await fetch("/config");
    applyStyle(await response.json());
  } catch (error) {
    console.warn("Could not load overlay config", error);
  }
}

function commitSubtitle(text) {
  clearTimeout(fadeTimer);
  if (!text || !text.trim()) {
    subtitleEl.classList.remove("visible");
    return;
  }

  subtitleEl.textContent = text;
  subtitleEl.classList.add("visible");
  fadeTimer = setTimeout(() => {
    subtitleEl.classList.remove("visible");
  }, 8000);
}

function scheduleSubtitle(text) {
  pendingSubtitle = text;
  if (renderRequested) {
    return;
  }

  renderRequested = true;
  requestAnimationFrame(() => {
    renderRequested = false;
    commitSubtitle(pendingSubtitle);
  });
}

function connect() {
  socket = new WebSocket(`ws://${location.host}/ws`);
  socket.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === "subtitle") {
        scheduleSubtitle(payload.text || "");
      }
      if (payload.type === "style") {
        applyStyle(payload.style);
      }
    } catch (error) {
      console.warn("Bad overlay message", error);
    }
  };
  socket.onclose = () => {
    setTimeout(connect, 2000);
  };
}

loadStyle();
connect();
