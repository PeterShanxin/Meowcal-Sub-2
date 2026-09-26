import type { CSSProperties, ReactNode } from "react";
import type { EngineStatus, InfoChip } from "../lib/types";

const ENGINE_LABELS: Record<EngineStatus["phase"], string> = {
  ready: "Translation ✓",
  idle: "Translation ready",
  installing: "Translation installing",
  needsSetup: "Translation needs setup",
  failed: "Translation failed",
  unsupported: "Translation unsupported",
};

function engineLabel(status: EngineStatus | null): string {
  if (!status) return "Translation —";
  if (status.phase === "installing") {
    return `Translation installing ${status.installPercent}%`;
  }
  return ENGINE_LABELS[status.phase] ?? "Translation —";
}

export function DisclosureChevron({ open }: { open: boolean }): JSX.Element {
  return (
    <svg
      width="10"
      height="10"
      viewBox="0 0 10 10"
      aria-hidden
      style={{
        transform: open ? "rotate(90deg)" : "rotate(0deg)",
        transition: "transform 180ms cubic-bezier(.2,.8,.3,1)",
        color: "var(--text-label)",
        flexShrink: 0,
      }}
    >
      <path
        d="M3 1.5 L7 5 L3 8.5"
        stroke="currentColor"
        strokeWidth="1.4"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function chipStyle(tone: InfoChip["tone"]): CSSProperties {
  if (tone === "accent") {
    return {
      background: "rgba(255,185,90,0.10)",
      border: "1px solid var(--accent-ring)",
      color: "var(--accent-text)",
    };
  }
  if (tone === "verified") {
    return {
      background: "rgba(120,200,130,0.12)",
      border: "1px solid rgba(120,200,130,0.28)",
      color: "#8ec99a",
    };
  }
  return {
    background: "rgba(255,255,255,0.04)",
    border: "1px solid rgba(255,255,255,0.08)",
    color: "var(--text-label)",
  };
}

export function InfoChipRow({
  chips,
  max = 4,
}: {
  chips: InfoChip[];
  max?: number;
}): JSX.Element | null {
  if (!chips || chips.length === 0) return null;
  const shown = chips.slice(0, max);
  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 6,
        marginTop: 6,
      }}
    >
      {shown.map((chip, i) => (
        <span
          key={`${chip.kind}-${i}-${chip.label}`}
          style={{
            ...chipStyle(chip.tone),
            padding: "2px 7px",
            borderRadius: 999,
            fontSize: 10.5,
            letterSpacing: 0.2,
            fontWeight: 500,
            whiteSpace: "nowrap",
          }}
        >
          {chip.label}
        </span>
      ))}
    </div>
  );
}

export function Kbd({ children, dim }: { children: ReactNode; dim?: boolean }): JSX.Element {
  return <kbd data-dim={dim ? "true" : "false"}>{children}</kbd>;
}

export function CatMascot({ size = 56 }: { size?: number }): JSX.Element {
  return (
    <img
      src="/static/shadow-cat-mark.svg"
      width={size}
      height={size}
      alt=""
      style={{ display: "block", margin: "0 auto" }}
    />
  );
}

export function Backdrop(): JSX.Element {
  return (
    <>
      <div
        style={{
          position: "absolute",
          inset: 0,
          pointerEvents: "none",
          opacity: 0.3,
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px)",
          backgroundSize: "40px 40px",
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 700,
          height: 700,
          top: -160,
          right: -200,
          borderRadius: "50%",
          pointerEvents: "none",
          opacity: 0.5,
          background: "radial-gradient(circle, rgba(242,199,143,0.09), transparent 65%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          width: 500,
          height: 500,
          bottom: -150,
          left: -100,
          borderRadius: "50%",
          pointerEvents: "none",
          opacity: 0.3,
          background: "radial-gradient(circle, rgba(242,199,143,0.07), transparent 60%)",
        }}
      />
    </>
  );
}

const topBarButtonStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  width: 26,
  height: 26,
  padding: 0,
  marginLeft: 4,
  borderRadius: 7,
  border: "1px solid rgba(255,255,255,0.06)",
  background: "rgba(255,255,255,0.02)",
  color: "var(--text-label)",
  cursor: "pointer",
  transition: "background 160ms ease, color 160ms ease",
};

function highlight(event: { currentTarget: HTMLButtonElement }): void {
  event.currentTarget.style.background = "var(--accent-tint)";
  event.currentTarget.style.color = "var(--accent-text)";
}

function unhighlight(event: { currentTarget: HTMLButtonElement }): void {
  event.currentTarget.style.background = "rgba(255,255,255,0.02)";
  event.currentTarget.style.color = "var(--text-label)";
}

export function TopBar({
  phase,
  wsConnected,
  engineStatus,
  sourcesCount,
  onOpenSettings,
  onClearSession,
}: {
  phase: "home" | "prep" | "live" | "settings" | "empty" | "no-key";
  wsConnected: boolean;
  engineStatus: EngineStatus | null;
  sourcesCount: number;
  onOpenSettings?: () => void;
  onClearSession?: () => void;
}): JSX.Element {
  const label =
    phase === "live"
      ? "Live"
      : phase === "prep"
        ? "Prepared"
        : phase === "settings"
          ? "Settings"
          : "Idle";
  const dotColor = phase === "live" ? "var(--accent-hex)" : "var(--ok-hex)";
  return (
    <div
      style={{
        position: "relative",
        display: "flex",
        alignItems: "center",
        padding: "14px 20px",
        fontSize: 12,
        color: "var(--text-label)",
        whiteSpace: "nowrap",
        zIndex: 5,
      }}
    >
      <div style={{ flex: 1 }} />
      <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: 4,
              background: dotColor,
              boxShadow: phase === "live" ? "0 0 8px var(--accent-hex)" : "none",
              animation: phase === "live" ? "pulse 1.4s ease-in-out infinite" : "none",
            }}
          />
          {label}
        </span>
        <span className="top-bar-detail" style={{ color: "#3a3a46" }}>
          ·
        </span>
        <span className="top-bar-detail" title={engineStatus?.message ?? ""}>
          {engineLabel(engineStatus)}
        </span>
        <span className="top-bar-detail" style={{ color: "#3a3a46" }}>
          ·
        </span>
        <span className="top-bar-detail">
          {sourcesCount} {sourcesCount === 1 ? "source" : "sources"}
        </span>
        <span style={{ color: "#3a3a46" }}>·</span>
        <span title={wsConnected ? "Connected" : "Reconnecting…"}>{wsConnected ? "●" : "○"}</span>
        {onClearSession && (
          <button
            type="button"
            onClick={onClearSession}
            aria-label="Clear session"
            title="Clear session (⇧⌫)"
            style={topBarButtonStyle}
            onMouseEnter={highlight}
            onMouseLeave={unhighlight}
          >
            <ResetIcon />
          </button>
        )}
        {onOpenSettings && (
          <button
            type="button"
            onClick={onOpenSettings}
            aria-label="Open settings"
            title="Settings (,)"
            style={topBarButtonStyle}
            onMouseEnter={highlight}
            onMouseLeave={unhighlight}
          >
            <GearIcon />
          </button>
        )}
      </div>
    </div>
  );
}

function ResetIcon(): JSX.Element {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 4v5h5" />
    </svg>
  );
}

function GearIcon(): JSX.Element {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

export function PaletteTabs({
  tabs,
  active,
  onChange,
}: {
  tabs: Array<{ id: string; label: string; count: number }>;
  active: string;
  onChange: (id: string) => void;
}): JSX.Element {
  return (
    <div
      style={{
        display: "flex",
        gap: 2,
        padding: "10px 16px",
        borderBottom: "1px solid rgba(255,255,255,0.05)",
        background: "rgba(255,255,255,0.015)",
      }}
    >
      {tabs.map((t) => {
        const isActive = active === t.id;
        const style: CSSProperties = {
          display: "flex",
          alignItems: "center",
          gap: 9,
          padding: "7px 14px",
          border: "none",
          background: isActive ? "var(--accent-tint)" : "transparent",
          color: isActive ? "var(--accent-text)" : "var(--text-muted)",
          cursor: "pointer",
          borderRadius: 7,
          fontSize: 13.5,
          fontWeight: 500,
        };
        return (
          <button type="button" key={t.id} onClick={() => onChange(t.id)} style={style}>
            {t.label}
            <span
              style={{
                fontSize: 11,
                color: isActive ? "var(--accent-text)" : "var(--text-dim)",
                opacity: 0.75,
              }}
            >
              {t.count}
            </span>
          </button>
        );
      })}
      <div style={{ flex: 1 }} />
      <span
        style={{
          fontSize: 12,
          color: "var(--text-dim)",
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        <Kbd dim>Tab</Kbd> switch
      </span>
    </div>
  );
}
