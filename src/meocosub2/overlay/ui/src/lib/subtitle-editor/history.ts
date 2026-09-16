import { transformSubtitle } from "./timing";
import type { Cue, SubtitleDocument, Transform } from "./types";

export interface History {
  past: SubtitleDocument[];
  present: SubtitleDocument;
  future: SubtitleDocument[];
  preview: SubtitleDocument | null;
}

export function createHistory(present: SubtitleDocument): History {
  return { past: [], present, future: [], preview: null };
}

export function commit(history: History, present: SubtitleDocument): History {
  if (present === history.present) return history;
  return {
    past: [...history.past.slice(-49), history.present],
    present,
    future: [],
    preview: null,
  };
}

export function editCue(
  history: History,
  index: number,
  edit: Pick<Cue, "startMs" | "endMs" | "text">,
): History {
  const cue = history.present.cues[index];
  if (!cue) throw new Error("Select a subtitle to edit.");
  if (!Number.isSafeInteger(edit.startMs) || !Number.isSafeInteger(edit.endMs)) {
    throw new Error("Use whole milliseconds for subtitle times.");
  }
  if (cue.startMs === edit.startMs && cue.endMs === edit.endMs && cue.text === edit.text)
    return history;
  const cues = history.present.cues.slice();
  cues[index] = { ...cue, ...edit };
  return commit(history, { ...history.present, cues });
}

export function preview(history: History, spec: Transform): History {
  return { ...history, preview: transformSubtitle(history.present, spec) };
}

export function applyPreview(history: History): History {
  if (!history.preview) throw new Error("Preview the timing change first.");
  return commit(history, history.preview);
}

export function undo(history: History): History {
  const present = history.past.at(-1);
  return present
    ? {
        past: history.past.slice(0, -1),
        present,
        future: [history.present, ...history.future],
        preview: null,
      }
    : history;
}

export function redo(history: History): History {
  const present = history.future[0];
  return present
    ? {
        past: [...history.past, history.present],
        present,
        future: history.future.slice(1),
        preview: null,
      }
    : history;
}

export function integerMs(value: string): number {
  if (!/^-?\d+$/.test(value) || !Number.isSafeInteger(Number(value))) {
    throw new Error("Enter a whole number of milliseconds.");
  }
  return Number(value);
}
