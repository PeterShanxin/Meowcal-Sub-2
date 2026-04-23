import type { LiveLine } from "../lib/types";

export function LiveView({
  prev,
  current,
  onStop,
  onSelectRegion,
  onOpenSettings,
}: {
  prev: LiveLine | null;
  current: LiveLine | null;
  onStop: () => void;
  onSelectRegion: () => void;
  onOpenSettings: () => void;
}): JSX.Element {
  return (
    <>
      <div
        style={{
          position: "absolute",
          inset: 0,
          zIndex: 1,
          background:
            "radial-gradient(ellipse at 20% 30%, rgba(231,111,81,0.18), transparent 40%), radial-gradient(ellipse at 80% 20%, rgba(244,162,97,0.12), transparent 45%), linear-gradient(180deg, transparent 30%, rgba(0,0,0,0.5) 100%)",
          pointerEvents: "none",
        }}
      />

      {prev?.text && (
        <div
          style={{
            position: "absolute",
            bottom: 160,
            left: 0,
            right: 0,
            textAlign: "center",
            zIndex: 3,
          }}
        >
          <div
            className="display-serif"
            style={{
              fontSize: 13,
              color: "rgba(255,255,255,0.35)",
            }}
          >
            {prev.text}
          </div>
        </div>
      )}

      <div
        style={{
          position: "absolute",
          bottom: 100,
          left: 0,
          right: 0,
          textAlign: "center",
          zIndex: 3,
          padding: "0 80px",
        }}
      >
        <div
          style={{
            fontSize: 38,
            fontWeight: 500,
            lineHeight: 1.3,
            letterSpacing: -0.3,
            color: "#fff",
            textShadow: "0 2px 20px rgba(0,0,0,0.7)",
            fontFamily: "var(--font-target)",
            marginBottom: 8,
          }}
        >
          {current?.text ?? "…"}
        </div>
      </div>

      <LiveDock
        tc={current?.tc ?? ""}
        onStop={onStop}
        onSelectRegion={onSelectRegion}
        onOpenSettings={onOpenSettings}
      />
    </>
  );
}

function LiveDock({
  tc,
  onStop,
  onSelectRegion,
  onOpenSettings,
}: {
  tc: string;
  onStop: () => void;
  onSelectRegion: () => void;
  onOpenSettings: () => void;
}): JSX.Element {
  return (
    <div
      style={{
        position: "absolute",
        bottom: 20,
        left: "50%",
        transform: "translateX(-50%)",
        display: "flex",
        alignItems: "center",
        gap: 4,
        padding: 6,
        borderRadius: 100,
        background: "rgba(0,0,0,0.6)",
        backdropFilter: "blur(24px)",
        WebkitBackdropFilter: "blur(24px)",
        border: "1px solid rgba(255,255,255,0.08)",
        boxShadow: "0 20px 50px rgba(0,0,0,0.5)",
        zIndex: 4,
      }}
    >
      <button
        onClick={onStop}
        title="Stop sync"
        style={{
          width: 40,
          height: 40,
          borderRadius: 100,
          border: "none",
          background: "rgba(255,90,90,0.15)",
          color: "#ff8f8f",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <svg width="11" height="11" viewBox="0 0 11 11" fill="currentColor">
          <rect x="1.5" y="1.5" width="8" height="8" rx="1" />
        </svg>
      </button>
      <Divider />
      <div
        className="mono"
        style={{
          padding: "0 14px",
          fontSize: 12,
          color: "#a8a8b2",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        <span style={{ color: "var(--accent-text)" }}>{tc || "—"}</span>
      </div>
      <Divider />
      <DockButton label="Region" onClick={onSelectRegion} />
      <DockButton label="Settings" onClick={onOpenSettings} />
      <Divider />
      <div
        style={{
          padding: "0 12px",
          fontSize: 11,
          color: "var(--text-label)",
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: 3,
            background: "var(--accent-hex)",
            boxShadow: "0 0 6px var(--accent-hex)",
            animation: "pulse 1.4s ease-in-out infinite",
          }}
        />
        live
      </div>
    </div>
  );
}

function Divider(): JSX.Element {
  return (
    <div
      style={{
        width: 1,
        height: 22,
        background: "rgba(255,255,255,0.08)",
        margin: "0 4px",
      }}
    />
  );
}

function DockButton({
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
        padding: "0 14px",
        height: 40,
        borderRadius: 100,
        border: "none",
        background: "transparent",
        color: "#a8a8b2",
        cursor: "pointer",
        fontSize: 12,
      }}
    >
      {label}
    </button>
  );
}
