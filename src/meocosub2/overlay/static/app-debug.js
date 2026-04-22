const debugLog = [];
const DEBUG_MAX = 20;

function escapeHtml(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function appendDebugEntry(data) {
  debugLog.unshift(data);
  if (debugLog.length > DEBUG_MAX) {
    debugLog.length = DEBUG_MAX;
  }
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
    const header = document.createElement("div");
    header.style.cssText = "display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;color:#64748b;font-size:10px;text-transform:uppercase;letter-spacing:.06em";
    header.innerHTML = '<span>OCR Debug</span><button id="debug-panel-close" style="background:none;border:none;color:#64748b;cursor:pointer;font-size:16px;line-height:1;padding:0">&times;</button>';
    panel.appendChild(header);
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
  if (!summary || !body) {
    return;
  }

  const misses = debugLog.filter((entry) => entry.matchIdx === null).length;
  const avgMs = debugLog.length
    ? Math.round(debugLog.reduce((sum, entry) => sum + (entry.elapsedMs || 0), 0) / debugLog.length)
    : 0;
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
