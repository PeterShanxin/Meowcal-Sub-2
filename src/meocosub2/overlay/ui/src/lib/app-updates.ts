import { type AppUpdateCheck, tauri } from "../hooks/use-tauri";

export async function requestAppUpdate(
  status: AppUpdateCheck,
  actions: Pick<
    typeof tauri,
    "openStoreUpdate" | "openPortableUpdate" | "installAppUpdate"
  > = tauri,
): Promise<void> {
  if (status.storeUpdateAvailable) {
    await actions.openStoreUpdate();
  } else if (status.portableUpdateVersion) {
    await actions.openPortableUpdate(status.portableUpdateVersion);
  } else if (status.availableVersion) {
    await actions.installAppUpdate(status.availableVersion);
  }
}
