import { type JSX, useEffect, useState } from "react";
import { type AppUpdateCheck, isTauri, tauri } from "../hooks/use-tauri";
import { localizeError, t } from "../i18n";
import { requestAppUpdate } from "../lib/app-updates";

export function UpdatePrompt({ visible }: { visible: boolean }): JSX.Element | null {
  const [status, setStatus] = useState<AppUpdateCheck | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isTauri()) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void tauri
        .checkAppUpdate(true)
        .then((result) => {
          if (!cancelled) setStatus(result);
        })
        .catch(() => undefined);
    }, 2000);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, []);

  if (
    !visible ||
    dismissed ||
    !status ||
    !(status.storeUpdateAvailable || status.portableUpdateVersion || status.availableVersion)
  )
    return null;
  const store = status.storeUpdateAvailable;
  const portable = status.portableUpdateVersion;

  const install = async (): Promise<void> => {
    setInstalling(true);
    setError(null);
    try {
      await requestAppUpdate(status);
      if (store || portable) setDismissed(true);
    } catch (caught: unknown) {
      setError(String(caught));
    } finally {
      setInstalling(false);
    }
  };

  return (
    <aside
      aria-label={t("App update")}
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
        {store
          ? t("A Microsoft Store update is available.")
          : t("Meowcal Sub 2 v{version} is available", {
              version: portable ?? status.availableVersion ?? "",
            })}
      </div>
      {!store && !portable && (
        <p style={{ margin: "8px 0 12px", fontSize: 12, color: "var(--text-muted)" }}>
          {t(
            "Install the signed update and restart the app. Your settings and downloads stay in place.",
          )}
        </p>
      )}
      {error && <p style={{ color: "var(--danger-text)", fontSize: 12 }}>{localizeError(error)}</p>}
      <div style={{ display: "flex", gap: 8, marginTop: store || portable ? 12 : 0 }}>
        <button type="button" disabled={installing} onClick={() => void install()}>
          {store
            ? t("Open Microsoft Store")
            : portable
              ? t("Open GitHub Releases")
              : installing
                ? t("Installing…")
                : t("Install update")}
        </button>
        <button type="button" disabled={installing} onClick={() => setDismissed(true)}>
          {t("Later")}
        </button>
      </div>
    </aside>
  );
}
