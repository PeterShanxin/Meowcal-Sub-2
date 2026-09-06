const TAURI = window.__TAURI__;
const root = document.getElementById("overlay-root");
const box = document.getElementById("selection-box");
const toolbar = document.getElementById("selector-toolbar");
const dimensions = document.getElementById("selector-dimensions");
const confirmButton = document.getElementById("selector-confirm");
const cancelButton = document.getElementById("selector-cancel");
const instructions = document.getElementById("selector-instructions");
const backdrop = document.getElementById("selector-backdrop");

const MIN_SIDE = 8;

const state = {
  dragging: false,
  startX: 0,
  startY: 0,
  currentX: 0,
  currentY: 0,
  hasSelection: false,
};

// Pointer positions come in fractions of a CSS pixel on a scaled display, and
// a region is whole pixels of screen: rounding the edges rather than the size
// keeps the saved box on the same pixels as the drawn one.
function currentRegion() {
  const left = Math.round(Math.min(state.startX, state.currentX));
  const top = Math.round(Math.min(state.startY, state.currentY));
  const right = Math.round(Math.max(state.startX, state.currentX));
  const bottom = Math.round(Math.max(state.startY, state.currentY));
  return { left, top, width: right - left, height: bottom - top };
}

function renderSelection() {
  const region = currentRegion();
  state.hasSelection = region.width >= MIN_SIDE && region.height >= MIN_SIDE;
  if (!state.hasSelection) {
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
  instructions.textContent = "Drag again to reselect, or confirm this area.";
}

// Pointer events on the root would also fire for the toolbar sitting inside it,
// and starting a fresh drag there cleared the selection before the button's own
// handler could read it - so Confirm could never save a region.
function startsADrag(event) {
  return event.button === 0 && !toolbar.contains(event.target);
}

root.addEventListener("pointerdown", (event) => {
  if (!startsADrag(event)) {
    return;
  }
  state.dragging = true;
  state.startX = event.clientX;
  state.startY = event.clientY;
  state.currentX = event.clientX;
  state.currentY = event.clientY;
  root.setPointerCapture(event.pointerId);
  renderSelection();
});

root.addEventListener("pointermove", (event) => {
  if (!state.dragging) {
    return;
  }
  state.currentX = event.clientX;
  state.currentY = event.clientY;
  renderSelection();
});

root.addEventListener("pointerup", (event) => {
  if (!state.dragging) {
    return;
  }
  state.dragging = false;
  state.currentX = event.clientX;
  state.currentY = event.clientY;
  if (root.hasPointerCapture(event.pointerId)) {
    root.releasePointerCapture(event.pointerId);
  }
  renderSelection();
});

async function confirmSelection() {
  if (!state.hasSelection) {
    return;
  }
  const region = currentRegion();
  try {
    await TAURI.core.invoke("set_capture_region", {
      x: region.left,
      y: region.top,
      width: region.width,
      height: region.height,
      deviceScaleFactor: window.devicePixelRatio || 1,
    });
  } catch (error) {
    // Silence here reads as a dead button: the window stays up, the area is not
    // saved, and nothing on screen says why.
    instructions.textContent = `Could not save this area: ${error}`;
  }
}

async function cancelSelection() {
  await TAURI.core.invoke("cancel_area_selector");
}

confirmButton.addEventListener("click", () => void confirmSelection());
cancelButton.addEventListener("click", () => void cancelSelection());

window.addEventListener("keydown", async (event) => {
  if (event.key === "Escape") {
    await cancelSelection();
  }
  if (event.key === "Enter") {
    await confirmSelection();
  }
});

// Starting from the box the last session used turns a reselect into a glance and
// an Enter, rather than redrawing the same rectangle every time. The window is
// reused rather than recreated, so this runs on every open, not just on load.
async function restoreLastSelection() {
  // The backend owns the saved region, so this can fail while it is still
  // starting. A blank selector is the right fallback: the user just drags.
  const region = await TAURI.core.invoke("get_capture_region").catch(() => null);
  if (region) {
    state.startX = region.x;
    state.startY = region.y;
    state.currentX = region.x + region.width;
    state.currentY = region.y + region.height;
  } else {
    // Nothing usable to reuse - a box left over from another monitor would point
    // the user at the wrong part of the screen.
    state.startX = 0;
    state.startY = 0;
    state.currentX = 0;
    state.currentY = 0;
  }
  renderSelection();
}

// The shell takes a still of the screen on its way to opening this window, so
// the box is drawn on what the user was watching rather than on whatever the
// desktop paints underneath a full-screen window.
async function paintBackdrop() {
  const dataUrl = await TAURI.core.invoke("get_selector_backdrop").catch(() => null);
  if (dataUrl) {
    backdrop.src = dataUrl;
    backdrop.classList.remove("hidden");
    return;
  }
  // Without one the desktop shows through, which is the next best thing.
  backdrop.classList.add("hidden");
  backdrop.removeAttribute("src");
}

// The window is reused rather than recreated, so each open runs these again.
function onOpened() {
  void paintBackdrop();
  void restoreLastSelection();
}

onOpened();
void TAURI.event.listen("tauri://focus", () => onOpened());
