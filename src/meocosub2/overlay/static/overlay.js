(() => {
  const plate = document.getElementById("plate");
  const line = document.getElementById("line");
  const mark = document.getElementById("mark");
  const markLabel = document.getElementById("mark-label");
  const token = (window.__MEOWCAL__ || {}).token || "";

  function withToken(path) {
    return token ? `${path}?token=${encodeURIComponent(token)}` : path;
  }

  function applyStyle(style) {
    if (!style) return;
    const root = document.documentElement.style;
    if (style.fontSize) root.setProperty("--plate-font-size", `${style.fontSize}px`);
    if (style.fontFamily) root.setProperty("--plate-font", `"${style.fontFamily}"`);
    if (style.textColor) root.setProperty("--plate-color", style.textColor);
    if (style.bgColor) root.setProperty("--plate-bg", style.bgColor);
    if (style.radiusPx != null) root.setProperty("--plate-radius", `${style.radiusPx}px`);
    if (style.paddingPx != null) root.setProperty("--plate-padding", `${style.paddingPx}px`);
    if (style.animationMs != null) root.setProperty("--plate-fade", `${style.animationMs}ms`);
  }

  // The shell sizes the window for two lines at the default font. Only the page
  // knows what this line, at this font size, actually came to.
  let reportedHeight = 0;
  function reportHeight() {
    const needed = Math.ceil(plate.getBoundingClientRect().height);
    if (!needed || Math.abs(needed - reportedHeight) < 3) return;
    reportedHeight = needed;
    const invoke = window.__TAURI__?.core?.invoke ?? window.__TAURI__?.invoke;
    if (invoke) void invoke("set_overlay_height", { heightCss: needed });
  }

  function show(text, source) {
    const provisional = source === "translated";
    line.textContent = text;
    line.classList.toggle("is-provisional", provisional);
    mark.classList.toggle("is-provisional", provisional);
    markLabel.textContent = provisional ? "AI" : "SUB";
    plate.classList.toggle("is-empty", !text);
    if (text) requestAnimationFrame(reportHeight);
  }

  function connect() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${proto}//${window.location.host}${withToken("/ws/app")}`);
    socket.onmessage = (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (message.type === "subtitle") show(message.text || "", message.source);
      else if (message.type === "style") applyStyle(message.style);
      else if (message.type === "state" && message.state?.status !== "running") show("", null);
    };
    // The overlay outlives a backend restart, so a dropped socket reconnects
    // rather than leaving a stale line frozen on the video.
    socket.onclose = () => window.setTimeout(connect, 1000);
  }

  connect();
})();
