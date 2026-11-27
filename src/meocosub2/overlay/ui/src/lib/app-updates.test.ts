import { describe, expect, it, vi } from "vitest";
import type { AppUpdateCheck } from "../hooks/use-tauri";
import { requestAppUpdate } from "./app-updates";

const current: AppUpdateCheck = {
  enabled: true,
  currentVersion: "0.4.0",
  availableVersion: null,
  storeUpdateAvailable: false,
  portableUpdateVersion: null,
  reason: null,
};

describe("update actions", () => {
  it("opens the Store only when a Store package update is available", async () => {
    const actions = {
      openPortableUpdate: vi.fn(async () => undefined),
      openStoreUpdate: vi.fn(async () => undefined),
      installAppUpdate: vi.fn(async () => undefined),
    };
    await requestAppUpdate(current, actions);
    expect(actions.openStoreUpdate).not.toHaveBeenCalled();
    expect(actions.installAppUpdate).not.toHaveBeenCalled();
    await requestAppUpdate({ ...current, storeUpdateAvailable: true }, actions);
    expect(actions.openStoreUpdate).toHaveBeenCalledOnce();
    await requestAppUpdate({ ...current, portableUpdateVersion: "0.4.2" }, actions);
    expect(actions.openPortableUpdate).toHaveBeenCalledWith("0.4.2");
    expect(actions.installAppUpdate).not.toHaveBeenCalled();
  });

  it("routes the GitHub installer to the exact signed version", async () => {
    const actions = {
      openPortableUpdate: vi.fn(async () => undefined),
      openStoreUpdate: vi.fn(async () => undefined),
      installAppUpdate: vi.fn(async () => undefined),
    };
    await requestAppUpdate({ ...current, availableVersion: "0.5.0" }, actions);
    expect(actions.installAppUpdate).toHaveBeenCalledWith("0.5.0");
    expect(actions.openStoreUpdate).not.toHaveBeenCalled();
  });
});
