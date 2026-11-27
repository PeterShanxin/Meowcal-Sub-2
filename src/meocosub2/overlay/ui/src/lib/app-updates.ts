import { type AppUpdateCheck, tauri } from "../hooks/use-tauri";

export function requestAppUpdate(
  status: AppUpdateCheck,
  actions: Pick<
    typeof tauri,
    "openStoreUpdate" | "openPortableUpdate" | "installAppUpdate"
  > = tauri,
): Promise<void | null> {
  if (status.storeUpdateAvailable) return actions.openStoreUpdate();
  if (status.portableUpdateVersion) return actions.openPortableUpdate(status.portableUpdateVersion);
  if (status.availableVersion) return actions.installAppUpdate(status.availableVersion);
  return Promise.resolve(null);
}
