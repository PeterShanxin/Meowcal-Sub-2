import { forwardRef, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, RefObject } from "react";
import type {
  CommandItem,
  LanguageOption,
  PaletteTabId,
  Phase,
  SourceItem,
  TargetItem,
  TitleMediaFilter,
  WorkItem,
  WorkSeasonItem,
} from "../lib/types";
import { DisclosureChevron, InfoChipRow, Kbd, PaletteTabs } from "./primitives";

interface PaletteProps {
  phase: Phase;
  compact: boolean;
  query: string;
  onQueryChange: (v: string) => void;
  tab: PaletteTabId;
  onTabChange: (v: PaletteTabId) => void;
  works: WorkItem[];
  totalWorksCount: number;
  titleMediaFilter: TitleMediaFilter;
  selectedSeasonFilters: number[];
  availableSeasonNumbers: number[];
  onTitleMediaFilterChange: (v: TitleMediaFilter) => void;
  onToggleSeasonFilter: (seasonNumber: number) => void;
  onClearSeasonFilters: () => void;
  sources: SourceItem[];
  targets: TargetItem[];
  commands: CommandItem[];
  selectedWorkId: string | null;
  expandedWorkId: string | null;
  expandedSeasonNumber: number | null;
  selectedEpisodeMatchId: string | null;
  selectedSourceId: string | null;
  selectedTargetId: string | null;
  cursorIndex: number;
  onToggleExpandWork: (id: string) => void;
  onToggleExpandSeason: (workId: string, seasonNumber: number) => void;
  onPickWork: (id: string) => void;
  onPickEpisode: (workId: string, matchId: string) => void;
  onHydrateEpisode: (workId: string, season: number, episode: number) => void;
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
    works,
    totalWorksCount,
    titleMediaFilter,
    selectedSeasonFilters,
    availableSeasonNumbers,
    onTitleMediaFilterChange,
    onToggleSeasonFilter,
    onClearSeasonFilters,
    sources,
    targets,
    commands,
    selectedWorkId,
    expandedWorkId,
    expandedSeasonNumber,
    selectedEpisodeMatchId,
    selectedSourceId,
    selectedTargetId,
    cursorIndex,
    onToggleExpandWork,
    onToggleExpandSeason,
    onPickWork,
    onPickEpisode,
    onHydrateEpisode,
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
  const [focused, setFocused] = useState(false);
  const langRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const titleResultsKey = useMemo(
    () => works.map((w) => `${w.id}:${w.title}:${w.totalSubtitles}:${w.posterUrl ?? ""}`).join("|"),
    [works],
  );

  useEffect(() => {
    const container = listRef.current;
    if (!container || cursorIndex < 0) return;
    const target = container.querySelector(
      `[data-cursor-row="${cursorIndex}"]`,
    ) as HTMLElement | null;
    if (!target) return;
    const cTop = container.scrollTop;
    const cBottom = cTop + container.clientHeight;
    const tTop = target.offsetTop;
    const tBottom = tTop + target.offsetHeight;
    if (tTop < cTop) container.scrollTop = tTop;
    else if (tBottom > cBottom) container.scrollTop = tBottom - container.clientHeight;
  }, [cursorIndex, tab]);

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

  useEffect(() => {
    if (phase !== "home" && phase !== "prep") return;
    const inp = inputRef.current;
    if (!inp) return;
    const focusNow = () => {
      try {
        window.focus();
      } catch {
        // ignore cross-origin/webview restrictions
      }
      inp.focus();
      inp.select();
    };
    focusNow();
    const delays = [50, 150, 400, 900];
    const timers = delays.map((d) => window.setTimeout(focusNow, d));
    window.addEventListener("focus", focusNow);
    document.addEventListener("visibilitychange", focusNow);
    return () => {
      timers.forEach((t) => window.clearTimeout(t));
      window.removeEventListener("focus", focusNow);
      document.removeEventListener("visibilitychange", focusNow);
    };
  }, [inputRef, phase]);

  const hasSelectedEpisode = !!selectedEpisodeMatchId;
  const tabs = [
    { id: "titles", label: "Titles", count: works.length },
    { id: "source", label: "Source", count: hasSelectedEpisode ? sources.length : 0 },
    { id: "target", label: "Target", count: hasSelectedEpisode ? targets.length : 0 },
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
    hasSelectedEpisode && phase !== "prep";
  const primaryLabel = canStart
    ? "Start sync"
    : canPrepare
      ? "Prepare automatically"
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
          position: "relative",
          display: "flex",
          alignItems: "center",
          gap: 14,
          padding: compact ? "14px 18px" : "22px 24px",
          borderBottom: `1px solid ${focused ? "var(--accent-ring)" : "rgba(255,255,255,0.05)"}`,
          background: focused
            ? "linear-gradient(180deg, rgba(255,185,90,0.04), rgba(255,185,90,0) 70%)"
            : "transparent",
          boxShadow: focused ? "inset 0 -1px 0 0 var(--accent-hex)" : "none",
          transition: "border-color 220ms ease, box-shadow 220ms ease, background 220ms ease",
        }}
      >
        <svg
          width="20"
          height="20"
          viewBox="0 0 16 16"
          fill="none"
          stroke={focused ? "var(--accent-hex)" : "#8a8a96"}
          strokeWidth="1.5"
          aria-hidden
          style={{ transition: "stroke 220ms ease", flexShrink: 0 }}
        >
          <circle cx="7" cy="7" r="5" />
          <path d="M11 11l3.5 3.5" />
        </svg>
        <input
          ref={inputRef}
          autoFocus
          data-palette="true"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onFocus={(e) => {
            setFocused(true);
            e.currentTarget.select();
          }}
          onBlur={() => setFocused(false)}
          placeholder={placeholder}
          style={{
            flex: 1,
            border: "none",
            background: "transparent",
            outline: "none",
            fontSize: compact ? 16 : 22,
            color: "var(--text-heading)",
            padding: 0,
            fontWeight: 400,
            caretColor: "var(--accent-hex)",
            letterSpacing: 0.1,
          }}
        />
        {searching && <div className="search-shimmer" aria-hidden />}
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

      {tab === "titles" && totalWorksCount > 0 && (
        <TitleFilters
          mediaFilter={titleMediaFilter}
          selectedSeasons={selectedSeasonFilters}
          availableSeasons={availableSeasonNumbers}
          filteredCount={works.length}
          totalCount={totalWorksCount}
          onMediaFilterChange={onTitleMediaFilterChange}
          onToggleSeason={onToggleSeasonFilter}
          onClearSeasons={onClearSeasonFilters}
        />
      )}

      <div ref={listRef} style={{ maxHeight: compact ? 280 : 420, overflow: "auto", position: "relative" }}>
        {tab === "titles" && (
          <div className={`results-shell ${searching && works.length > 0 ? "is-refreshing" : ""}`}>
            {searching && works.length > 0 && (
              <div className="results-status" aria-live="polite">
                <span className="mini-spinner" aria-hidden />
                <span>Searching</span>
              </div>
            )}
            <div key={titleResultsKey} className="results-content">
              <WorkList
                items={works}
                selectedWorkId={selectedWorkId}
                expandedWorkId={expandedWorkId}
                expandedSeasonNumber={expandedSeasonNumber}
                selectedEpisodeMatchId={selectedEpisodeMatchId}
                cursorIndex={cursorIndex}
                onToggleExpandWork={onToggleExpandWork}
                onToggleExpandSeason={onToggleExpandSeason}
                onPickWork={onPickWork}
                onPickEpisode={onPickEpisode}
                onHydrateEpisode={onHydrateEpisode}
                searching={searching}
                emptyHint={totalWorksCount > 0 ? "No titles match these filters" : undefined}
              />
            </div>
          </div>
        )}
        {tab === "source" && (
          hasSelectedEpisode ? (
            <SubList
              items={sources}
              selectedId={selectedSourceId}
              cursorIndex={cursorIndex}
              onPick={onPickSource}
            />
          ) : (
            <EmptyTab hint="Pick a title (and episode) first" />
          )
        )}
        {tab === "target" && (
          hasSelectedEpisode ? (
            <TargetList
              items={targets}
              selectedId={selectedTargetId}
              cursorIndex={cursorIndex}
              onPick={onPickTarget}
            />
          ) : (
            <EmptyTab hint="Pick a title (and episode) first" />
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
          gap: 12,
          padding: "12px 20px",
          borderTop: "1px solid rgba(255,255,255,0.05)",
          fontSize: 12.5,
          color: "var(--text-label)",
        }}
      >
        <Kbd dim>↑↓←→</Kbd>
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
            {!hasSelectedEpisode
              ? "Pick a title to continue"
              : "Auto-selecting source and target subtitles"}
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
  padding: "8px 16px",
  background: "linear-gradient(180deg, var(--accent-hex), var(--accent-deep))",
  color: "#1a0f08",
  border: "none",
  borderRadius: 7,
  fontSize: 13,
  fontWeight: 600,
  cursor: "pointer",
};

function TitleFilters({
  mediaFilter,
  selectedSeasons,
  availableSeasons,
  filteredCount,
  totalCount,
  onMediaFilterChange,
  onToggleSeason,
  onClearSeasons,
}: {
  mediaFilter: TitleMediaFilter;
  selectedSeasons: number[];
  availableSeasons: number[];
  filteredCount: number;
  totalCount: number;
  onMediaFilterChange: (filter: TitleMediaFilter) => void;
  onToggleSeason: (seasonNumber: number) => void;
  onClearSeasons: () => void;
}): JSX.Element {
  const filters: Array<{ id: TitleMediaFilter; label: string }> = [
    { id: "all", label: "All" },
    { id: "series", label: "TV Shows" },
    { id: "movie", label: "Movies" },
    { id: "specials", label: "OVA / Specials" },
  ];
  const showSeasons =
    availableSeasons.length > 0 && (mediaFilter === "series" || selectedSeasons.length > 0);

  return (
    <div
      style={{
        padding: "10px 20px 12px",
        borderBottom: "1px solid rgba(255,255,255,0.05)",
        background: "rgba(0,0,0,0.12)",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {filters.map((filter) => (
            <FilterChip
              key={filter.id}
              active={mediaFilter === filter.id}
              label={filter.label}
              onClick={() => onMediaFilterChange(filter.id)}
            />
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 11.5, color: "var(--text-dim)", whiteSpace: "nowrap" }}>
          {filteredCount === totalCount
            ? `${totalCount} shown`
            : `${filteredCount} of ${totalCount}`}
        </span>
      </div>
      {showSeasons && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span
            style={{
              fontSize: 10.5,
              color: "var(--text-label)",
              textTransform: "uppercase",
              letterSpacing: 1,
            }}
          >
            Seasons
          </span>
          <FilterChip
            active={selectedSeasons.length === 0}
            label="All seasons"
            onClick={onClearSeasons}
          />
          {availableSeasons.map((season) => (
            <FilterChip
              key={season}
              active={selectedSeasons.includes(season)}
              label={season > 0 ? `S${season}` : "SP"}
              onClick={() => onToggleSeason(season)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function FilterChip({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        padding: "5px 10px",
        borderRadius: 7,
        border: active ? "1px solid var(--accent-ring)" : "1px solid rgba(255,255,255,0.07)",
        background: active ? "var(--accent-tint)" : "rgba(255,255,255,0.025)",
        color: active ? "var(--accent-text)" : "var(--text-muted)",
        fontSize: 12,
        fontWeight: 600,
        lineHeight: 1.2,
        cursor: "pointer",
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </button>
  );
}

interface TitleNavRow {
  kind: "work" | "season" | "episode" | "skeleton_episode";
  workId: string;
  seasonNumber?: number;
  episodeNumber?: number;
  episodeMatchId?: string;
}

function flattenNavRows(
  items: WorkItem[],
  expandedWorkId: string | null,
  expandedSeasonNumber: number | null,
): TitleNavRow[] {
  const rows: TitleNavRow[] = [];
  for (const work of items) {
    rows.push({ kind: "work", workId: work.id });
    if (work.id === expandedWorkId && work.expandable) {
      for (const season of work.seasons) {
        rows.push({ kind: "season", workId: work.id, seasonNumber: season.seasonNumber });
        if (season.seasonNumber === expandedSeasonNumber) {
          for (const ep of season.episodes) {
            const isSkeleton = ep.matchId.startsWith("skeleton:");
            rows.push({
              kind: isSkeleton ? "skeleton_episode" : "episode",
              workId: work.id,
              seasonNumber: season.seasonNumber,
              episodeNumber: ep.episode ?? undefined,
              episodeMatchId: ep.matchId,
            });
          }
        }
      }
    }
  }
  return rows;
}

export function paletteWorksNavRows(
  items: WorkItem[],
  expandedWorkId: string | null,
  expandedSeasonNumber: number | null,
): TitleNavRow[] {
  return flattenNavRows(items, expandedWorkId, expandedSeasonNumber);
}

function WorkList({
  items,
  selectedWorkId,
  expandedWorkId,
  expandedSeasonNumber,
  selectedEpisodeMatchId,
  cursorIndex,
  onToggleExpandWork,
  onToggleExpandSeason,
  onPickWork,
  onPickEpisode,
  onHydrateEpisode,
  searching,
  emptyHint,
}: {
  items: WorkItem[];
  selectedWorkId: string | null;
  expandedWorkId: string | null;
  expandedSeasonNumber: number | null;
  selectedEpisodeMatchId: string | null;
  cursorIndex: number;
  onToggleExpandWork: (id: string) => void;
  onToggleExpandSeason: (workId: string, seasonNumber: number) => void;
  onPickWork: (id: string) => void;
  onPickEpisode: (workId: string, matchId: string) => void;
  onHydrateEpisode: (workId: string, season: number, episode: number) => void;
  searching: boolean;
  emptyHint?: string;
}): JSX.Element {
  if (items.length === 0) {
    if (searching) {
      return (
        <div className="empty-searching">
          <div className="empty-searching-card">
            <span className="empty-searching-spinner" aria-hidden />
            <span>Searching</span>
          </div>
        </div>
      );
    }
    return <EmptyTab hint={emptyHint ?? "Type a title and press ↵ to search"} />;
  }

  const rows = flattenNavRows(items, expandedWorkId, expandedSeasonNumber);
  const rowIndexByKey = new Map<string, number>();
  rows.forEach((row, index) => {
    if (row.kind === "work") {
      rowIndexByKey.set(`work:${row.workId}`, index);
      return;
    }
    if (row.kind === "season") {
      rowIndexByKey.set(`season:${row.workId}:${row.seasonNumber}`, index);
      return;
    }
    rowIndexByKey.set(
      `episode:${row.workId}:${row.seasonNumber}:${row.episodeMatchId}`,
      index,
    );
  });
  const rowIndexForWork = (workId: string): number =>
    rowIndexByKey.get(`work:${workId}`) ?? -1;
  const rowIndexForSeason = (workId: string, seasonNumber: number): number =>
    rowIndexByKey.get(`season:${workId}:${seasonNumber}`) ?? -1;
  const rowIndexForEpisode = (
    workId: string,
    seasonNumber: number,
    episodeMatchId: string,
  ): number =>
    rowIndexByKey.get(`episode:${workId}:${seasonNumber}:${episodeMatchId}`) ?? -1;

  return (
    <div className="work-grid">
      {items.map((work) => {
        const workRowIndex = rowIndexForWork(work.id);
        const isSelected = selectedWorkId === work.id;
        const isExpanded = expandedWorkId === work.id;
        return (
          <div className="work-card" key={`work-card-${work.id}`}>
            <WorkRow
              work={work}
              selected={isSelected}
              expanded={isExpanded}
              focused={cursorIndex === workRowIndex}
              rowIndex={workRowIndex}
              onClick={() => {
                if (work.expandable) {
                  onToggleExpandWork(work.id);
                } else {
                  onPickWork(work.id);
                }
              }}
            />
            {isExpanded && (
              <div className="work-nested">
                {work.seasons.map((season) => {
                  const seasonRowIndex = rowIndexForSeason(work.id, season.seasonNumber);
                  const open = expandedSeasonNumber === season.seasonNumber;
                  return (
                    <div key={`season-group-${work.id}-${season.seasonNumber}`}>
                      <SeasonRow
                        season={season}
                        open={open}
                        focused={cursorIndex === seasonRowIndex}
                        rowIndex={seasonRowIndex}
                        onClick={() => onToggleExpandSeason(work.id, season.seasonNumber)}
                      />
                      {open && season.episodes.map((ep) => {
                        const epRowIndex = rowIndexForEpisode(work.id, season.seasonNumber, ep.matchId);
                        const isSkeleton = ep.matchId.startsWith("skeleton:");
                        if (isSkeleton) {
                          return (
                            <EpisodeRow
                              key={`skep-${ep.matchId}`}
                              label={ep.label}
                              subtitles={0}
                              picked={false}
                              focused={cursorIndex === epRowIndex}
                              skeleton
                              hydratable={ep.episode != null}
                              rowIndex={epRowIndex}
                              onClick={() => ep.episode != null && onHydrateEpisode(work.id, season.seasonNumber, ep.episode)}
                            />
                          );
                        }
                        const picked = selectedEpisodeMatchId === ep.matchId;
                        return (
                          <EpisodeRow
                            key={`ep-${ep.matchId}`}
                            label={ep.label}
                            subtitles={ep.subtitlesCount}
                            picked={picked}
                            focused={cursorIndex === epRowIndex}
                            rowIndex={epRowIndex}
                            onClick={() => onPickEpisode(work.id, ep.matchId)}
                          />
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function WorkRow({
  work,
  selected,
  expanded,
  focused,
  onClick,
  rowIndex,
}: {
  work: WorkItem;
  selected: boolean;
  expanded: boolean;
  focused: boolean;
  onClick: () => void;
  rowIndex: number;
}): JSX.Element {
  const [posterFailed, setPosterFailed] = useState(false);
  const posterUrl = work.posterUrl && !posterFailed ? work.posterUrl : null;

  useEffect(() => {
    setPosterFailed(false);
  }, [work.posterUrl]);

  return (
    <Row
      selected={selected}
      focused={focused}
      onClick={onClick}
      rowIndex={rowIndex}
      className="work-row"
    >
      <div
        className={`work-poster ${posterUrl ? "has-image" : ""}`}
        aria-hidden
      >
        {posterUrl && (
          <img
            src={posterUrl}
            alt=""
            loading="lazy"
            decoding="async"
            onError={() => setPosterFailed(true)}
          />
        )}
        {!posterUrl && <span>{work.mediaType === "movie" ? "MOV" : "TV"}</span>}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          {work.expandable && <DisclosureChevron open={expanded} />}
          <div
            style={{
              fontSize: 16,
              color: "var(--text-heading)",
              fontWeight: 500,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {work.title}
          </div>
        </div>
        <div style={{ fontSize: 12.5, color: "var(--text-label)", marginTop: 3 }}>
          {work.year} · {work.type}
          {work.totalSubtitles > 0 ? ` · ${work.totalSubtitles.toLocaleString()} subs` : ""}
        </div>
        <InfoChipRow chips={work.chips} max={4} />
      </div>
      {focused && <Kbd>↵</Kbd>}
    </Row>
  );
}

function SeasonRow({
  season,
  open,
  focused,
  onClick,
  rowIndex,
}: {
  season: WorkSeasonItem;
  open: boolean;
  focused: boolean;
  onClick: () => void;
  rowIndex: number;
}): JSX.Element {
  return (
    <div
      data-cursor-row={rowIndex}
      onClick={onClick}
      onMouseDown={(e) => e.preventDefault()}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "8px 20px 8px 48px",
        cursor: "pointer",
        background: focused ? "var(--accent-tint)" : "transparent",
        borderLeft: `2px solid ${focused ? "var(--accent-hex)" : "transparent"}`,
        userSelect: "none",
        WebkitUserSelect: "none",
      }}
    >
      <DisclosureChevron open={open} />
      <div style={{ flex: 1, fontSize: 13.5, color: "var(--text-body)" }}>{season.label}</div>
      <span style={{ fontSize: 11, color: "var(--text-label)" }}>
        {season.episodes.length} ep{season.episodes.length === 1 ? "" : "s"}
      </span>
      {focused && <Kbd>↵</Kbd>}
    </div>
  );
}

function EpisodeRow({
  label,
  subtitles,
  picked,
  focused,
  onClick,
  skeleton,
  hydratable,
  rowIndex,
}: {
  label: string;
  subtitles: number;
  picked: boolean;
  focused: boolean;
  onClick: () => void;
  skeleton?: boolean;
  hydratable?: boolean;
  rowIndex?: number;
}): JSX.Element {
  const clickable = !skeleton || !!hydratable;
  return (
    <div
      data-cursor-row={rowIndex ?? undefined}
      onClick={clickable ? onClick : undefined}
      onMouseDown={(e) => e.preventDefault()}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "7px 20px 7px 72px",
        cursor: clickable ? "pointer" : "default",
        opacity: skeleton && !clickable ? 0.58 : 1,
        background: focused
          ? "var(--accent-tint)"
          : !skeleton && picked
            ? "rgba(255,185,90,0.05)"
            : "transparent",
        borderLeft: `2px solid ${focused || (!skeleton && picked) ? "var(--accent-hex)" : "transparent"}`,
        userSelect: "none",
        WebkitUserSelect: "none",
      }}
    >
      <span
        className="mono"
        style={{
          flex: 1,
          fontSize: 13,
          color: skeleton ? "var(--text-muted)" : "var(--text-body)",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {label}
      </span>
      {subtitles > 0 && (
        <span style={{ fontSize: 10.5, color: "var(--text-label)" }}>{subtitles} subs</span>
      )}
      {skeleton && hydratable && !focused && (
        <span style={{ fontSize: 10.5, color: "var(--accent-text)" }}>Search</span>
      )}
      {focused && <Kbd>{skeleton ? "Search" : "↵"}</Kbd>}
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
  if (items.length === 0) return <EmptyTab hint="No subtitles for this episode" />;
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
            rowIndex={i}
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
                  fontSize: 14,
                  color: "var(--text-body)",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {r.file}
              </div>
              <div style={{ fontSize: 12, color: "var(--text-label)", marginTop: 3 }}>
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
            rowIndex={i}
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
                  fontSize: 14,
                  color: "var(--text-body)",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  fontWeight: isSpecial ? 500 : 400,
                }}
              >
                {r.title ?? r.file}
              </div>
              <div style={{ fontSize: 12, color: "var(--text-label)", marginTop: 3 }}>
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
            data-cursor-row={i}
            onClick={() => {
              if (!disabled) onPick(c.id);
            }}
            onMouseDown={(e) => e.preventDefault()}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 14,
              padding: "10px 20px",
              opacity: disabled ? 0.4 : 1,
              cursor: disabled ? "not-allowed" : "pointer",
              background: focused ? "var(--accent-tint)" : "transparent",
              borderLeft: `2px solid ${focused ? "var(--accent-hex)" : "transparent"}`,
              userSelect: "none",
              WebkitUserSelect: "none",
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
                fontSize: 14,
                border: `1px solid ${isPrimary ? "var(--accent-ring)" : "rgba(255,255,255,0.05)"}`,
              }}
            >
              {c.icon}
            </div>
            <span style={{ flex: 1, fontSize: 14, color: "var(--text-body)" }}>
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
  rowIndex?: number;
  className?: string;
}

const Row = forwardRef<HTMLDivElement, RowProps>(function Row(
  { selected, focused, onClick, children, rowIndex, className },
  ref,
) {
  return (
    <div
      ref={ref}
      className={className}
      data-cursor-row={rowIndex ?? undefined}
      data-row-active={className === "work-row" && (focused || selected) ? "true" : undefined}
      onClick={onClick}
      onMouseDown={(e) => e.preventDefault()}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: className === "work-row" ? undefined : "10px 20px",
        background: focused
          ? "var(--accent-tint)"
          : selected
            ? "rgba(255,185,90,0.05)"
            : undefined,
        borderLeft:
          className === "work-row"
            ? "2px solid transparent"
            : `2px solid ${focused || selected ? "var(--accent-hex)" : "transparent"}`,
        cursor: "pointer",
        userSelect: "none",
        WebkitUserSelect: "none",
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
        padding: "48px 20px",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 14,
        color: "var(--text-label)",
      }}
    >
      <div
        aria-hidden
        style={{
          width: 36,
          height: 1,
          background:
            "linear-gradient(90deg, transparent, var(--accent-ring), transparent)",
          opacity: 0.6,
        }}
      />
      <span style={{ fontSize: 12, letterSpacing: 0.2 }}>{hint}</span>
    </div>
  );
}
