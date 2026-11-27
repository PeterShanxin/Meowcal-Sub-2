import { type AppUpdateCheck, tauri } from "../hooks/use-tauri";

const LAST_STARTUP_CHECK = "meowcal-sub-2:last-startup-update-check";
const DAY_MS = 24 * 60 * 60 * 1000;

export function checkStartupUpdate(
  storage: Pick<Storage, "getItem" | "setItem">,
  now: number,
  check: () => Promise<AppUpdateCheck | null> = tauri.checkAppUpdate,
): Promise<AppUpdateCheck | null> {
  const previous = Number(storage.getItem(LAST_STARTUP_CHECK));
  if (previous > 0 && now >= previous && now - previous < DAY_MS) {
    return Promise.resolve(null);
  }
  storage.setItem(LAST_STARTUP_CHECK, String(now));
  return check();
}

export function requestAppUpdate(
  status: AppUpdateCheck,
  actions: Pick<typeof tauri, "openStoreUpdate" | "openPortableUpdate" | "installAppUpdate"> = tauri,
): Promise<void | null> {
  if (status.storeUpdateAvailable) return actions.openStoreUpdate();
  if (status.portableUpdateVersion) return actions.openPortableUpdate(status.portableUpdateVersion);
  if (status.availableVersion) return actions.installAppUpdate(status.availableVersion);
  return Promise.resolve(null);
}
