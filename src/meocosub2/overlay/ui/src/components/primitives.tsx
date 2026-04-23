import type { CSSProperties, ReactNode } from "react";

export function Kbd({
  children,
  dim,
}: {
  children: ReactNode;
  dim?: boolean;
}): JSX.Element {
  return <kbd data-dim={dim ? "true" : "false"}>{children}</kbd>;
}

export function CatMark({ size = 18 }: { size?: number }): JSX.Element {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 18 18"
      style={{ display: "block" }}
      aria-hidden
    >
      <defs>
        <linearGradient id="catgrad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--accent-hex)" />
          <stop offset="1" stopColor="var(--accent-deep)" />
        </linearGradient>
      </defs>
      <path d="M2 15 L2 5 L6 8 L12 8 L16 5 L16 15 Z" fill="url(#catgrad)" />
      <circle cx="6.5" cy="11.5" r="0.9" fill="#1a1014" />
      <circle cx="11.5" cy="11.5" r="0.9" fill="#1a1014" />
    </svg>
  );
}

export function CatMascot({
  size = 56,
  expression = "curious",
}: {
  size?: number;
  expression?: "curious" | "sleepy";
}): JSX.Element {
  const gradId = `catbody-${expression}`;
  return (
    <svg
      width={size}
      height={size * 1.1}
      viewBox="0 0 100 110"
      style={{ display: "block" }}
      aria-hidden
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--accent-hex)" stopOpacity="0.35" />
          <stop offset="1" stopColor="var(--accent-deep)" stopOpacity="0.5" />
        </linearGradient>
      </defs>
      <path d="M18 32 L22 12 L38 24 Z" fill={`url(#${gradId})`} />
      <path d="M82 32 L78 12 L62 24 Z" fill={`url(#${gradId})`} />
      <ellipse cx="50" cy="45" rx="30" ry="27" fill={`url(#${gradId})`} />
      <path
        d="M25 60 Q25 95 50 100 Q75 95 75 60 Z"
        fill={`url(#${gradId})`}
        opacity="0.8"
      />
      {expression === "sleepy" ? (
        <>
          <path
            d="M38 44 Q42 42 46 44"
            stroke="var(--accent-hex)"
            strokeWidth="1.8"
            fill="none"
            strokeLinecap="round"
          />
          <path
            d="M54 44 Q58 42 62 44"
            stroke="var(--accent-hex)"
            strokeWidth="1.8"
            fill="none"
            strokeLinecap="round"
          />
        </>
      ) : (
        <>
          <ellipse cx="42" cy="44" rx="2.4" ry="4" fill="var(--accent-hex)" />
          <ellipse cx="58" cy="44" rx="2.4" ry="4" fill="var(--accent-hex)" />
        </>
      )}
      <path d="M48 52 L52 52 L50 55 Z" fill="var(--accent-hex)" opacity="0.8" />
      <path
        d="M30 54 L42 53 M30 57 L42 55"
        stroke="var(--accent-hex)"
        strokeWidth="0.8"
        opacity="0.5"
      />
      <path
        d="M70 54 L58 53 M70 57 L58 55"
        stroke="var(--accent-hex)"
        strokeWidth="0.8"
        opacity="0.5"
      />
    </svg>
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
          background:
            "radial-gradient(circle, rgba(242,199,143,0.09), transparent 65%)",
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
          background:
            "radial-gradient(circle, rgba(242,199,143,0.07), transparent 60%)",
        }}
      />
    </>
  );
}

export function TopBar({
  phase,
  wsConnected,
  foundryPhase,
  sourcesCount,
}: {
  phase: "home" | "prep" | "live" | "settings" | "empty" | "no-key";
  wsConnected: boolean;
  foundryPhase: string;
  sourcesCount: number;
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
        zIndex: 5,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <CatMark />
        <span style={{ color: "var(--text-body)", fontWeight: 600 }}>Meowcal</span>
      </div>
      <div style={{ flex: 1 }} />
      <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: 4,
              background: dotColor,
              boxShadow:
                phase === "live" ? "0 0 8px var(--accent-hex)" : "none",
              animation:
                phase === "live" ? "pulse 1.4s ease-in-out infinite" : "none",
            }}
          />
          {label}
        </span>
        <span style={{ color: "#3a3a46" }}>·</span>
        <span>Foundry {foundryPhase === "ready" ? "✓" : foundryPhase || "—"}</span>
        <span style={{ color: "#3a3a46" }}>·</span>
        <span>{sourcesCount} sources</span>
        <span style={{ color: "#3a3a46" }}>·</span>
        <span title={wsConnected ? "Connected" : "Reconnecting…"}>
          {wsConnected ? "●" : "○"}
        </span>
      </div>
    </div>
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
        padding: "8px 12px",
        borderBottom: "1px solid rgba(255,255,255,0.05)",
        background: "rgba(255,255,255,0.015)",
      }}
    >
      {tabs.map((t) => {
        const isActive = active === t.id;
        const style: CSSProperties = {
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 12px",
          border: "none",
          background: isActive ? "var(--accent-tint)" : "transparent",
          color: isActive ? "var(--accent-text)" : "var(--text-muted)",
          cursor: "pointer",
          borderRadius: 6,
          fontSize: 12,
          fontWeight: 500,
        };
        return (
          <button key={t.id} onClick={() => onChange(t.id)} style={style}>
            {t.label}
            <span
              style={{
                fontSize: 10,
                color: isActive ? "var(--accent-text)" : "var(--text-dim)",
                opacity: 0.7,
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
          fontSize: 11,
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
