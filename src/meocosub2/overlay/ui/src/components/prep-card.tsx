import { getLocale, localizeMessage, t } from "../i18n";
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
  foundLabel: string;
  source: SourceItem | null;
  target: TargetItem | null;
  prepared: BackendPreparedSession | null;
  gapFill: BackendGapFill | null;
  onPickTarget: (resultId: string) => void;
}

export function PrepCard({
  titleLabel,
  foundLabel,
  source,
  target,
  prepared,
  gapFill,
  onPickTarget,
}: PrepCardProps): JSX.Element {
  const sourceFile =
    prepared?.session_mode === "ocr_fallback"
      ? t("On-screen subtitles")
      : (prepared?.source_summary ?? prepared?.source_file_name ?? source?.file ?? "—");
  const isAutoTranslation =
    prepared?.target_match_mode === "auto_live_translation" ||
    prepared?.target_match_mode === "direct_translation";
  const isLocalTranslation = prepared?.target_match_mode === "local_translation";
  // The source file is the target here, so naming it would read as an ordinary
  // pairing and hide where these translations actually come from.
  const isOwnTranslation = prepared?.target_match_mode === "source_own_translation";
  const targetLabel = isAutoTranslation
    ? t("Live translation (on device)")
    : isLocalTranslation
      ? t("Local translation (on device)")
      : isOwnTranslation
        ? t("Translation inside the source file")
        : (prepared?.target_file_name ?? target?.title ?? target?.file ?? "—");
  const lines = prepared?.source_line_count
    ? t("{count} prepared", { count: prepared.source_line_count.toLocaleString() })
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
        minWidth: 0,
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
        {t("Session ready")}
      </div>
      <div
        style={{
          fontSize: 22,
          color: "var(--text-heading)",
          fontWeight: 500,
          letterSpacing: -0.3,
        }}
      >
        {titleLabel || prepared?.title || t("Live screen translation")}
      </div>
      <div
        style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 12, fontSize: 13 }}
      >
        <Row label={t("Source")} value={sourceFile} mono />
        <Row
          label={t("Target")}
          value={targetLabel}
          tag={isAutoTranslation || isLocalTranslation ? "AUTO" : null}
        />
        <Row label={t("Found")} value={foundLabel} />
        <Row label={t("Lines")} value={lines} />
        {(chosenAlignment || gapFill) && (
          <Row label={t("Coverage")} value={coverageLabel(chosenAlignment, gapFill)} />
        )}
      </div>
      {prepared?.target_clock_unverified && (
        <p style={{ margin: 0, fontSize: 12, lineHeight: 1.5, color: "var(--text-label)" }}>
          {t(
            "Target timing is unverified. No consistent shared human subtitle text confirmed the file clocks, so matching timestamps are assumed. Check synchronization during playback and correct the target file in the editor if needed.",
          )}
        </p>
      )}
      {!!prepared?.subtitle_checks?.length && (
        <details style={{ fontSize: 12, color: "var(--text-label)" }}>
          <summary style={{ cursor: "pointer" }}>{t("Subtitles checked automatically")}</summary>
          <p style={{ whiteSpace: "pre-line", lineHeight: 1.6 }}>
            {prepared.subtitle_checks
              .map((check) =>
                [
                  `${check.file_name}:`,
                  check.reordered ? t("sorted by time;") : "",
                  check.duplicates_removed > 0
                    ? t("duplicates removed: {count};", { count: check.duplicates_removed })
                    : "",
                  check.empty_removed > 0
                    ? t("empty cues skipped: {count};", { count: check.empty_removed })
                    : "",
                  (check.drawings_removed ?? 0) > 0
                    ? t("drawing cues skipped: {count};", { count: check.drawings_removed ?? 0 })
                    : "",
                  t("ready for sync."),
                ]
                  .filter(Boolean)
                  .join(getLocale() === "zh-CN" ? "" : " "),
              )
              .join("\n")}
          </p>
          <p>
            {t("Changes apply to playback. Original files are unchanged. Editing is optional.")}
          </p>
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
            {better.unpaired_cues === 0
              ? t("{file} answers all of them.", { file: better.file_name })
              : t("{file} answers more of them.", { file: better.file_name })}
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
            {t("Use it")}
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
        {t("Press")} <Kbd>Ctrl ↵</Kbd> {t("to start sync")} · <Kbd>,</Kbd> {t("for settings")}
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
        minWidth: 0,
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
        <span>
          {t("Preview")} {line?.tc ? `· ${localizeMessage(line.tc)}` : ""}
        </span>
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
        {line?.text ?? t("Waiting for first subtitle…")}
      </div>
    </div>
  );
}
