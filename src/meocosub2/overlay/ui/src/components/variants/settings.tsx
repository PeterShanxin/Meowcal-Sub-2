import { useEffect, useRef, useState } from "react";
import type { BackendConfig, EngineStatus } from "../../lib/types";
import { api } from "../../hooks/use-api";
import { tauri } from "../../hooks/use-tauri";
import {
  FONT_PRESETS,
  loadFontScale,
  presetLabel,
  setFontScale,
  type FontPresetName,
} from "../../lib/font-scale";
import { Kbd } from "../primitives";

type SectionId =
  | "appearance"
  | "sources"
  | "capture"
  | "overlay"
  | "translate"
  | "matching"
  | "debug";

interface Section {
  id: SectionId;
  label: string;
}

const SECTIONS: Section[] = [
  { id: "appearance", label: "Appearance" },
  { id: "sources", label: "Subtitle sources" },
  { id: "capture", label: "Capture" },
  { id: "overlay", label: "Overlay style" },
  { id: "translate", label: "Translation" },
  { id: "matching", label: "Matching" },
  { id: "debug", label: "Debug" },
];

const SETTINGS_CLOSE_ANIMATION_MS = 160;

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "a[href]",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export function SettingsView({
  initialConfig,
  onClose,
  open,
  engine,
  onInstallEngine,
}: {
  initialConfig: BackendConfig;
  onClose: () => void;
  open: boolean;
  engine: EngineStatus | null;
  onInstallEngine: () => void;
}): JSX.Element {
  const [section, setSection] = useState<SectionId>("sources");
  const [draft, setDraft] = useState<BackendConfig>(initialConfig);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [banner, setBanner] = useState<{
    kind: "ok" | "error";
    text: string;
  } | null>(null);
  const [motionState, setMotionState] = useState<"hidden" | "open" | "closing">(
    open ? "open" : "hidden",
  );
  const backdropRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const closeTimerRef = useRef<number | null>(null);
  const previousFocusRef = useRef<Element | null>(null);

  useEffect(() => {
    if (open) {
      if (closeTimerRef.current !== null) {
        window.clearTimeout(closeTimerRef.current);
        closeTimerRef.current = null;
      }
      setMotionState("open");
    } else {
      setMotionState((current) => {
        if (current === "open") {
          const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
          const delay = reducedMotion ? 0 : SETTINGS_CLOSE_ANIMATION_MS;
          closeTimerRef.current = window.setTimeout(() => {
            setMotionState("hidden");
            closeTimerRef.current = null;
          }, delay);
          return "closing";
        }
        return current;
      });
    }
  }, [open]);

  useEffect(() => {
    const el = backdropRef.current;
    if (!el) return;
    if (motionState === "hidden") {
      el.setAttribute("inert", "");
      el.setAttribute("aria-hidden", "true");
    } else {
      el.removeAttribute("inert");
      el.removeAttribute("aria-hidden");
    }
  }, [motionState]);

  useEffect(() => {
    setDraft(initialConfig);
    setDirty(false);
  }, [initialConfig]);

  useEffect(() => {
    if (motionState === "hidden") return;

    if (motionState === "open") {
      previousFocusRef.current = document.activeElement;
      closeButtonRef.current?.focus({ preventScroll: true });
    }

    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      const dialog = dialogRef.current;
      if (!dialog) {
        return;
      }

      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      ).filter((element) => element.offsetParent !== null);
      if (focusable.length === 0) {
        event.preventDefault();
        closeButtonRef.current?.focus({ preventScroll: true });
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      // Restore focus only when the closing animation finishes (closing → hidden).
      // The closure captures motionState at effect-run time, so this fires only
      // for the "closing" invocation's cleanup, not the "open" one.
      if (motionState === "closing") {
        const previousFocus = previousFocusRef.current;
        if (previousFocus instanceof HTMLElement && previousFocus.isConnected) {
          previousFocus.focus({ preventScroll: true });
        }
      }
    };
  }, [motionState, onClose]);

  useEffect(() => {
    return () => {
      if (closeTimerRef.current !== null) {
        window.clearTimeout(closeTimerRef.current);
      }
    };
  }, []);

  const update = (patch: (c: BackendConfig) => BackendConfig): void => {
    setDraft((prev) => patch(prev));
    setDirty(true);
  };

  const save = async (): Promise<void> => {
    setSaving(true);
    setBanner(null);
    try {
      const next = await api.putConfig(draft);
      setDraft(next);
      setDirty(false);
      setBanner({ kind: "ok", text: "Settings saved." });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Save failed";
      setBanner({ kind: "error", text: msg });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      ref={backdropRef}
      className="settings-backdrop"
      data-motion={motionState}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      style={{
        position: "absolute",
        inset: 0,
        zIndex: 30,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "72px 28px 28px",
        background: "rgba(7,7,10,0.04)",
      }}
    >
      <div
        ref={dialogRef}
        className="settings-dialog glass-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        onMouseDown={(event) => event.stopPropagation()}
        style={{
          position: "relative",
          width: "min(920px, calc(100vw - 48px))",
          height: "min(760px, calc(100vh - 112px))",
          minHeight: 0,
          display: "grid",
          gridTemplateColumns: "var(--settings-dialog-columns, 220px minmax(0, 1fr))",
          overflow: "hidden",
          boxShadow:
            "0 30px 86px rgba(0,0,0,0.42), 0 0 0 1px rgba(242,199,143,0.04)",
        }}
      >
        <button type="button"
          ref={closeButtonRef}
          onClick={onClose}
          aria-label="Close settings"
          title="Close settings"
          style={{
            position: "absolute",
            top: 14,
            right: 14,
            zIndex: 3,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            width: 30,
            height: 30,
            padding: 0,
            borderRadius: 7,
            border: "1px solid rgba(255,255,255,0.08)",
            background: "rgba(255,255,255,0.035)",
            color: "var(--text-muted)",
            cursor: "pointer",
          }}
        >
          <CloseIcon />
        </button>
        <aside
          style={{
            padding: "18px 12px",
            display: "flex",
            flexDirection: "column",
            gap: 2,
            minHeight: 0,
            borderRight: "1px solid rgba(255,255,255,0.06)",
            background: "rgba(0,0,0,0.12)",
          }}
        >
          <div
            style={{
              fontSize: 10,
              letterSpacing: 1.5,
              color: "var(--text-label)",
              fontWeight: 700,
              textTransform: "uppercase",
              padding: "8px 10px 4px",
            }}
          >
            Settings
          </div>
          {SECTIONS.map((s) => {
            const active = s.id === section;
            return (
              <button type="button"
                key={s.id}
                onClick={() => setSection(s.id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "8px 10px",
                  border: "none",
                  borderRadius: 7,
                  cursor: "pointer",
                  fontSize: 13,
                  background: active ? "var(--accent-tint)" : "transparent",
                  color: active ? "var(--accent-text)" : "#a8a8b2",
                  borderLeft: `2px solid ${active ? "var(--accent-hex)" : "transparent"}`,
                  textAlign: "left",
                }}
              >
                <span style={{ flex: 1 }}>{s.label}</span>
              </button>
            );
          })}
        </aside>

        <main
          style={{
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            position: "relative",
            minWidth: 0,
            minHeight: 0,
          }}
        >
        <div
          style={{
            flex: 1,
            overflow: "auto",
            padding: "34px 28px 28px",
            position: "relative",
          }}
        >
          {banner && (
            <div
              style={{
                position: "absolute",
                top: 18,
                right: 58,
                padding: "8px 12px",
                borderRadius: 7,
                fontSize: 12,
                background:
                  banner.kind === "ok"
                    ? "rgba(74,222,128,0.1)"
                    : "var(--danger-tint)",
                color: banner.kind === "ok" ? "var(--ok-hex)" : "var(--danger-text)",
                border: `1px solid ${banner.kind === "ok" ? "rgba(74,222,128,0.3)" : "var(--danger-ring)"}`,
              }}
            >
              {banner.text}
            </div>
          )}
          {section === "appearance" && <AppearanceSection />}
          {section === "sources" && (
            <SourcesSection draft={draft} update={update} />
          )}
          {section === "capture" && (
            <CaptureSection draft={draft} update={update} />
          )}
          {section === "overlay" && (
            <OverlaySection draft={draft} update={update} />
          )}
          {section === "translate" && (
            <TranslateSection
              draft={draft}
              update={update}
              engine={engine}
              onInstallEngine={onInstallEngine}
            />
          )}
          {section === "matching" && (
            <MatchingSection draft={draft} update={update} />
          )}
          {section === "debug" && (
            <DebugSection draft={draft} update={update} />
          )}
        </div>

        <div
          style={{
            flexShrink: 0,
            padding: "14px 28px 20px",
            display: "flex",
            gap: 10,
            justifyContent: "space-between",
            alignItems: "center",
            background:
              "linear-gradient(to bottom, transparent, rgba(18,18,24,0.95) 30%)",
          }}
        >
          <button type="button"
            onClick={() => {
              setDraft(initialConfig);
              setDirty(false);
              setBanner(null);
            }}
            disabled={!dirty || saving}
            style={{
              padding: "10px 16px",
              borderRadius: 8,
              border: "1px solid rgba(255,255,255,0.1)",
              background: "transparent",
              color: "#a8a8b2",
              fontSize: 13,
              cursor: dirty ? "pointer" : "not-allowed",
              opacity: dirty ? 1 : 0.4,
            }}
          >
            Reset
          </button>
          <div style={{ display: "flex", gap: 10 }}>
            <button type="button"
              onClick={onClose}
              style={{
                padding: "10px 16px",
                borderRadius: 8,
                border: "1px solid rgba(255,255,255,0.08)",
                background: "transparent",
                color: "#a8a8b2",
                fontSize: 13,
                cursor: "pointer",
              }}
            >
              Close settings <Kbd dim>Esc</Kbd>
            </button>
            <button type="button"
              onClick={save}
              disabled={!dirty || saving}
              style={{
                padding: "10px 16px",
                borderRadius: 8,
                border: "none",
                background:
                  "linear-gradient(180deg, var(--accent-hex), var(--accent-deep))",
                color: "#1a0f08",
                fontSize: 13,
                fontWeight: 600,
                cursor: dirty ? "pointer" : "not-allowed",
                opacity: dirty ? 1 : 0.5,
              }}
            >
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </div>
      </main>
      </div>
    </div>
  );
}

function CloseIcon(): JSX.Element {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      aria-hidden
    >
      <path d="M6 6l12 12" />
      <path d="M18 6L6 18" />
    </svg>
  );
}

function Heading({
  eyebrow,
  title,
}: {
  eyebrow: string;
  title: string;
}): JSX.Element {
  return (
    <>
      <div
        style={{
          fontSize: 11,
          letterSpacing: 1.8,
          color: "var(--text-label)",
          fontWeight: 700,
          textTransform: "uppercase",
        }}
      >
        {eyebrow}
      </div>
      <h2
        style={{
          margin: "6px 0 22px",
          fontSize: 24,
          fontWeight: 500,
          letterSpacing: -0.4,
          color: "var(--text-heading)",
        }}
      >
        {title}
      </h2>
    </>
  );
}

function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: React.ReactNode;
  hint?: string;
}): JSX.Element {
  return (
    <div>
      <div
        style={{
          fontSize: 11,
          color: "var(--text-label)",
          letterSpacing: 0.4,
          textTransform: "uppercase",
          fontWeight: 700,
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      {children}
      {hint && (
        <div style={{ fontSize: 11, color: "var(--text-label)", marginTop: 4 }}>
          {hint}
        </div>
      )}
    </div>
  );
}

const inputStyle = {
  width: "100%",
  padding: "10px 12px",
  borderRadius: 8,
  background: "rgba(255,255,255,0.03)",
  border: "1px solid rgba(255,255,255,0.06)",
  color: "var(--text-heading)",
  fontSize: 13,
  fontFamily: "var(--font-mono)",
  outline: "none",
};

function TextInput({
  value,
  onChange,
  placeholder,
  type,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}): JSX.Element {
  return (
    <input
      type={type ?? "text"}
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      style={inputStyle}
    />
  );
}

function NumberInput({
  value,
  onChange,
  min,
  max,
  step,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
}): JSX.Element {
  return (
    <input
      type="number"
      value={Number.isFinite(value) ? value : 0}
      min={min}
      max={max}
      step={step}
      onChange={(e) => onChange(Number(e.target.value))}
      style={inputStyle}
    />
  );
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}): JSX.Element {
  return (
    <label
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        cursor: "pointer",
        padding: "8px 0",
      }}
    >
      <span
        style={{
          width: 34,
          height: 20,
          borderRadius: 10,
          background: checked ? "var(--accent-tint)" : "rgba(255,255,255,0.06)",
          border: `1px solid ${checked ? "var(--accent-ring)" : "rgba(255,255,255,0.08)"}`,
          position: "relative",
          transition: "background 0.2s",
        }}
      >
        <span
          style={{
            position: "absolute",
            top: 2,
            left: checked ? 16 : 2,
            width: 14,
            height: 14,
            borderRadius: 7,
            background: checked ? "var(--accent-hex)" : "#6a6a76",
            transition: "left 0.2s, background 0.2s",
          }}
        />
      </span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        style={{ display: "none" }}
      />
      <span style={{ fontSize: 13, color: "var(--text-body)" }}>{label}</span>
    </label>
  );
}

interface SectionProps {
  draft: BackendConfig;
  update: (patch: (c: BackendConfig) => BackendConfig) => void;
}

function SourcesSection({ draft, update }: SectionProps): JSX.Element {
  const os = draft.subtitleSources.opensubtitles;
  const sd = draft.subtitleSources.subdl;
  const as_ = draft.subtitleSources.assrt;
  const tmdb = draft.subtitleSources.tmdb;
  const setOs = (patch: Partial<typeof os>): void =>
    update((c) => ({
      ...c,
      subtitleSources: {
        ...c.subtitleSources,
        opensubtitles: { ...c.subtitleSources.opensubtitles, ...patch },
      },
    }));
  const setSubdl = (patch: Partial<typeof sd>): void =>
    update((c) => ({
      ...c,
      subtitleSources: {
        ...c.subtitleSources,
        subdl: { ...c.subtitleSources.subdl, ...patch },
      },
    }));
  const setTmdb = (patch: Partial<typeof tmdb>): void =>
    update((c) => ({
      ...c,
      subtitleSources: {
        ...c.subtitleSources,
        tmdb: { ...c.subtitleSources.tmdb, ...patch },
      },
    }));
  return (
    <>
      <Heading eyebrow="Subtitle sources" title="Where should we fetch subtitles?" />

      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <div className="glass-panel" style={{ padding: 18 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 10,
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-heading)" }}>
              OpenSubtitles
            </div>
            <Toggle
              checked={os.enabled}
              onChange={(v) => setOs({ enabled: v })}
              label={os.enabled ? "Enabled" : "Disabled"}
            />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            <Field label="API key">
              <TextInput
                value={os.apiKey}
                onChange={(v) => setOs({ apiKey: v })}
                type="password"
                placeholder="sk-xxx"
              />
            </Field>
            <Field label="Username">
              <TextInput
                value={os.username}
                onChange={(v) => setOs({ username: v })}
              />
            </Field>
            <Field label="Password">
              <TextInput
                value={os.password}
                onChange={(v) => setOs({ password: v })}
                type="password"
              />
            </Field>
            <Field label="Org fallback" hint="Use org endpoint if primary fails">
              <Toggle
                checked={os.enableOrgFallback}
                onChange={(v) => setOs({ enableOrgFallback: v })}
                label={os.enableOrgFallback ? "On" : "Off"}
              />
            </Field>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: 18 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-heading)" }}>
              SubDL
            </div>
            <Toggle
              checked={sd.enabled}
              onChange={(v) => setSubdl({ enabled: v })}
              label={sd.enabled ? "Enabled" : "Disabled"}
            />
          </div>
          <div style={{ marginTop: 12 }}>
            <Field label="API key">
              <TextInput
                value={sd.apiKey}
                onChange={(v) => setSubdl({ apiKey: v })}
                type="password"
                placeholder="SubDL API key"
              />
            </Field>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: 18 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 10,
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-heading)" }}>
              ASSRT
            </div>
            <Toggle
              checked={as_.enabled}
              onChange={(v) =>
                update((c) => ({
                  ...c,
                  subtitleSources: {
                    ...c.subtitleSources,
                    assrt: { ...c.subtitleSources.assrt, enabled: v },
                  },
                }))
              }
              label={as_.enabled ? "Enabled" : "Disabled"}
            />
          </div>
          <Field label="Token">
            <TextInput
              value={as_.token}
              onChange={(v) =>
                update((c) => ({
                  ...c,
                  subtitleSources: {
                    ...c.subtitleSources,
                    assrt: { ...c.subtitleSources.assrt, token: v },
                  },
                }))
              }
              type="password"
            />
          </Field>
        </div>

        <div className="glass-panel" style={{ padding: 18 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 10,
            }}
          >
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-heading)" }}>
                TMDb cross-lingual merge
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                Collapses same show across languages (e.g. オーバーロード + Overlord) via TMDb IDs.
              </div>
            </div>
            <Toggle
              checked={tmdb.mergeEnabled}
              onChange={(v) => setTmdb({ mergeEnabled: v })}
              label={tmdb.mergeEnabled ? "On" : "Off"}
            />
          </div>
          <Field
            label="TMDb API key"
            hint="Free at themoviedb.org → Settings → API. v3 auth. Leave blank to disable."
          >
            <TextInput
              value={tmdb.apiKey}
              onChange={(v) => setTmdb({ apiKey: v })}
              type="password"
              placeholder="tmdb-v3-key"
            />
          </Field>
        </div>
      </div>
    </>
  );
}

function CaptureSection({ draft, update }: SectionProps): JSX.Element {
  const c = draft.capture;
  const [x, y, w, h] = c.region;
  return (
    <>
      <Heading eyebrow="Capture" title="Where should Meowcal watch?" />

      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>
          Capture region
        </div>
        <div
          style={{
            position: "relative",
            height: 180,
            borderRadius: 10,
            background: "linear-gradient(180deg, #0f0f14, #060608)",
            border: "1px solid rgba(255,255,255,0.06)",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              position: "absolute",
              top: 30,
              left: 20,
              right: 20,
              bottom: 20,
              border: "1.5px dashed var(--accent-hex)",
              borderRadius: 4,
              background: "var(--accent-tint)",
            }}
          />
          <div
            style={{
              position: "absolute",
              bottom: 28,
              left: "50%",
              transform: "translateX(-50%)",
              padding: "6px 14px",
              background: "rgba(0,0,0,0.6)",
              borderRadius: 6,
              fontSize: 13,
              color: "#fff",
              fontWeight: 500,
            }}
          >
            Subtitle zone
          </div>
          <div
            className="mono"
            style={{
              position: "absolute",
              top: 8,
              right: 10,
              fontSize: 10,
              color: "var(--accent-text)",
            }}
          >
            {x}, {y} · {w} × {h}
          </div>
        </div>
        <button type="button"
          onClick={() => {
            void tauri.openAreaSelector();
          }}
          style={{
            marginTop: 10,
            padding: "8px 14px",
            borderRadius: 7,
            background: "rgba(255,255,255,0.04)",
            border: "1px solid rgba(255,255,255,0.08)",
            color: "var(--text-body)",
            fontSize: 12,
            cursor: "pointer",
            display: "inline-flex",
            gap: 8,
            alignItems: "center",
          }}
        >
          Select new region <Kbd>C</Kbd>
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
        <Field label="Interval (ms)" hint="Lower = more CPU">
          <NumberInput
            value={c.intervalMs}
            onChange={(v) =>
              update((cfg) => ({
                ...cfg,
                capture: { ...cfg.capture, intervalMs: v },
              }))
            }
            min={100}
            step={50}
          />
        </Field>
        <Field label="OCR language" hint="Usually mirrors source language">
          <TextInput
            value={c.ocrLanguage}
            onChange={(v) =>
              update((cfg) => ({
                ...cfg,
                capture: { ...cfg.capture, ocrLanguage: v },
              }))
            }
            placeholder="en-US"
          />
        </Field>
      </div>

      <div style={{ marginTop: 18 }}>
        <Field label="Languages (source → target)">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <TextInput
              value={draft.languages.source}
              onChange={(v) =>
                update((cfg) => ({
                  ...cfg,
                  languages: { ...cfg.languages, source: v },
                }))
              }
              placeholder="en"
            />
            <TextInput
              value={draft.languages.target}
              onChange={(v) =>
                update((cfg) => ({
                  ...cfg,
                  languages: { ...cfg.languages, target: v },
                }))
              }
              placeholder="zh-TW"
            />
          </div>
        </Field>
      </div>
    </>
  );
}

function OverlaySection({ draft, update }: SectionProps): JSX.Element {
  const overlay = draft.overlay as Record<string, unknown>;
  const entries = Object.entries(overlay).filter(
    ([k]) => k !== "port" && !k.startsWith("_"),
  );
  return (
    <>
      <Heading eyebrow="Overlay" title="How should subtitles look?" />
      <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: -14, marginBottom: 18 }}>
        In live mode the main window becomes the subtitle surface. These values
        tune font, color, blur, animation, and position.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
        <Field label="Overlay port" hint="Read-only; restart to change">
          <TextInput
            value={String(overlay.port ?? "8765")}
            onChange={() => {}}
          />
        </Field>
        {entries.map(([key, value]) => (
          <Field key={key} label={key}>
            <TextInput
              value={String(value ?? "")}
              onChange={(v) =>
                update((cfg) => ({
                  ...cfg,
                  overlay: { ...(cfg.overlay as Record<string, unknown>), [key]: coerce(value, v) },
                }))
              }
            />
          </Field>
        ))}
      </div>
    </>
  );
}

function coerce(original: unknown, next: string): unknown {
  if (typeof original === "number") {
    const n = Number(next);
    return Number.isFinite(n) ? n : original;
  }
  if (typeof original === "boolean") {
    return next === "true";
  }
  return next;
}

interface TranslateSectionProps extends SectionProps {
  engine: EngineStatus | null;
  onInstallEngine: () => void;
}

function TranslateSection({
  draft,
  update,
  engine,
  onInstallEngine,
}: TranslateSectionProps): JSX.Element {
  const t = draft.translation;
  const installing = engine?.phase === "installing";
  return (
    <>
      <Heading eyebrow="Translation" title="On-device translation" />
      <p style={{ margin: "0 0 18px", fontSize: 13, color: "var(--text-muted)", lineHeight: 1.6 }}>
        Subtitles are translated on this machine by {engine?.model || "a local model"}.
        Nothing captured from your screen leaves the device.
      </p>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          padding: "14px 16px",
          borderRadius: 12,
          background: "var(--surface-2)",
          border: "1px solid var(--border-soft)",
          marginBottom: 18,
        }}
      >
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{engine?.message ?? "Checking..."}</div>
          {installing && (
            <div style={{ marginTop: 8, height: 4, borderRadius: 2, background: "var(--border-soft)" }}>
              <div
                style={{
                  width: `${engine?.installPercent ?? 0}%`,
                  height: "100%",
                  borderRadius: 2,
                  background: "var(--accent)",
                  transition: "width 400ms ease",
                }}
              />
            </div>
          )}
        </div>
        {engine?.phase === "needsSetup" || engine?.phase === "failed" ? (
          <button type="button" className="settings-primary" onClick={onInstallEngine}>
            {engine.phase === "failed" ? "Retry download" : "Download engine"}
          </button>
        ) : null}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
        <Field label="Timeout (s)" hint="How long one line may take before it is dropped">
          <NumberInput
            value={t.timeoutS}
            onChange={(v) =>
              update((c) => ({ ...c, translation: { ...c.translation, timeoutS: v } }))
            }
            min={1}
          />
        </Field>
      </div>
    </>
  );
}

function MatchingSection({ draft, update }: SectionProps): JSX.Element {
  const m = draft.matching;
  return (
    <>
      <Heading eyebrow="Matching" title="How strict should OCR matching be?" />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
        <Field label="Fuzzy threshold" hint="0 – 100. Higher = stricter (default 65)">
          <NumberInput
            value={m.fuzzyThreshold}
            onChange={(v) =>
              update((c) => ({
                ...c,
                matching: { ...c.matching, fuzzyThreshold: Math.round(v) },
              }))
            }
            min={0}
            max={100}
            step={1}
          />
        </Field>
        <Field label="Window size" hint="Lookback for matching (lines)">
          <NumberInput
            value={m.windowSize}
            onChange={(v) =>
              update((c) => ({
                ...c,
                matching: { ...c.matching, windowSize: Math.round(v) },
              }))
            }
            min={1}
          />
        </Field>
      </div>
    </>
  );
}

function DebugSection({ draft, update }: SectionProps): JSX.Element {
  return (
    <>
      <Heading eyebrow="Debug" title="Developer options" />
      <Toggle
        checked={draft.debug.mode}
        onChange={(v) =>
          update((c) => ({ ...c, debug: { ...c.debug, mode: v } }))
        }
        label="Enable debug overlay (OCR timing + match visualiser)"
      />
    </>
  );
}

function AppearanceSection(): JSX.Element {
  const [active, setActive] = useState<FontPresetName>(() => loadFontScale());
  const presets = Object.keys(FONT_PRESETS) as FontPresetName[];
  const onPick = (name: FontPresetName): void => {
    setFontScale(name);
    setActive(name);
  };
  return (
    <>
      <Heading eyebrow="Appearance" title="Interface size" />
      <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: -12, marginBottom: 18 }}>
        Scale the entire app interface. Applies instantly and persists across launches.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {presets.map((name) => {
          const selected = active === name;
          const pct = Math.round(FONT_PRESETS[name] * 100);
          return (
            <button type="button"
              key={name}
              onClick={() => onPick(name)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 14,
                padding: "12px 16px",
                background: selected ? "var(--accent-tint)" : "rgba(255,255,255,0.02)",
                border: `1px solid ${selected ? "var(--accent-ring)" : "rgba(255,255,255,0.06)"}`,
                borderRadius: 9,
                cursor: "pointer",
                textAlign: "left",
                color: selected ? "var(--accent-text)" : "var(--text-body)",
                transition: "background 160ms ease, border-color 160ms ease",
              }}
            >
              <div
                aria-hidden
                style={{
                  width: 20,
                  height: 20,
                  borderRadius: "50%",
                  border: `2px solid ${selected ? "var(--accent-hex)" : "rgba(255,255,255,0.18)"}`,
                  background: selected ? "var(--accent-hex)" : "transparent",
                  flexShrink: 0,
                  boxShadow: selected ? "inset 0 0 0 3px #1a0f08" : "none",
                  transition: "all 160ms ease",
                }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 15, fontWeight: 500 }}>
                  {presetLabel(name)}
                  {name === "default" && (
                    <span
                      style={{
                        fontSize: 10,
                        marginLeft: 8,
                        padding: "2px 6px",
                        borderRadius: 999,
                        background: "rgba(255,255,255,0.06)",
                        color: "var(--text-label)",
                        textTransform: "uppercase",
                        letterSpacing: 1,
                        fontWeight: 600,
                      }}
                    >
                      Recommended
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 12, color: "var(--text-label)", marginTop: 2 }}>
                  Interface scale {pct}%
                </div>
              </div>
              <div
                aria-hidden
                style={{
                  fontFamily: "var(--font-display)",
                  fontStyle: "italic",
                  fontSize: 22 * FONT_PRESETS[name],
                  color: selected ? "var(--accent-text)" : "var(--text-muted)",
                  opacity: 0.85,
                }}
              >
                Aa
              </div>
            </button>
          );
        })}
      </div>
    </>
  );
}
