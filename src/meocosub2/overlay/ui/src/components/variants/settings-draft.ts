import { useEffect, useRef, useState } from "react";
import type { BackendConfig } from "../../lib/types";

/**
 * The settings draft, reset whenever the saved config changes. The interface
 * language saves on its own and broadcasts a new config; with unsaved edits
 * pending, only the language is taken from it so those edits survive.
 */
export function useSettingsDraft(initialConfig: BackendConfig) {
  const [draft, setDraft] = useState<BackendConfig>(initialConfig);
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  useEffect(() => {
    if (dirtyRef.current) {
      setDraft((current) => ({ ...current, ui: initialConfig.ui }));
      return;
    }
    setDraft(initialConfig);
    setDirty(false);
  }, [initialConfig]);
  return { draft, setDraft, dirty, setDirty };
}
