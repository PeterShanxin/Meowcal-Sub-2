import { useEffect } from "react";

export interface KeyHandlers {
  onFocusPalette: () => void;
  onCycleTab: (direction: 1 | -1) => void;
  onMoveCursor: (direction: 1 | -1) => void;
  onPrimaryConfirm: () => void;
  onSelect: () => void;
  onOpenSettings: () => void;
  onClearSession: () => void;
}

function isModifierKey(e: KeyboardEvent): boolean {
  return e.metaKey || e.ctrlKey;
}

function isTypingContext(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable;
}

export function useKeybinds(h: KeyHandlers): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      // ⌘K / Ctrl+K — always
      if (isModifierKey(e) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        h.onFocusPalette();
        return;
      }

      // ⌘↵ / Ctrl+Enter — always (prepare/start)
      if (isModifierKey(e) && e.key === "Enter") {
        e.preventDefault();
        h.onPrimaryConfirm();
        return;
      }

      const target = e.target as HTMLElement | null;
      const isPaletteInput =
        target instanceof HTMLInputElement && target.dataset.palette === "true";

      // Tab / Shift+Tab — cycle palette tabs (when in palette input)
      if (e.key === "Tab" && !e.altKey && !e.ctrlKey && !e.metaKey) {
        if (isPaletteInput) {
          e.preventDefault();
          h.onCycleTab(e.shiftKey ? -1 : 1);
          return;
        }
      }

      // Arrow up/down — palette cursor navigation (regardless of focus target,
      // as long as user is not typing in a non-palette input)
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (!isPaletteInput && isTypingContext(e.target)) return;
        e.preventDefault();
        h.onMoveCursor(e.key === "ArrowDown" ? 1 : -1);
        return;
      }

      // Arrow left/right — cycle tabs when at text boundary or input empty
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        if (isPaletteInput) {
          const inp = target as HTMLInputElement;
          const atStart = (inp.selectionStart ?? 0) === 0 && (inp.selectionEnd ?? 0) === 0;
          const atEnd =
            (inp.selectionStart ?? 0) === inp.value.length &&
            (inp.selectionEnd ?? 0) === inp.value.length;
          const empty = inp.value.length === 0;
          if (empty || (e.key === "ArrowLeft" && atStart) || (e.key === "ArrowRight" && atEnd)) {
            e.preventDefault();
            h.onCycleTab(e.key === "ArrowRight" ? 1 : -1);
            return;
          }
          return;
        }
        if (isTypingContext(e.target)) return;
        e.preventDefault();
        h.onCycleTab(e.key === "ArrowRight" ? 1 : -1);
        return;
      }

      // Enter inside palette input = select
      if (e.key === "Enter" && !isModifierKey(e) && isPaletteInput) {
        e.preventDefault();
        h.onSelect();
        return;
      }

      if (isTypingContext(e.target)) return;

      // Non-typing shortcuts
      if (e.key === ",") {
        e.preventDefault();
        h.onOpenSettings();
        return;
      }
      if (e.key === "Backspace" && e.shiftKey) {
        e.preventDefault();
        h.onClearSession();
      }
    };

    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [h]);
}
