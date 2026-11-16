# Brand assets

The mark is a pair of subtitle cards on a dark tile, drawn in gold line art. The
front card holds the subtitle being read and the back card holds its
translation. The signal arc at the top left and the four-point sparkle at the top
right replace the cat ears of the earlier mark. Use the full name
**Meowcal Sub 2** in English and **Meowcal Sub 2 · 妙影2** in Simplified Chinese.
In Chinese running text, the short name is **妙影2**, with no space.

- `icon.svg` is the canonical source for the application icon. The studio and
  splash use the same artwork as `src/meocosub2/overlay/static/mark.svg`.
- `icon-16.svg` and `icon-32.svg` are hand-fitted to the pixel grid for small
  sizes, where the full artwork's thin gradient lines blur: the 16 px version is
  drawn in whole pixels with flat gold, and the 32 px version uses 2 px strokes.
  Use them for those sizes and the full `icon.svg` from 48 px up.
- `icon.png` and the packaged icons in `src-tauri/icons/` are renders of these
  sources. Render each size from an SVG rather than scaling a large PNG down.
  `icon.ico` holds 16 px from `icon-16.svg`, 24 and 32 px from `icon-32.svg`,
  and 48, 64, 128 and 256 px from `icon.svg`, all as PNG entries; `32x32.png`
  is rendered from `icon-32.svg`.
- `wordmark.svg` and `wordmark.zh-CN.svg` are the English and Chinese lockups for
  dark backgrounds. The text stays editable; use Segoe UI and Microsoft YaHei.
- `banner.svg` and `banner.zh-CN.svg` head `README.md` and `README.zh-CN.md`.
  After you edit either SVG, run `python scripts/update_branding.py` to refresh
  its PNG export. Verification rejects a stale export.
