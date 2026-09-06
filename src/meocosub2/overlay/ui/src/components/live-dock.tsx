import { useEffect, useState } from "react";
import { tauri } from "../hooks/use-tauri";

const EASE = "cubic-bezier(0.22, 1, 0.36, 1)";
// One press of the timing control. The backend rounds to its own step and
// holds the range, and answers with what it stored, so this is the size of a
// press rather than a rule about what an offset may be.
const BIAS_STEP_MS = 100;

/** The studio window while a session runs.
 *
 * The subtitles are drawn in the plate window beside the capture region, where
 * they do not cover the burned-in line they were read from. All that is left
 * here is a bead in the corner of the screen, which becomes the controls when
 * the pointer reaches it.
 *
 * The shell owns the shape and the state: it watches the desktop cursor and
 * clips the window to a pill that grows out of the corner. This page is told
 * how far open that pill is and fades its contents to match.
 */
export function LiveView({
  biasMs,
  onAdjustBias,
  onStop,
  onSelectRegion,
  onOpenSettings,
}: {
  biasMs: number;
  onAdjustBias: (deltaMs: number) => void;
  onStop: () => void;
  onSelectRegion: () => void;
  onOpenSettings: () => void;
}): JSX.Element {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | null = null;
    void tauri
      .listen("dock-open", (event) => {
        setOpen(Boolean((event as { payload?: boolean } | null)?.payload));
      })
      .then((stop) => {
        if (!stop) return;
        if (disposed) stop();
        else unlisten = stop;
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "flex-end",
        gap: 2,
        paddingRight: 7,
        background: "rgba(13,12,16,0.9)",
        boxSizing: "border-box",
        overflow: "hidden",
      }}
    >
      <Reveal open={open} delay={165}>
        <BiasControl biasMs={biasMs} onAdjust={onAdjustBias} />
      </Reveal>
      <Reveal open={open} delay={110}>
        <IconButton label="Stop sync" onClick={onStop}>
          <svg width="9" height="9" viewBox="0 0 10 10" fill="currentColor">
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

/** How far the plate is shifted, written the way the viewer set it. */
function formatBias(ms: number): string {
  const seconds = ms / 1000;
  return `${seconds > 0 ? "+" : ""}${seconds.toFixed(1)}s`;
}

/** Retiming, for a player whose subtitles do not sit where the clock expects.
 *
 * The plate is drawn from a clock anchored by matches, and a player that buffers
 * or a stream that is cut a beat differently leaves it consistently early or
 * late. Raising the offset shows each line sooner.
 */
function BiasControl({
  biasMs,
  onAdjust,
}: {
  biasMs: number;
  onAdjust: (deltaMs: number) => void;
}): JSX.Element {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
      <StepButton label="Show subtitles later" glyph="−" onClick={() => onAdjust(-BIAS_STEP_MS)} />
      <span
        aria-live="polite"
        style={{
          minWidth: 38,
          textAlign: "center",
          fontSize: 11,
          fontVariantNumeric: "tabular-nums",
          color: biasMs === 0 ? "#77767f" : "#b6b5c0",
        }}
      >
        {formatBias(biasMs)}
      </span>
      <StepButton label="Show subtitles earlier" glyph="+" onClick={() => onAdjust(BIAS_STEP_MS)} />
    </div>
  );
}

function StepButton({
  label,
  glyph,
  onClick,
}: {
  label: string;
  glyph: string;
  onClick: () => void;
}): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      style={{
        width: 22,
        height: 22,
        borderRadius: 100,
        border: "none",
        background: "rgba(255,255,255,0.07)",
        color: "#b6b5c0",
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 13,
        lineHeight: 1,
      }}
    >
      {glyph}
    </button>
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
        width: 30,
        height: 30,
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
        transform: open ? "translateX(0)" : "translateX(14px)",
        pointerEvents: open ? "auto" : "none",
        transition: [
          `opacity 180ms ease ${open ? delay : 0}ms`,
          `transform 300ms ${EASE} ${open ? delay : 0}ms`,
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
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      style={{
        width: 30,
        height: 30,
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

function TextButton({ label, onClick }: { label: string; onClick: () => void }): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        padding: "0 11px",
        height: 30,
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
