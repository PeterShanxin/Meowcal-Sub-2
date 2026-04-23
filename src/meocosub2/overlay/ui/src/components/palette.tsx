import { forwardRef, useEffect, useRef, useState } from "react";
import type { CSSProperties, RefObject } from "react";
import type {
  CommandItem,
  LanguageOption,
  PaletteTabId,
  Phase,
  SourceItem,
  TargetItem,
  TitleItem,
} from "../lib/types";
import { CatMascot, Kbd, PaletteTabs } from "./primitives";

interface PaletteProps {
  phase: Phase;
  compact: boolean;
  query: string;
  onQueryChange: (v: string) => void;
  tab: PaletteTabId;
  onTabChange: (v: PaletteTabId) => void;
  titles: TitleItem[];
  sources: SourceItem[];
  targets: TargetItem[];
  commands: CommandItem[];
  selectedTitleId: string | null;
  selectedSourceId: string | null;
  selectedTargetId: string | null;
  cursorIndex: number;
  onPickTitle: (id: string) => void;
  onPickSource: (id: string) => void;
  onPickTarget: (id: string) => void;
  onCommand: (id: string) => void;
  onPrimary: () => void;
  inputRef: RefObject<HTMLInputElement>;
  sourceLang: string;
  targetLang: string;
  searching: boolean;
  langOptions: LanguageOption[];
  onChangeLang: (type: "source" | "target", code: string) => void;
}

export function Palette(props: PaletteProps): JSX.Element {
  const {
    phase,
    compact,
    query,
    onQueryChange,
    tab,
    onTabChange,
    titles,
    sources,
    targets,
    commands,
    selectedTitleId,
    selectedSourceId,
    selectedTargetId,
    cursorIndex,
    onPickTitle,
    onPickSource,
    onPickTarget,
    onCommand,
    onPrimary,
    inputRef,
    sourceLang,
    targetLang,
    searching,
    langOptions,
    onChangeLang,
  } = props;

  const [openDrop, setOpenDrop] = useState<"source" | "target" | null>(null);
  const langRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!openDrop) return;
    const close = (e: MouseEvent) => {
      if (langRef.current && !langRef.current.contains(e.target as Node)) {
        setOpenDrop(null);
      }
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [openDrop]);

  const tabs = [
    { id: "titles", label: "Titles", count: titles.length },
    { id: "source", label: "Source", count: selectedTitleId ? sources.length : 0 },
    { id: "target", label: "Target", count: selectedTitleId ? targets.length : 0 },
    { id: "cmd", label: "Commands", count: commands.length },
  ];

  const placeholder =
    tab === "cmd"
      ? "Type a command…"
      : tab === "source"
        ? "Filter source subtitles…"
        : tab === "target"
          ? "Filter target subtitles…"
          : "Search for a title…";

  const canStart = phase === "prep";
  const canPrepare =
    selectedTitleId && selectedSourceId && selectedTargetId && phase !== "prep";
  const primaryLabel = canStart
    ? "Start sync"
    : canPrepare
      ? "Prepare session"
      : null;

  return (
    <div
      className="glass-panel"
      style={{
        borderRadius: compact ? 12 : 16,
        overflow: "hidden",
        boxShadow: compact
          ? "0 8px 28px rgba(0,0,0,0.35)"
          : "0 32px 80px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.03) inset",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: compact ? "12px 16px" : "18px 20px",
          borderBottom: "1px solid rgba(255,255,255,0.05)",
        }}
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#8a8a96" strokeWidth="1.5" aria-hidden>
          <circle cx="7" cy="7" r="5" />
          <path d="M11 11l3.5 3.5" />
        </svg>
        <input
          ref={inputRef}
          autoFocus
          data-palette="true"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder={placeholder}
          style={{
            flex: 1,
            border: "none",
            background: "transparent",
            outline: "none",
            fontSize: compact ? 15 : 18,
            color: "var(--text-heading)",
            padding: 0,
            fontWeight: 400,
          }}
        />
        <div ref={langRef} style={{ position: "relative", display: "flex", gap: 6, alignItems: "center" }}>
          <span
            onClick={() => setOpenDrop(openDrop === "source" ? null : "source")}
            style={{
              padding: "4px 8px",
              background: openDrop === "source" ? "rgba(255,255,255,0.08)" : "rgba(255,255,255,0.04)",
              borderRadius: 5,
              fontSize: 11,
              color: "#a8a8b2",
              border: "1px solid rgba(255,255,255,0.06)",
              textTransform: "uppercase",
              cursor: "pointer",
              userSelect: "none",
            }}
          >
            {sourceLang}
          </span>
          <svg width="12" height="10" viewBox="0 0 12 10" fill="none" stroke="#6a6a76" strokeWidth="1.3" aria-hidden>
            <path d="M1 5h8M7 1l4 4-4 4" />
          </svg>
          <span
            onClick={() => setOpenDrop(openDrop === "target" ? null : "target")}
            style={{
              padding: "4px 8px",
              background: openDrop === "target" ? "var(--accent-hex)" : "var(--accent-tint)",
              color: "var(--accent-text)",
              borderRadius: 5,
              fontSize: 11,
              border: "1px solid var(--accent-ring)",
              cursor: "pointer",
              userSelect: "none",
            }}
          >
            {targetLang}
          </span>
          {openDrop && langOptions.length > 0 && (
            <div
              style={{
                position: "absolute",
                top: "calc(100% + 6px)",
                right: 0,
                minWidth: 180,
                background: "#1a1a24",
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: 8,
                boxShadow: "0 12px 32px rgba(0,0,0,0.5)",
                zIndex: 100,
                overflow: "hidden",
              }}
            >
              <div style={{ padding: "6px 10px 4px", fontSize: 10, color: "var(--text-label)", textTransform: "uppercase", letterSpacing: 1 }}>
                {openDrop === "source" ? "Source language" : "Target language"}
              </div>
              {langOptions.map((opt) => {
                const active = openDrop === "source"
                  ? opt.code.toLowerCase() === sourceLang.toLowerCase()
                  : opt.code.toLowerCase() === targetLang.toLowerCase();
                return (
                  <div
                    key={opt.code}
                    onClick={() => { onChangeLang(openDrop, opt.code); setOpenDrop(null); }}
                    style={{
                      padding: "8px 12px",
                      fontSize: 13,
                      color: active ? "var(--accent-text)" : "var(--text-body)",
                      background: active ? "var(--accent-tint)" : "transparent",
                      cursor: "pointer",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      gap: 8,
                    }}
                    onMouseEnter={(e) => { if (!active) (e.currentTarget as HTMLDivElement).style.background = "rgba(255,255,255,0.04)"; }}
                    onMouseLeave={(e) => { if (!active) (e.currentTarget as HTMLDivElement).style.background = "transparent"; }}
                  >
                    <span>{opt.label}</span>
                    <span style={{ fontSize: 10, color: "var(--text-label)", textTransform: "uppercase" }}>{opt.code}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <PaletteTabs
        tabs={tabs}
        active={tab}
        onChange={(id) => onTabChange(id as PaletteTabId)}
      />

      <div style={{ maxHeight: compact ? 240 : 360, overflow: "auto" }}>
        {tab === "titles" && (
          <TitleList
            items={filterTitles(titles, query)}
            selectedId={selectedTitleId}
            cursorIndex={cursorIndex}
            onPick={onPickTitle}
            searching={searching}
          />
        )}
        {tab === "source" && (
          selectedTitleId ? (
            <SubList
              items={filterSources(sources, query)}
              selectedId={selectedSourceId}
              cursorIndex={cursorIndex}
              onPick={onPickSource}
            />
          ) : (
            <EmptyTab hint="Pick a title first" />
          )
        )}
        {tab === "target" && (
          selectedTitleId ? (
            <TargetList
              items={filterTargets(targets, query)}
              selectedId={selectedTargetId}
              cursorIndex={cursorIndex}
              onPick={onPickTarget}
            />
          ) : (
            <EmptyTab hint="Pick a title first" />
          )
        )}
        {tab === "cmd" && (
          <CmdList
            items={commands}
            cursorIndex={cursorIndex}
            onPick={onCommand}
          />
        )}
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "10px 16px",
          borderTop: "1px solid rgba(255,255,255,0.05)",
          fontSize: 11,
          color: "var(--text-label)",
        }}
      >
        <Kbd dim>↑↓</Kbd>
        <span>Navigate</span>
        <Kbd dim>↵</Kbd>
        <span>Select</span>
        <div style={{ flex: 1 }} />
        {primaryLabel ? (
          <button onClick={onPrimary} style={primaryStyle}>
            {primaryLabel}
            <Kbd>⌘↵</Kbd>
          </button>
        ) : (
          <span>
            {!selectedTitleId
              ? "Pick a title to continue"
              : !selectedSourceId
                ? "Pick a source subtitle"
                : "Pick a target (or use local translation)"}
          </span>
        )}
      </div>
    </div>
  );
}

const primaryStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "6px 14px",
  background: "linear-gradient(180deg, var(--accent-hex), var(--accent-deep))",
  color: "#1a0f08",
  border: "none",
  borderRadius: 7,
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
};

function filterTitles(items: TitleItem[], q: string): TitleItem[] {
  void q;
  return items;
}

function filterSources(items: SourceItem[], q: string): SourceItem[] {
  void q;
  return items;
}

function filterTargets(items: TargetItem[], q: string): TargetItem[] {
  void q;
  return items;
}

function TitleList({
  items,
  selectedId,
  cursorIndex,
  onPick,
  searching,
}: {
  items: TitleItem[];
  selectedId: string | null;
  cursorIndex: number;
  onPick: (id: string) => void;
  searching: boolean;
}): JSX.Element {
  if (items.length === 0) {
    return (
      <EmptyTab
        hint={searching ? "Searching…" : "Type a title and press ↵ to search"}
      />
    );
  }
  return (
    <div style={{ padding: "6px 0" }}>
      {items.map((t, i) => {
        const sel = selectedId === t.id;
        const focused = cursorIndex === i;
        return (
          <Row
            key={t.id}
            selected={sel}
            focused={focused}
            onClick={() => onPick(t.id)}
          >
            <div
              style={{
                width: 28,
                height: 40,
                borderRadius: 4,
                flexShrink: 0,
                background: "linear-gradient(135deg, #3a2a1a, #1a0f08)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 13,
              }}
            >
              {t.type.startsWith("Movie") ? "🎬" : "📺"}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 14, color: "var(--text-heading)", fontWeight: 500 }}>
                {t.title}
              </div>
              <div style={{ fontSize: 11, color: "var(--text-label)", marginTop: 2 }}>
                {t.year} · {t.type} · {t.runtime}
              </div>
            </div>
            {focused && <Kbd>↵</Kbd>}
          </Row>
        );
      })}
    </div>
  );
}

function SubList({
  items,
  selectedId,
  cursorIndex,
  onPick,
}: {
  items: SourceItem[];
  selectedId: string | null;
  cursorIndex: number;
  onPick: (id: string) => void;
}): JSX.Element {
  if (items.length === 0) return <EmptyTab hint="No subtitles for this title" />;
  return (
    <div style={{ padding: "6px 0" }}>
      {items.map((r, i) => {
        const sel = selectedId === r.id;
        const focused = cursorIndex === i;
        return (
          <Row
            key={r.id}
            selected={sel}
            focused={focused}
            onClick={() => onPick(r.id)}
          >
            <div
              style={{
                width: 22,
                display: "flex",
                justifyContent: "center",
                color: "var(--text-label)",
              }}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
                <rect x="2" y="2" width="12" height="12" rx="1" />
                <path d="M4 7h8M4 9h8M4 11h4" />
              </svg>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                className="mono"
                style={{
                  fontSize: 13,
                  color: "var(--text-body)",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {r.file}
              </div>
              <div style={{ fontSize: 11, color: "var(--text-label)", marginTop: 2 }}>
                {r.provider} · {r.downloads} downloads · {r.fps} fps
                {r.trusted && (
                  <span style={{ color: "var(--accent-text)", marginLeft: 8 }}>
                    ✓ Trusted
                  </span>
                )}
                {r.hi && <span style={{ marginLeft: 8 }}>HI</span>}
              </div>
            </div>
            {focused && <Kbd>↵</Kbd>}
          </Row>
        );
      })}
    </div>
  );
}

function TargetList({
  items,
  selectedId,
  cursorIndex,
  onPick,
}: {
  items: TargetItem[];
  selectedId: string | null;
  cursorIndex: number;
  onPick: (id: string) => void;
}): JSX.Element {
  if (items.length === 0) return <EmptyTab hint="No targets available" />;
  return (
    <div style={{ padding: "6px 0" }}>
      {items.map((r, i) => {
        const sel = selectedId === r.id;
        const focused = cursorIndex === i;
        const isSpecial = r.kind === "local" || r.kind === "ocr";
        return (
          <Row
            key={r.id}
            selected={sel}
            focused={focused}
            onClick={() => onPick(r.id)}
          >
            <div
              style={{
                width: 22,
                display: "flex",
                justifyContent: "center",
                color: isSpecial ? "var(--accent-hex)" : "var(--text-label)",
              }}
            >
              {r.kind === "local" ? (
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
                  <path d="M2 8a6 6 0 1 1 12 0A6 6 0 0 1 2 8z" />
                  <path d="M8 4v4l2.5 2.5" />
                </svg>
              ) : r.kind === "ocr" ? (
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
                  <path d="M2 4V2h2M12 2h2v2M2 12v2h2M12 14h2v-2" />
                  <path d="M5 8h6" />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
                  <rect x="2" y="2" width="12" height="12" rx="1" />
                  <path d="M4 7h8M4 9h8M4 11h4" />
                </svg>
              )}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                className={isSpecial ? "" : "mono"}
                style={{
                  fontSize: 13,
                  color: "var(--text-body)",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  fontWeight: isSpecial ? 500 : 400,
                }}
              >
                {r.title ?? r.file}
              </div>
              <div style={{ fontSize: 11, color: "var(--text-label)", marginTop: 2 }}>
                {r.note ?? `${r.provider} · ${r.downloads} downloads · ${r.fps} fps`}
              </div>
            </div>
            {r.kind === "local" && (
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
                AUTO
              </span>
            )}
            {focused && <Kbd>↵</Kbd>}
          </Row>
        );
      })}
    </div>
  );
}

function CmdList({
  items,
  cursorIndex,
  onPick,
}: {
  items: CommandItem[];
  cursorIndex: number;
  onPick: (id: string) => void;
}): JSX.Element {
  return (
    <div style={{ padding: "6px 0" }}>
      {items.map((c, i) => {
        const isPrimary = c.kind === "primary";
        const disabled = !!c.disabled;
        const focused = cursorIndex === i;
        return (
          <div
            key={c.id}
            onClick={() => {
              if (!disabled) onPick(c.id);
            }}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 14,
              padding: "10px 20px",
              opacity: disabled ? 0.4 : 1,
              cursor: disabled ? "not-allowed" : "pointer",
              background: focused ? "var(--accent-tint)" : "transparent",
              borderLeft: `2px solid ${focused ? "var(--accent-hex)" : "transparent"}`,
            }}
          >
            <div
              style={{
                width: 28,
                height: 28,
                borderRadius: 7,
                flexShrink: 0,
                background: isPrimary ? "var(--accent-tint)" : "rgba(255,255,255,0.04)",
                color: isPrimary ? "var(--accent-text)" : "#a8a8b2",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 13,
                border: `1px solid ${isPrimary ? "var(--accent-ring)" : "rgba(255,255,255,0.05)"}`,
              }}
            >
              {c.icon}
            </div>
            <span style={{ flex: 1, fontSize: 13, color: "var(--text-body)" }}>
              {c.label}
            </span>
            <Kbd>{c.shortcut}</Kbd>
          </div>
        );
      })}
    </div>
  );
}

interface RowProps {
  selected: boolean;
  focused: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

const Row = forwardRef<HTMLDivElement, RowProps>(function Row(
  { selected, focused, onClick, children },
  ref,
) {
  return (
    <div
      ref={ref}
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "10px 20px",
        background: focused
          ? "var(--accent-tint)"
          : selected
            ? "rgba(255,185,90,0.05)"
            : "transparent",
        borderLeft: `2px solid ${focused || selected ? "var(--accent-hex)" : "transparent"}`,
        cursor: "pointer",
      }}
    >
      {children}
    </div>
  );
});

function EmptyTab({ hint }: { hint: string }): JSX.Element {
  return (
    <div
      style={{
        padding: "32px 20px",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 10,
        color: "var(--text-label)",
      }}
    >
      <CatMascot size={44} expression="sleepy" />
      <span style={{ fontSize: 12 }}>{hint}</span>
    </div>
  );
}
