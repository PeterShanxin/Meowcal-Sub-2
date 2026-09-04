interface TauriLike {
  core?: { invoke: <T>(cmd: string, args?: Record<string, unknown>) => Promise<T> };
  invoke?: <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;
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

export const tauri = {
  enterLiveMode: () => invokeTauri<void>("enter_live_mode"),
  exitLiveMode: () => invokeTauri<void>("exit_live_mode"),
  openAreaSelector: () => invokeTauri<void>("open_area_selector"),
  closeAreaSelector: () => invokeTauri<void>("close_area_selector"),
  stopTranslation: () => invokeTauri<void>("stop_translation"),
  getApiBase: () => invokeTauri<string>("get_api_base"),
};
