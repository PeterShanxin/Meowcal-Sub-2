import { useState } from "react";
import { formatTimestamp } from "../../lib/subtitle-editor/timing";
import type { Issue, SubtitleDocument } from "../../lib/subtitle-editor/types";

const PAGE_SIZE = 30;
const displayTime = (value: number): string =>
  Number.isSafeInteger(value) && value >= 0 ? formatTimestamp(value) : `${value} ms`;

export function CueList({
  document,
  preview,
  selected,
  onSelect,
  disabled,
}: {
  document: SubtitleDocument;
  preview: SubtitleDocument | null;
  selected: number;
  onSelect: (index: number) => void;
  disabled: boolean;
}): JSX.Element {
  const [jump, setJump] = useState("");
  const page = Math.floor(selected / PAGE_SIZE);
  const total = document.cues.length;
  return (
    <section className="editor-cues">
      <div className="editor-actions editor-pagination">
        <button
          type="button"
          disabled={disabled || page === 0}
          onClick={() => onSelect((page - 1) * PAGE_SIZE)}
        >
          Previous
        </button>
        <span>
          Page {page + 1} / {Math.max(1, Math.ceil(total / PAGE_SIZE))}
        </span>
        <button
          type="button"
          disabled={disabled || (page + 1) * PAGE_SIZE >= total}
          onClick={() => onSelect((page + 1) * PAGE_SIZE)}
        >
          Next
        </button>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const index = Number(jump) - 1;
            if (Number.isInteger(index) && index >= 0 && index < total) onSelect(index);
          }}
        >
          <input
            aria-label="Jump to subtitle"
            type="number"
            min={1}
            max={total}
            placeholder="#"
            value={jump}
            onChange={(event) => setJump(event.target.value)}
            disabled={disabled}
            required
          />
          <button type="submit" disabled={disabled}>
            Go
          </button>
        </form>
      </div>
      {preview && (
        <p className="editor-preview-label">
          Timing preview · all {total.toLocaleString()} subtitles checked · not applied
        </p>
      )}
      <div className="editor-table-scroll">
        <table>
          <thead>
            <tr>
              <th>Subtitle</th>
              <th>Current time</th>
              {preview && <th>After correction</th>}
            </tr>
          </thead>
          <tbody>
            {document.cues.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).map((cue) => (
              <tr key={cue.id} aria-selected={selected === cue.index - 1}>
                <td>
                  <button
                    type="button"
                    disabled={disabled}
                    aria-label={`Edit subtitle ${cue.index}`}
                    onClick={() => onSelect(cue.index - 1)}
                  >
                    <span>#{cue.index}</span>
                    <span className="editor-cue-text">{cue.text || "(empty subtitle)"}</span>
                  </button>
                </td>
                <td>
                  {displayTime(cue.startMs)}
                  <br />
                  {displayTime(cue.endMs)}
                </td>
                {preview && (
                  <td className="editor-preview-time">
                    {displayTime(preview.cues[cue.index - 1].startMs)}
                    <br />
                    {displayTime(preview.cues[cue.index - 1].endMs)}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function IssueList({
  issues,
  onSelect,
  disabled,
}: {
  issues: Issue[];
  onSelect: (index: number) => void;
  disabled: boolean;
}): JSX.Element {
  const [page, setPage] = useState(0);
  const current = Math.min(page, Math.max(0, Math.ceil(issues.length / 10) - 1));
  const errors = issues.filter((issue) => issue.severity === "error").length;
  return (
    <details className="editor-section editor-issues">
      <summary>
        {errors} errors · {issues.length - errors} warnings
        {!issues.length ? " · checks passed" : " · inspect"}
      </summary>
      <p>
        Errors block saving. Overlaps, duplicates and out-of-order cues are warnings; review them
        before use.
      </p>
      {issues.slice(current * 10, current * 10 + 10).map((issue) => (
        <div
          key={`${issue.code}:${issue.cueIndices[0]}`}
          className={issue.severity === "error" ? "editor-error" : ""}
        >
          <button
            type="button"
            disabled={disabled}
            onClick={() => onSelect(issue.cueIndices[0] - 1)}
          >
            Go to #{issue.cueIndices[0]}
          </button>{" "}
          {issue.message}
          {issue.cueIndices.length > 1 && (
            <span>
              {" "}
              Cues: {issue.cueIndices.slice(0, 10).join(", ")}
              {issue.cueIndices.length > 10
                ? ` … (${issue.cueIndices.length} total; use the subtitle number to jump)`
                : ""}
            </span>
          )}
        </div>
      ))}
      {issues.length > 10 && (
        <div className="editor-actions">
          <button type="button" disabled={current === 0} onClick={() => setPage(current - 1)}>
            Previous issues
          </button>
          <span>
            {current + 1} / {Math.ceil(issues.length / 10)}
          </span>
          <button
            type="button"
            disabled={(current + 1) * 10 >= issues.length}
            onClick={() => setPage(current + 1)}
          >
            Next issues
          </button>
        </div>
      )}
    </details>
  );
}
