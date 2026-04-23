import { CatMascot, Kbd } from "../primitives";

export function EmptyState({
  sourceLabel,
  targetLabel,
  onOpenPalette,
}: {
  sourceLabel: string;
  targetLabel: string;
  onOpenPalette: () => void;
}): JSX.Element {
  return (
    <>
      <div
        style={{
          position: "absolute",
          top: 120,
          left: "50%",
          transform: "translateX(-50%)",
          textAlign: "center",
          width: 560,
        }}
      >
        <CatMascot size={96} expression="curious" />
        <div
          style={{
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 2.5,
            color: "var(--text-label)",
            textTransform: "uppercase",
            marginTop: 14,
          }}
        >
          First launch
        </div>
        <h1
          className="display-serif"
          style={{
            margin: "8px 0 0",
            fontSize: 34,
            fontWeight: 500,
            letterSpacing: -0.8,
            color: "var(--text-heading)",
          }}
        >
          Pick a language pair to begin.
        </h1>
        <p
          style={{
            fontSize: 14,
            color: "var(--text-muted)",
            marginTop: 10,
            lineHeight: 1.55,
          }}
        >
          Meowcal watches what's on screen and shows translated subtitles alongside.
        </p>
      </div>

      <div
        style={{
          position: "absolute",
          bottom: 120,
          left: "50%",
          transform: "translateX(-50%)",
          width: 560,
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        <div
          className="glass-panel"
          style={{
            display: "flex",
            gap: 10,
            padding: "16px 18px",
          }}
        >
          <div style={{ flex: 1 }}>
            <div
              style={{
                fontSize: 10,
                color: "var(--text-label)",
                letterSpacing: 1.2,
                fontWeight: 700,
                textTransform: "uppercase",
              }}
            >
              From
            </div>
            <div
              style={{
                fontSize: 16,
                fontWeight: 500,
                marginTop: 4,
                color: "var(--text-heading)",
              }}
            >
              {sourceLabel}
            </div>
          </div>
          <svg
            width="18"
            height="14"
            viewBox="0 0 18 14"
            fill="none"
            stroke="#6a6a76"
            strokeWidth="1.3"
            style={{ marginTop: 24 }}
            aria-hidden
          >
            <path d="M1 7h14M11 2l5 5-5 5" />
          </svg>
          <div style={{ flex: 1 }}>
            <div
              style={{
                fontSize: 10,
                color: "var(--accent-text)",
                letterSpacing: 1.2,
                fontWeight: 700,
                textTransform: "uppercase",
              }}
            >
              To
            </div>
            <div
              style={{
                fontSize: 16,
                fontWeight: 500,
                marginTop: 4,
                color: "var(--text-heading)",
              }}
            >
              {targetLabel}
            </div>
          </div>
        </div>
        <button
          onClick={onOpenPalette}
          style={{
            padding: "14px",
            borderRadius: 10,
            border: "none",
            background:
              "linear-gradient(180deg, var(--accent-hex), var(--accent-deep))",
            color: "#1a0f08",
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
          }}
        >
          Open command palette <Kbd>⌘K</Kbd>
        </button>
      </div>
    </>
  );
}
