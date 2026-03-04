const subtitleEl = document.getElementById("subtitle-text");
const containerEl = document.getElementById("subtitle-container");
let socket;
let fadeTimer;

async function loadConfig() {
  try {
    const response = await fetch("/config");
    const config = await response.json();
    document.documentElement.style.setProperty("--font-size", `${config.fontSize}px`);
    document.documentElement.style.setProperty("--font-family", config.fontFamily);
    document.documentElement.style.setProperty("--text-color", config.textColor);
    document.documentElement.style.setProperty("--bg-color", config.bgColor);
    if (config.position === "top") {
      containerEl.style.bottom = "auto";
      containerEl.style.top = "5%";
    }
  } catch (error) {
    console.warn("Could not load overlay config", error);
  }
}

function showSubtitle(text) {
  clearTimeout(fadeTimer);
  if (!text || !text.trim()) {
    subtitleEl.style.opacity = "0";
    return;
  }
  subtitleEl.textContent = text;
  subtitleEl.style.opacity = "1";
  fadeTimer = setTimeout(() => {
    subtitleEl.style.opacity = "0";
  }, 8000);
}

function connect() {
  socket = new WebSocket(`ws://${location.host}/ws`);
  socket.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === "subtitle") {
        showSubtitle(payload.text);
      }
    } catch (error) {
      console.warn("Bad overlay message", error);
    }
  };
  socket.onclose = () => {
    setTimeout(connect, 2000);
  };
}

loadConfig();
connect();
