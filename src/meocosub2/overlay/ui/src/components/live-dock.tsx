import { useState } from "react";
import { tauri } from "../hooks/use-tauri";

/** The dock at rest, and the dock with the pointer on it, in CSS pixels. */
const COLLAPSED = 52;
const EXPANDED_WIDTH = 292;
const EXPANDED_HEIGHT = 52;
const EASE = "cubic-bezier(0.22, 1, 0.36, 1)";

/** The studio window while a session runs.
 *
 * The subtitles are drawn in the plate window beside the capture region, where
 * they do not cover the burned-in line they were read from. All that is left
 * here is a bead in the corner of the screen, which becomes the controls when
 * the pointer reaches it and goes back to being a bead when it leaves.
 *
 * The shell owns the shape: it walks the window between the two sizes and clips
 * it to a pill. This page only fades the contents in and out of it.
 */
export function LiveView({
  onStop,
  onSelectRegion,
  onOpenSettings,
}: {
  onStop: () => void;
  onSelectRegion: () => void;
  onOpenSettings: () => void;
}): JSX.Element {
  const [open, setOpen] = useState(false);

  const setDock = (next: boolean): void => {
    if (next === open) return;
    setOpen(next);
    void tauri.setDockSize(
      next ? EXPANDED_WIDTH : COLLAPSED,
      next ? EXPANDED_HEIGHT : COLLAPSED,
    );
  };

  return (
    <div
      onMouseEnter={() => setDock(true)}
      onMouseLeave={() => setDock(false)}
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "flex-end",
        gap: 2,
        paddingRight: 9,
        background: "rgba(13,12,16,0.86)",
        boxSizing: "border-box",
        overflow: "hidden",
      }}
    >
      <Reveal open={open} delay={110}>
        <IconButton label="Stop sync" onClick={onStop}>
          <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
            <rect x="0.5" y="0.5" width="9" height="9" rx="1.4" />
          </svg>
        </IconButton>
      </Reveal>
      <Reveal open={open} delay={55}>
        <TextButton label="Region" onClick={onSelectRegion} />
      </Reveal>
      <Reveal open={open} delay={0}>
        <TextButton label="Settings" onClick={onOpenSettings} />
      </Reveal>
      <Pulse />
    </div>
  );
}

/** The one thing on screen while the dock rests: proof the session is running. */
function Pulse(): JSX.Element {
  return (
    <div
      style={{
        flex: "0 0 auto",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        width: 34,
        height: 34,
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: 4,
          background: "var(--accent-hex)",
          boxShadow: "0 0 10px var(--accent-hex)",
          animation: "pulse 1.4s ease-in-out infinite",
        }}
      />
    </div>
  );
}

/** Controls arrive from the corner the dock grows out of, nearest one first. */
function Reveal({
  open,
  delay,
  children,
}: {
  open: boolean;
  delay: number;
  children: JSX.Element;
}): JSX.Element {
  return (
    <div
      style={{
        flex: "0 0 auto",
        opacity: open ? 1 : 0,
        transform: open ? "translateX(0)" : "translateX(18px)",
        pointerEvents: open ? "auto" : "none",
        transition: [
          `opacity 200ms ease ${open ? delay : 0}ms`,
          `transform 320ms ${EASE} ${open ? delay : 0}ms`,
        ].join(", "),
      }}
    >
      {children}
    </div>
  );
}

function IconButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: JSX.Element;
}): JSX.Element {
  return (
    <button
      onClick={onClick}
      title={label}
      aria-label={label}
      style={{
        width: 34,
        height: 34,
        borderRadius: 100,
        border: "none",
        background: "rgba(255,90,90,0.16)",
        color: "#ff8f8f",
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {children}
    </button>
  );
}

function TextButton({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}): JSX.Element {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "0 12px",
        height: 34,
        borderRadius: 100,
        border: "none",
        background: "transparent",
        color: "#b6b5c0",
        cursor: "pointer",
        fontSize: 12,
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </button>
  );
}
