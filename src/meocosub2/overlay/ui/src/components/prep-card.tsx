import type {
  BackendGapFill,
  BackendPreparedSession,
  BackendTargetAlignment,
  LiveLine,
  SourceItem,
  TargetItem,
} from "../lib/types";
import { Kbd } from "./primitives";

interface PrepCardProps {
  titleLabel: string | null;
  runtimeLabel: string;
  source: SourceItem | null;
  target: TargetItem | null;
  prepared: BackendPreparedSession | null;
  gapFill: BackendGapFill | null;
  onPickTarget: (resultId: string) => void;
}

function plural(count: number): string {
  return count === 1 ? "1 line" : `${count} lines`;
}

/**
 * What the chosen target file leaves for the model, in the viewer's terms.
 *
 * The same number throughout, read at whatever stage it has reached: what the
 * model will have to write, what it is writing, and what it wrote. The seconds
 * are dropped once filling starts, because they measure the whole hole and only
 * part of it is left.
 */
export function coverageLabel(
  chosen: BackendTargetAlignment | null,
  fill: BackendGapFill | null,
): string {
  if (fill === null) {
    if (chosen === null || chosen.unpaired_cues === 0) return "every line answered";
    const seconds = Math.round(chosen.unpaired_ms / 1000);
    return `${plural(chosen.unpaired_cues)} written on this device · ${seconds}s`;
  }
  if (fill.active) return `writing ${fill.filled} of ${fill.total} lines on this device…`;
  const left = fill.total - fill.filled;
  if (left <= 0) return "every line answered";
  return `${plural(left)} of ${fill.total} still to write on this device`;
}

export function PrepCard({
  titleLabel,
  runtimeLabel,
  source,
  target,
  prepared,
  gapFill,
  onPickTarget,
}: PrepCardProps): JSX.Element {
  const sourceFile = prepared?.source_summary ?? prepared?.source_file_name ?? source?.file ?? "—";
  const isAutoTranslation = prepared?.target_match_mode === "auto_live_translation";
  const isLocalTranslation = prepared?.target_match_mode === "local_translation";
  // The source file is the target here, so naming it would read as an ordinary
  // pairing and hide where these translations actually come from.
  const isOwnTranslation = prepared?.target_match_mode === "source_own_translation";
  const targetLabel = isAutoTranslation
    ? "Live translation (Foundry)"
    : isLocalTranslation
      ? "Local translation (Foundry)"
      : isOwnTranslation
        ? "Translation inside the source file"
        : (prepared?.target_file_name ?? target?.title ?? target?.file ?? "—");
  const lines = prepared?.source_line_count
    ? `${prepared.source_line_count.toLocaleString()} prepared`
    : "—";
  const alignment = prepared?.target_alignment ?? [];
  const chosenAlignment = alignment.find((entry) => entry.chosen) ?? null;
  // Ranked best first by the backend, so a better one is simply the first entry
  // that is not the viewer's own pick.
  const better =
    chosenAlignment && chosenAlignment.unpaired_cues > 0
      ? (alignment.find(
          (entry) => !entry.chosen && entry.unpaired_ms < chosenAlignment.unpaired_ms,
        ) ?? null)
      : null;

  return (
    <div
      className="glass-panel fade-in"
      style={{
        padding: 22,
        display: "flex",
        flexDirection: "column",
        gap: 14,
      }}
    >
      <div
        style={{
          fontSize: 10,
          letterSpacing: 1.8,
          color: "var(--text-label)",
          fontWeight: 700,
          textTransform: "uppercase",
        }}
      >
        Session ready
      </div>
      <div
        style={{
          fontSize: 22,
          color: "var(--text-heading)",
          fontWeight: 500,
          letterSpacing: -0.3,
        }}
      >
        {titleLabel ?? prepared?.title ?? "Untitled"}
      </div>
      <div style={{ display: "grid", gap: 12, fontSize: 13 }}>
        <Row label="Source" value={sourceFile} mono />
        <Row
          label="Target"
          value={targetLabel}
          tag={isAutoTranslation || isLocalTranslation ? "AUTO" : null}
        />
        <Row label="Runtime" value={runtimeLabel} />
        <Row label="Lines" value={lines} />
        {(chosenAlignment || gapFill) && (
          <Row label="Coverage" value={coverageLabel(chosenAlignment, gapFill)} />
        )}
      </div>
      {better && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            fontSize: 12,
            color: "var(--text-label)",
          }}
        >
          <span style={{ flex: 1 }}>
            {better.file_name} answers {better.unpaired_cues === 0 ? "all of them" : "more of them"}
            .
          </span>
          <button
            type="button"
            onClick={() => onPickTarget(better.result_id)}
            style={{
              padding: "4px 10px",
              borderRadius: 100,
              border: "1px solid var(--text-label)",
              background: "transparent",
              color: "var(--text-body)",
              cursor: "pointer",
              fontSize: 11,
              whiteSpace: "nowrap",
            }}
          >
            Use it
          </button>
        </div>
      )}
      <div style={{ flex: 1 }} />
      <div
        style={{
          display: "flex",
          gap: 10,
          alignItems: "center",
          fontSize: 12,
          color: "var(--text-label)",
        }}
      >
        Press <Kbd>⌘↵</Kbd> to start sync · <Kbd>,</Kbd> for settings
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  mono,
  tag,
}: {
  label: string;
  value: string;
  mono?: boolean;
  tag?: string | null;
}): JSX.Element {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
      <div
        style={{
          width: 72,
          fontSize: 11,
          color: "var(--text-label)",
          letterSpacing: 0.5,
          textTransform: "uppercase",
          flexShrink: 0,
        }}
      >
        {label}
      </div>
      <div
        className={mono ? "mono" : ""}
        style={{
          flex: 1,
          color: "var(--text-body)",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {value}
      </div>
      {tag && (
        <span
          style={{
            fontSize: 9,
            padding: "2px 6px",
            background: "var(--accent-hex)",
            color: "#1a0f08",
            borderRadius: 3,
            fontWeight: 700,
            letterSpacing: 0.6,
          }}
        >
          {tag}
        </span>
      )}
    </div>
  );
}

export function PreviewCard({ line }: { line: LiveLine | null }): JSX.Element {
  return (
    <div
      className="fade-in"
      style={{
        padding: 22,
        borderRadius: 14,
        background: "linear-gradient(180deg, #1c1a16, #0a0807)",
        border: "1px solid rgba(255,255,255,0.06)",
        display: "flex",
        flexDirection: "column",
        gap: 12,
        minHeight: 160,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 10,
          color: "var(--text-label)",
          letterSpacing: 1.5,
          fontWeight: 700,
          textTransform: "uppercase",
        }}
      >
        <span>Preview {line?.tc ? `· ${line.tc}` : ""}</span>
        <span style={{ color: "var(--accent-text)" }}>zh-TW</span>
      </div>
      <div style={{ flex: 1 }} />
      <div
        style={{
          fontSize: 22,
          color: "#fff",
          fontWeight: 500,
          lineHeight: 1.4,
          fontFamily: "var(--font-target)",
          minHeight: 32,
        }}
      >
        {line?.text ?? "Waiting for first subtitle…"}
      </div>
    </div>
  );
}
