import type {
  BackendGapFill,
  BackendPreparedSession,
  LiveLine,
  SourceItem,
  TargetItem,
} from "../lib/types";
import { coverageLabel } from "../state/mappers";
import { Kbd } from "./primitives";
import { SubtitleEditor } from "./subtitle-editor/workspace";

interface PrepCardProps {
  titleLabel: string | null;
  runtimeLabel: string;
  source: SourceItem | null;
  target: TargetItem | null;
  prepared: BackendPreparedSession | null;
  gapFill: BackendGapFill | null;
  onPickTarget: (resultId: string) => void;
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
      {!!prepared?.subtitle_checks?.length && (
        <details style={{ fontSize: 12, color: "var(--text-label)" }}>
          <summary style={{ cursor: "pointer" }}>Subtitles checked automatically</summary>
          <p style={{ whiteSpace: "pre-line", lineHeight: 1.6 }}>
            {prepared.subtitle_checks
              .map((check) =>
                [
                  `${check.file_name}:`,
                  check.reordered ? "sorted by time;" : "",
                  check.duplicates_removed > 0
                    ? `duplicates removed: ${check.duplicates_removed};`
                    : "",
                  check.empty_removed > 0 ? `empty cues skipped: ${check.empty_removed};` : "",
                  "ready for sync.",
                ]
                  .filter(Boolean)
                  .join(" "),
              )
              .join("\n")}
          </p>
          <p>Changes apply to playback. Original files are unchanged. Editing is optional.</p>
        </details>
      )}
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
      {prepared &&
        (prepared.source_path || prepared.target_path || prepared.source_candidate_count > 0) && (
          <SubtitleEditor sessionId={prepared.session_id} />
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

export function PreviewCard({
  line,
  targetLanguage,
}: {
  line: LiveLine | null;
  targetLanguage: string;
}): JSX.Element {
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
        <span style={{ color: "var(--accent-text)" }}>{targetLanguage}</span>
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
