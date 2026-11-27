import { useState } from "react";
import { type AppUpdateCheck, tauri } from "../../hooks/use-tauri";
import { localizeError, localizeMessage, t } from "../../i18n";
import { requestAppUpdate } from "../../lib/app-updates";

export function UpdatesSection(): JSX.Element {
  const [status, setStatus] = useState<AppUpdateCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const check = async (): Promise<void> => {
    setChecking(true);
    setStatus(null);
    setError(null);
    try {
      const result = await tauri.checkAppUpdate();
      if (result) setStatus(result);
    } catch (caught: unknown) {
      setError(String(caught));
    } finally {
      setChecking(false);
    }
  };

  const install = async (update: AppUpdateCheck): Promise<void> => {
    setInstalling(true);
    setError(null);
    try {
      await requestAppUpdate(update);
    } catch (caught: unknown) {
      setError(String(caught));
    } finally {
      setInstalling(false);
    }
  };
  const available = status?.storeUpdateAvailable || status?.portableUpdateVersion || status?.availableVersion;

  return (
    <section style={{ display: "grid", gap: 16 }}>
      <div>
        <h2 style={{ margin: "0 0 6px" }}>{t("App updates")}</h2>
        <p style={{ color: "var(--text-muted)", fontSize: 13, margin: 0 }}>
          {t("The app checks for updates at most once a day when it opens.")}
        </p>
      </div>
      {status && (
        <p style={{ margin: 0, fontSize: 13 }}>
          {t("Version {version}.", { version: status.currentVersion })}{" "}
          {status.storeUpdateAvailable
            ? t("A Microsoft Store update is available.")
            : status.portableUpdateVersion
              ? t("Portable version {version} is available.", { version: status.portableUpdateVersion })
              : status.availableVersion
              ? t("Version {version} is ready to install.", { version: status.portableUpdateVersion
              ? t("Portable version {version} is available.", { version: status.portableUpdateVersion })
              : status.availableVersion })
              : status.enabled
                ? t("You are up to date.")
                : localizeMessage(status.reason ?? "")}
        </p>
      )}
      {error && <p style={{ margin: 0, color: "var(--danger-text)" }}>{localizeError(error)}</p>}
      <div style={{ display: "flex", gap: 10 }}>
        <button type="button" disabled={checking || installing} onClick={() => void check()}>
          {checking ? t("Checking…") : t("Check for updates")}
        </button>
        {status && available && (
          <button
            type="button"
            disabled={checking || installing}
            onClick={() => void install(status)}
          >
            {status.storeUpdateAvailable
              ? t("Open Microsoft Store")
              : status.portableUpdateVersion
                ? t("Open GitHub Releases")
                : installing
                ? t("Installing…")
                : t("Install update")}
          </button>
        )}
      </div>
    </section>
  );
}
