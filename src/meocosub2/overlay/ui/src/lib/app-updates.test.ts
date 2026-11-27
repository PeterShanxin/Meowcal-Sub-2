import { describe, expect, it, vi } from "vitest";
import type { AppUpdateCheck } from "../hooks/use-tauri";
import { checkStartupUpdate, requestAppUpdate } from "./app-updates";

const current: AppUpdateCheck = {
  enabled: true,
  currentVersion: "0.4.0",
  availableVersion: null,
  storeUpdateAvailable: false,
  portableUpdateVersion: null,
  reason: null,
};

describe("startup update check", () => {
  it("checks once in 24 hours across launches; manual checks bypass the gate", async () => {
    const saved = new Map<string, string>();
    const storage = {
      getItem: (key: string) => saved.get(key) ?? null,
      setItem: (key: string, value: string) => saved.set(key, value),
    };
    const check = vi.fn(async () => current);
    const now = Date.UTC(2026, 10, 28);
    expect(await checkStartupUpdate(storage, now, check)).toEqual(current);
    expect(await checkStartupUpdate(storage, now + 23 * 3600_000, check)).toBeNull();
    expect(check).toHaveBeenCalledTimes(1);
    expect(await check()).toEqual(current);
    expect(await checkStartupUpdate(storage, now + 24 * 3600_000, check)).toEqual(current);
    expect(check).toHaveBeenCalledTimes(3);
  });

  it("does not retry automatically each launch when a check is unavailable", async () => {
    let lastCheck: string | null = null;
    const storage = {
      getItem: () => lastCheck,
      setItem: (_key: string, value: string) => {
        lastCheck = value;
      },
    };
    const check = vi.fn(() => Promise.reject(new Error("Offline")));
    await expect(checkStartupUpdate(storage, 1000, check)).rejects.toThrow("Offline");
    expect(await checkStartupUpdate(storage, 2000, check)).toBeNull();
    expect(check).toHaveBeenCalledTimes(1);
  });
});

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
