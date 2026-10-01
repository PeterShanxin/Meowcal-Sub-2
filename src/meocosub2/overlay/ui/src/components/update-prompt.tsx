import { useEffect, useState } from "react";
import { isTauri, tauri } from "../hooks/use-tauri";

export function UpdatePrompt({ visible }: { visible: boolean }): JSX.Element | null {
  const [version, setVersion] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isTauri()) return;
    let cancelled = false;
    void tauri
      .checkAppUpdate()
      .then((result) => {
        if (!cancelled) setVersion(result?.availableVersion ?? null);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (!visible || dismissed || !version) return null;

  const install = async (): Promise<void> => {
    setInstalling(true);
    setError(null);
    try {
      await tauri.installAppUpdate(version);
    } catch (caught: unknown) {
      setError(String(caught));
    } finally {
      setInstalling(false);
    }
  };

  return (
    <aside
      aria-label="App update"
      style={{
        position: "absolute",
        bottom: 20,
        right: 20,
        zIndex: 32,
        width: "min(360px, calc(100vw - 40px))",
        padding: 16,
        borderRadius: 10,
        border: "1px solid var(--accent-ring)",
        background: "#1e1e27",
        boxShadow: "0 16px 40px rgba(0,0,0,0.35)",
      }}
    >
      <div role="status" style={{ fontWeight: 700 }}>
        Meowcal Sub 2 v{version} is available
      </div>
      <p style={{ margin: "8px 0 12px", fontSize: 12, color: "var(--text-muted)" }}>
        Install the signed update and restart the app. Your settings and downloads stay in place.
      </p>
      {error && <p style={{ color: "var(--danger-text)", fontSize: 12 }}>{error}</p>}
      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" disabled={installing} onClick={() => void install()}>
          {installing ? "Installing…" : "Install update"}
        </button>
        <button type="button" disabled={installing} onClick={() => setDismissed(true)}>
          Later
        </button>
      </div>
    </aside>
  );
}
