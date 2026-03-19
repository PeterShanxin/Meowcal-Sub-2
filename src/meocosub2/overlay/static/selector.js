const TAURI = window.__TAURI__;
const root = document.getElementById("overlay-root");
const box = document.getElementById("selection-box");
const toolbar = document.getElementById("selector-toolbar");
const dimensions = document.getElementById("selector-dimensions");
const confirmButton = document.getElementById("selector-confirm");
const cancelButton = document.getElementById("selector-cancel");

const state = {
  dragging: false,
  startX: 0,
  startY: 0,
  currentX: 0,
  currentY: 0,
};

function currentRegion() {
  const left = Math.min(state.startX, state.currentX);
  const top = Math.min(state.startY, state.currentY);
  const width = Math.abs(state.currentX - state.startX);
  const height = Math.abs(state.currentY - state.startY);
  return { left, top, width, height };
}

function renderSelection() {
  const region = currentRegion();
  if (region.width < 4 || region.height < 4) {
    box.classList.add("hidden");
    toolbar.classList.add("hidden");
    return;
  }

  box.classList.remove("hidden");
  box.style.left = `${region.left}px`;
  box.style.top = `${region.top}px`;
  box.style.width = `${region.width}px`;
  box.style.height = `${region.height}px`;

  toolbar.classList.remove("hidden");
  toolbar.style.left = `${region.left}px`;
  toolbar.style.top = `${Math.max(12, region.top - 54)}px`;
  dimensions.textContent = `${region.width} × ${region.height}`;
}

root.addEventListener("mousedown", (event) => {
  state.dragging = true;
  state.startX = event.clientX;
  state.startY = event.clientY;
  state.currentX = event.clientX;
  state.currentY = event.clientY;
  renderSelection();
});

root.addEventListener("mousemove", (event) => {
  if (!state.dragging) {
    return;
  }
  state.currentX = event.clientX;
  state.currentY = event.clientY;
  renderSelection();
});

window.addEventListener("mouseup", (event) => {
  if (!state.dragging) {
    return;
  }
  state.dragging = false;
  state.currentX = event.clientX;
  state.currentY = event.clientY;
  renderSelection();
});

confirmButton.addEventListener("click", async () => {
  const region = currentRegion();
  if (region.width < 4 || region.height < 4) {
    return;
  }
  await TAURI.core.invoke("set_capture_region", {
    x: region.left,
    y: region.top,
    width: region.width,
    height: region.height,
    deviceScaleFactor: window.devicePixelRatio || 1,
  });
});

cancelButton.addEventListener("click", async () => {
  await TAURI.core.invoke("close_area_selector");
});

window.addEventListener("keydown", async (event) => {
  if (event.key === "Escape") {
    await TAURI.core.invoke("close_area_selector");
  }
});
