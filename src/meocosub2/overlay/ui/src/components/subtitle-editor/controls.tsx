import { useState } from "react";
import { integerMs } from "../../lib/subtitle-editor/history";
import type { Cue, Transform } from "../../lib/subtitle-editor/types";

export interface TimingFields {
  mode: "offset" | "anchors";
  offset: string;
  source1: string;
  target1: string;
  source2: string;
  target2: string;
}

export const initialTiming: TimingFields = {
  mode: "offset",
  offset: "0",
  source1: "0",
  target1: "0",
  source2: "60000",
  target2: "60000",
};

export function CueForm({
  cue,
  onSave,
  onDirty,
  onError,
}: {
  cue: Cue;
  onSave: (edit: Pick<Cue, "startMs" | "endMs" | "text">) => void;
  onDirty: (value: boolean) => void;
  onError: (message: string) => void;
}): JSX.Element {
  const [start, setStart] = useState(String(cue.startMs));
  const [end, setEnd] = useState(String(cue.endMs));
  const [text, setText] = useState(cue.text);
  const dirty = start !== String(cue.startMs) || end !== String(cue.endMs) || text !== cue.text;
  function change(nextStart: string, nextEnd: string, nextText: string): void {
    setStart(nextStart);
    setEnd(nextEnd);
    setText(nextText);
    onDirty(
      nextStart !== String(cue.startMs) || nextEnd !== String(cue.endMs) || nextText !== cue.text,
    );
  }
  return (
    <form
      className="editor-section"
      onSubmit={(event) => {
        event.preventDefault();
        try {
          onSave({ startMs: integerMs(start), endMs: integerMs(end), text });
          onDirty(false);
        } catch (error) {
          onError(error instanceof Error ? error.message : "Could not edit this subtitle.");
        }
      }}
    >
      <h3>Subtitle {cue.index}</h3>
      <div className="editor-fields">
        <label>
          Start (ms)
          <input
            value={start}
            inputMode="numeric"
            onChange={(event) => change(event.target.value, end, text)}
          />
        </label>
        <label>
          End (ms)
          <input
            value={end}
            inputMode="numeric"
            onChange={(event) => change(start, event.target.value, text)}
          />
        </label>
      </div>
      <label>
        Subtitle text
        <textarea
          aria-label="Subtitle text"
          rows={4}
          value={text}
          onChange={(event) => change(start, end, event.target.value)}
        />
      </label>
      <div className="editor-actions">
        <button type="submit" disabled={!dirty}>
          Keep edit
        </button>
        <button
          type="button"
          disabled={!dirty}
          onClick={() => change(String(cue.startMs), String(cue.endMs), cue.text)}
        >
          Discard edit
        </button>
        <span>{dirty ? "Uncommitted edit" : "Up to date"}</span>
      </div>
    </form>
  );
}

export function TimingForm({
  fields,
  onChange,
  onPreview,
  onApply,
  hasPreview,
  disabled,
}: {
  fields: TimingFields;
  onChange: (fields: TimingFields) => void;
  onPreview: (spec: Transform) => void;
  onApply: () => void;
  hasPreview: boolean;
  disabled: boolean;
}): JSX.Element {
  const [error, setError] = useState("");
  function preview(): void {
    try {
      setError("");
      onPreview(
        fields.mode === "offset"
          ? { offsetMs: integerMs(fields.offset) }
          : {
              anchors: [
                { sourceMs: integerMs(fields.source1), targetMs: integerMs(fields.target1) },
                { sourceMs: integerMs(fields.source2), targetMs: integerMs(fields.target2) },
              ],
            },
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid timing values.");
    }
  }
  const inputs: [keyof Omit<TimingFields, "mode">, string][] =
    fields.mode === "offset"
      ? [["offset", "Shift (ms)"]]
      : [
          ["source1", "Subtitle time 1 (ms)"],
          ["target1", "Video time 1 (ms)"],
          ["source2", "Subtitle time 2 (ms)"],
          ["target2", "Video time 2 (ms)"],
        ];
  return (
    <section className="editor-section">
      <h3>Timing correction</h3>
      <label>
        Method
        <select
          aria-label="Method"
          value={fields.mode}
          onChange={(event) => {
            setError("");
            onChange({ ...fields, mode: event.target.value as TimingFields["mode"] });
          }}
          disabled={disabled}
        >
          <option value="offset">Shift all subtitles</option>
          <option value="anchors">Match two points</option>
        </select>
      </label>
      <p>
        {fields.mode === "offset"
          ? "Negative = earlier. Positive = later. 1000 ms = 1 second."
          : "Match an early and a late subtitle to their video times to correct gradual drift."}
      </p>
      <div className="editor-fields">
        {inputs.map(([key, label]) => (
          <label key={key}>
            {label}
            <input
              value={fields[key]}
              disabled={disabled}
              inputMode="numeric"
              onChange={(event) => {
                setError("");
                onChange({ ...fields, [key]: event.target.value });
              }}
            />
          </label>
        ))}
      </div>
      <div className="editor-actions">
        <button type="button" disabled={disabled} onClick={preview}>
          Preview timing
        </button>
        <button type="button" disabled={disabled || !hasPreview} onClick={onApply}>
          Apply timing
        </button>
      </div>
      {error && (
        <p role="alert" className="editor-error">
          {error}
        </p>
      )}
    </section>
  );
}
