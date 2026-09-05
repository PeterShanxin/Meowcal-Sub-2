type UnlistenFn = () => void;

interface TauriLike {
  core?: { invoke: <T>(cmd: string, args?: Record<string, unknown>) => Promise<T> };
  invoke?: <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;
  event?: {
    listen: (event: string, handler: (payload: unknown) => void) => Promise<UnlistenFn>;
  };
}

function getTauri(): TauriLike | null {
  const w = window as unknown as { __TAURI__?: TauriLike };
  return w.__TAURI__ ?? null;
}

export function isTauri(): boolean {
  return getTauri() !== null;
}

export async function invokeTauri<T>(
  cmd: string,
  args?: Record<string, unknown>,
): Promise<T | null> {
  const t = getTauri();
  if (!t) return null;
  const fn = t.core?.invoke ?? t.invoke;
  if (!fn) return null;
  return fn<T>(cmd, args);
}

/** Subscribes to a shell event, or resolves null outside the desktop shell. */
export async function listenTauri(
  event: string,
  handler: (payload: unknown) => void,
): Promise<UnlistenFn | null> {
  const listen = getTauri()?.event?.listen;
  if (!listen) return null;
  return listen(event, handler);
}

export const tauri = {
  enterLiveMode: (region: number[]) =>
    invokeTauri<void>("enter_live_mode", { region }),
  exitLiveMode: () => invokeTauri<void>("exit_live_mode"),
  setDockSize: (widthCss: number, heightCss: number) =>
    invokeTauri<void>("set_dock_size", { widthCss, heightCss }),
  openAreaSelector: () => invokeTauri<void>("open_area_selector"),
  stopTranslation: () => invokeTauri<void>("stop_translation"),
  getApiBase: () => invokeTauri<string>("get_api_base"),
  listen: listenTauri,
};
