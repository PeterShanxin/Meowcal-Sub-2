import { useEffect, useMemo, useRef, useState } from "react";
import { api, type EditorFile } from "../../hooks/use-api";
import { diagnose } from "../../lib/subtitle-editor/diagnostics";
import { parseSubtitle, serializeSubtitle } from "../../lib/subtitle-editor/document";
import {
  applyPreview,
  commit,
  createHistory,
  editCue,
  type History,
  preview,
  redo,
  undo,
} from "../../lib/subtitle-editor/history";
import type { SubtitleDocument } from "../../lib/subtitle-editor/types";
import { store } from "../../state/store";
import { CueForm, initialTiming, TimingForm, type TimingFields } from "./controls";
import { CueList, IssueList } from "./cue-list";
import "./workspace.css";

interface FileState {
  file: EditorFile;
  original: SubtitleDocument | null;
  history: History | null;
  selected: number;
  timing: TimingFields;
  version: number;
  error: string;
}

function loadFile(file: EditorFile): FileState {
  let doc: SubtitleDocument | null = null;
  let error = file.error ?? "";
  if (file.content !== undefined) {
    try {
      doc = parseSubtitle(file.content, { filename: file.filename });
    } catch (err) {
      error = err instanceof Error ? err.message : "Could not read this subtitle.";
    }
  }
  return {
    file,
    original: doc,
    history: doc ? createHistory(doc) : null,
    selected: 0,
    timing: { ...initialTiming },
    version: 0,
    error,
  };
}

export function SubtitleEditor({ sessionId }: { sessionId: string }): JSX.Element {
  const dialog = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState<FileState[]>([]);
  const [active, setActive] = useState(0);
  const [editingSession, setEditingSession] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const current = files[active];
  const history = current?.history;
  const doc = history?.present;
  const issues = useMemo(() => (doc ? diagnose(doc) : []), [doc]);
  const changed = files.filter((file) => file.history && file.history.present !== file.original);
  const pending = draft || changed.length > 0;
  const invalid = files.some(
    (file) =>
      file.history && diagnose(file.history.present).some((issue) => issue.severity === "error"),
  );
  const hasPreview = files.some((file) => file.history?.preview);

  useEffect(() => {
    if (open) dialog.current?.showModal();
    else dialog.current?.close();
  }, [open]);
  useEffect(() => {
    if (!pending) return;
    const protect = (event: BeforeUnloadEvent): void => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", protect);
    return () => window.removeEventListener("beforeunload", protect);
  }, [pending]);

  async function begin(): Promise<void> {
    setBusy(true);
    setError("");
    setNotice("");
    setFiles([]);
    setOpen(true);
    setDraft(false);
    try {
      const result = await api.getEditorFiles(sessionId);
      setFiles(result.files.map(loadFile));
      setActive(0);
      setEditingSession(result.sessionId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open subtitles.");
    } finally {
      setBusy(false);
    }
  }
  function close(): void {
    if (busy) return;
    if (
      pending &&
      !window.confirm("Discard subtitle changes that have not been saved for this session?")
    )
      return;
    setOpen(false);
    setFiles([]);
    setDraft(false);
  }
  function update(change: Partial<FileState>): void {
    setFiles((previous) =>
      previous.map((file, i) =>
        i === active ? { ...file, ...change, version: file.version + 1 } : file,
      ),
    );
  }
  function changeHistory(action: (value: History) => History): void {
    if (!history) return;
    setError("");
    try {
      update({ history: action(history) });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change subtitles.");
    }
  }
  async function importFile(file: File): Promise<void> {
    setError("");
    setBusy(true);
    try {
      if (file.size > 4 * 1024 * 1024) throw new Error("Choose a subtitle up to 4 MiB.");
      if (!/\.(srt|vtt)$/i.test(file.name)) throw new Error("Choose an SRT or WebVTT file.");
      const text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(
        await file.arrayBuffer(),
      );
      const imported = parseSubtitle(text, { filename: file.name });
      update({
        history: history ? commit(history, imported) : createHistory(imported),
        selected: 0,
        error: "",
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Choose a UTF-8 subtitle file.");
    } finally {
      setBusy(false);
    }
  }
  function exportFile(): void {
    if (!doc) return;
    try {
      const blob = new Blob([serializeSubtitle(doc)], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${doc.filename.replace(/\.(srt|vtt)$/i, "")}.corrected.${doc.format}`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice("Corrected copy exported. Save & use to update this session too.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not export subtitles.");
    }
  }
  async function save(): Promise<void> {
    setBusy(true);
    setError("");
    try {
      const result = await api.saveSubtitleEdits({
        sessionId: editingSession,
        revisions: Object.fromEntries(files.map(({ file }) => [file.key, file.revision ?? ""])),
        files: changed.map((file) => {
          if (!file.history || !file.file.revision)
            throw new Error("Reopen this file before saving.");
          return {
            key: file.file.key,
            format: file.history.present.format,
            content: serializeSubtitle(file.history.present),
          };
        }),
      });
      setFiles([]);
      setOpen(false);
      setDraft(false);
      setNotice("Corrected copies saved and ready for sync. Playback offset reset to 0 ms.");
      store.set({
        snapshot: result.state,
        config: result.state.config,
        liveLines: [],
        lastSubtitle: "",
        sourceInspection: null,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save subtitles.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <button type="button" className="editor-launch" onClick={() => void begin()}>
        Edit subtitles
      </button>
      {!open && notice && (
        <p role="status" className="editor-saved">
          {notice}
        </p>
      )}
      <dialog
        ref={dialog}
        className="subtitle-editor"
        aria-labelledby="subtitle-editor-title"
        onCancel={(event) => {
          event.preventDefault();
          close();
        }}
      >
        <header>
          <div>
            <span className="editor-eyebrow">SUBTITLE WORKSPACE</span>
            <h2 id="subtitle-editor-title">Edit subtitles · Optional</h2>
          </div>
          <button type="button" onClick={close} disabled={busy} aria-label="Close subtitle editor">
            Close
          </button>
        </header>
        <p className="editor-intro">
          You usually do not need to edit subtitles. Meowcal checks them automatically and syncs
          playback using on-screen subtitles, adjusting timing offsets when reliable matches are
          available. Use this workspace for text changes or manual timing corrections. Original
          files stay untouched.
        </p>
        <fieldset disabled={busy} className="editor-body">
          <div className="editor-toolbar">
            <label>
              Track
              <select
                aria-label="Track"
                value={active}
                disabled={draft}
                onChange={(event) => {
                  setActive(Number(event.target.value));
                  setError("");
                }}
              >
                {files.map((file, index) => (
                  <option key={file.file.key} value={index}>
                    {file.file.role === "source" ? "Source" : "Target"} · {file.file.filename}
                    {file.history && file.history.present !== file.original ? " *" : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="editor-import">
              Import replacement
              <input
                type="file"
                accept=".srt,.vtt"
                disabled={draft || !current?.file.revision}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file) void importFile(file);
                }}
              />
            </label>
            <button
              type="button"
              disabled={draft || !history?.past.length}
              onClick={() => changeHistory(undo)}
            >
              Undo
            </button>
            <button
              type="button"
              disabled={draft || !history?.future.length}
              onClick={() => changeHistory(redo)}
            >
              Redo
            </button>
          </div>
          {current?.error && (
            <p role="alert" className="editor-error">
              {current.error}
            </p>
          )}
          {doc && history && (
            <>
              <div className="editor-meta">
                <span>
                  {doc.filename} · {doc.format.toUpperCase()} · {doc.cues.length.toLocaleString()}{" "}
                  subtitles
                </span>
                <span>{history.past.length} undo steps (up to 50)</span>
              </div>
              <IssueList
                issues={issues}
                disabled={draft}
                onSelect={(selected) => update({ selected })}
              />
              <div className="editor-grid">
                <CueList
                  document={doc}
                  preview={history.preview}
                  selected={current.selected}
                  disabled={draft}
                  onSelect={(selected) => update({ selected })}
                />
                <div className="editor-tools">
                  {doc.cues[current.selected] && (
                    <CueForm
                      key={`${active}:${current.version}`}
                      cue={doc.cues[current.selected]}
                      onDirty={setDraft}
                      onError={setError}
                      onSave={(edit) =>
                        changeHistory((value) => editCue(value, current.selected, edit))
                      }
                    />
                  )}
                  <TimingForm
                    key={active}
                    fields={current.timing}
                    disabled={draft || !doc.cues.length}
                    hasPreview={!!history.preview}
                    onChange={(timing) =>
                      update({ timing, history: { ...history, preview: null } })
                    }
                    onPreview={(spec) =>
                      changeHistory((value) => preview({ ...value, preview: null }, spec))
                    }
                    onApply={() => changeHistory(applyPreview)}
                  />
                  {history.preview && (
                    <button
                      type="button"
                      disabled={draft}
                      onClick={() => update({ history: { ...history, preview: null } })}
                    >
                      Discard timing preview
                    </button>
                  )}
                </div>
              </div>
            </>
          )}
        </fieldset>
        {busy && (
          <p role="status">
            {files.length ? "Saving or importing subtitles…" : "Reading prepared subtitles…"}
          </p>
        )}
        {error && (
          <p role="alert" className="editor-error">
            {error}
          </p>
        )}
        {open && notice && <p role="status">{notice}</p>}
        <footer>
          <p>
            {draft
              ? "Keep or discard the current edit to continue."
              : hasPreview
                ? "Apply or discard the timing preview before saving."
                : "Save & use rebuilds the prepared tracks and resets the playback offset to 0 ms."}
          </p>
          <div className="editor-actions">
            <button
              type="button"
              onClick={exportFile}
              disabled={
                busy ||
                draft ||
                !!history?.preview ||
                !doc ||
                issues.some((issue) => issue.severity === "error")
              }
            >
              Export copy
            </button>
            <button
              type="button"
              className="editor-primary"
              onClick={() => void save()}
              disabled={busy || draft || invalid || hasPreview || !changed.length}
            >
              Save & use
            </button>
          </div>
        </footer>
      </dialog>
    </>
  );
}
