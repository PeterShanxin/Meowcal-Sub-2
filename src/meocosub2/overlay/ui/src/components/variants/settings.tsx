import { useEffect, useState } from "react";
import type { BackendConfig } from "../../lib/types";
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

export function SettingsView({
  initialConfig,
  onClose,
}: {
  initialConfig: BackendConfig;
  onClose: () => void;
}): JSX.Element {
  const [section, setSection] = useState<SectionId>("sources");
  const [draft, setDraft] = useState<BackendConfig>(initialConfig);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [banner, setBanner] = useState<{
    kind: "ok" | "error";
    text: string;
  } | null>(null);

  useEffect(() => {
    setDraft(initialConfig);
    setDirty(false);
  }, [initialConfig]);

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
      style={{
        position: "absolute",
        top: 70,
        left: 20,
        right: 20,
        bottom: 20,
        display: "grid",
        gridTemplateColumns: "220px 1fr",
        gap: 16,
      }}
    >
      <aside
        className="glass-panel"
        style={{
          padding: 12,
          display: "flex",
          flexDirection: "column",
          gap: 2,
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
            <button
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
        className="glass-panel"
        style={{
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          position: "relative",
        }}
      >
        <div style={{ flex: 1, overflow: "auto", padding: 28, position: "relative" }}>
          {banner && (
            <div
              style={{
                position: "absolute",
                top: 16,
                right: 16,
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
            <TranslateSection draft={draft} update={update} />
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
          <button
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
            <button
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
            <button
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
              onChange={(v) =>
                update((c) => ({
                  ...c,
                  subtitleSources: {
                    ...c.subtitleSources,
                    subdl: { enabled: v },
                  },
                }))
              }
              label={sd.enabled ? "Enabled" : "Disabled"}
            />
          </div>
          <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 6 }}>
            No API key required.
          </p>
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
        <button
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
            value={String(overlay.port ?? draft.translation.endpoint ?? "8765")}
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

function TranslateSection({ draft, update }: SectionProps): JSX.Element {
  const t = draft.translation;
  return (
    <>
      <Heading eyebrow="Translation" title="Foundry Local translation backend" />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
        <Field label="Endpoint" hint="Foundry Local base URL">
          <TextInput
            value={t.endpoint}
            onChange={(v) =>
              update((c) => ({ ...c, translation: { ...c.translation, endpoint: v } }))
            }
            placeholder="http://localhost:5273"
          />
        </Field>
        <Field label="Model">
          <TextInput
            value={t.model}
            onChange={(v) =>
              update((c) => ({ ...c, translation: { ...c.translation, model: v } }))
            }
          />
        </Field>
        <Field label="Timeout (s)">
          <NumberInput
            value={t.timeoutS}
            onChange={(v) =>
              update((c) => ({ ...c, translation: { ...c.translation, timeoutS: v } }))
            }
            min={1}
          />
        </Field>
        <Field label="Batch size" hint="Lines per translation call">
          <NumberInput
            value={t.batchSize}
            onChange={(v) =>
              update((c) => ({ ...c, translation: { ...c.translation, batchSize: v } }))
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
            <button
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
