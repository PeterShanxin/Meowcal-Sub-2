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

      // Tab / Shift+Tab — cycle palette tabs (when not typing in a non-palette input)
      if (e.key === "Tab" && !e.altKey && !e.ctrlKey && !e.metaKey) {
        const target = e.target as HTMLElement | null;
        if (target instanceof HTMLInputElement && target.dataset.palette === "true") {
          e.preventDefault();
          h.onCycleTab(e.shiftKey ? -1 : 1);
          return;
        }
      }

      // Arrow navigation inside palette input
      if (
        (e.key === "ArrowDown" || e.key === "ArrowUp") &&
        e.target instanceof HTMLInputElement &&
        e.target.dataset.palette === "true"
      ) {
        e.preventDefault();
        h.onMoveCursor(e.key === "ArrowDown" ? 1 : -1);
        return;
      }

      // Enter inside palette input = select
      if (
        e.key === "Enter" &&
        !isModifierKey(e) &&
        e.target instanceof HTMLInputElement &&
        e.target.dataset.palette === "true"
      ) {
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
