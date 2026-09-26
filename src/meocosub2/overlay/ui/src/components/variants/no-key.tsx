export function NoApiKey({ onOpenSettings }: { onOpenSettings: () => void }): JSX.Element {
  return (
    <div
      style={{
        position: "absolute",
        top: "50%",
        left: "50%",
        transform: "translate(-50%, -50%)",
        width: "min(560px, calc(100vw - 32px))",
        boxSizing: "border-box",
        padding: 28,
        borderRadius: 16,
        background: "var(--danger-soft)",
        border: "1px solid var(--danger-ring)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
      }}
    >
      <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: 10,
            flexShrink: 0,
            background: "var(--danger-tint)",
            color: "var(--danger-text)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 18,
            fontWeight: 700,
          }}
        >
          !
        </div>
        <div style={{ flex: 1 }}>
          <div
            style={{
              fontSize: 11,
              letterSpacing: 1.5,
              color: "var(--danger-text)",
              fontWeight: 700,
              textTransform: "uppercase",
            }}
          >
            Setup required
          </div>
          <h2
            style={{
              margin: "6px 0 0",
              fontSize: 22,
              fontWeight: 500,
              color: "var(--text-heading)",
              letterSpacing: -0.3,
            }}
          >
            Add source credentials.
          </h2>
          <p
            style={{
              fontSize: 13,
              color: "#a8a8b2",
              marginTop: 8,
              lineHeight: 1.55,
            }}
          >
            At least one subtitle source credential must be configured before search. SubDL now
            requires an API key; ASSRT uses a token.
          </p>
          <div style={{ display: "flex", gap: 8, marginTop: 18 }}>
            <button
              type="button"
              onClick={onOpenSettings}
              style={{
                padding: "10px 16px",
                borderRadius: 8,
                border: "none",
                background: "linear-gradient(180deg, var(--accent-hex), var(--accent-deep))",
                color: "#1a0f08",
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Open Settings
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
