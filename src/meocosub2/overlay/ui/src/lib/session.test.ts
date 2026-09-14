import { afterEach, beforeEach, expect, it, vi } from "vitest";

beforeEach(() => vi.resetModules());
afterEach(() => vi.unstubAllGlobals());

function browser(href: string, desktop = false, injectedToken?: string) {
  const location = { href };
  vi.stubGlobal("window", {
    location,
    __TAURI__: desktop ? {} : undefined,
    __MEOWCAL__: { token: injectedToken },
    history: {
      replaceState: (_state: unknown, _title: string, next: string) => (location.href = next),
    },
  });
  return location;
}

it("keeps the desktop navigation authenticated when WebView2 reloads", async () => {
  const location = browser("http://127.0.0.1:8765/?token=fixture&desktopLaunch=1", true);
  const session = await import("./session");
  expect(new URL(location.href).searchParams.get("token")).toBe("fixture");
  expect(session.accessToken).toBe("fixture");
});

it("removes only the browser address-bar token and uses the injected run token", async () => {
  const location = browser(
    "http://127.0.0.1:8765/?token=fixture&view=studio",
    false,
    "current/run",
  );
  const session = await import("./session");
  expect(location.href).toBe("http://127.0.0.1:8765/?view=studio");
  expect(session.withToken("/ws/app?view=studio")).toBe("/ws/app?view=studio&token=current%2Frun");
  expect(session.withToken("/ws/app")).toBe("/ws/app?token=current%2Frun");
});

it("does not invent a token for an unauthenticated page", async () => {
  browser("http://127.0.0.1:8765/");
  const session = await import("./session");
  expect(session.accessToken).toBe("");
  expect(session.withToken("/ws/app")).toBe("/ws/app");
});
