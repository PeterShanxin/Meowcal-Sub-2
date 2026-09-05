const STORAGE_KEY = "meocosub2.fontScale";

export const FONT_PRESETS = {
  compact: 0.88,
  default: 1,
  comfortable: 1.12,
  large: 1.25,
} as const;

export type FontPresetName = keyof typeof FONT_PRESETS;

const PRESET_LABELS: Record<FontPresetName, string> = {
  compact: "Compact",
  default: "Default",
  comfortable: "Comfortable",
  large: "Large",
};

export function presetLabel(name: FontPresetName): string {
  return PRESET_LABELS[name];
}

function apply(scale: number): void {
  const el = document.documentElement as HTMLElement & {
    style: CSSStyleDeclaration & { zoom?: string };
  };
  el.style.zoom = String(scale);
}

export function loadFontScale(): FontPresetName {
  const v = localStorage.getItem(STORAGE_KEY);
  if (v && v in FONT_PRESETS) return v as FontPresetName;
  return "default";
}

export function setFontScale(name: FontPresetName): void {
  localStorage.setItem(STORAGE_KEY, name);
  apply(FONT_PRESETS[name]);
  window.dispatchEvent(new CustomEvent("font-scale-change", { detail: name }));
}

export function applyFontScale(): void {
  apply(FONT_PRESETS[loadFontScale()]);
}
