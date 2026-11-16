# Brand assets

The mark is a pair of subtitle cards on a dark tile, drawn in gold line art. The
front card holds the subtitle being read and the back card holds its
translation. The signal arc at the top left and the four-point sparkle at the top
right replace the cat ears of the earlier mark. Use the full name
**Meowcal Sub 2** in English and **Meowcal Sub 2 · 妙影2** in Simplified Chinese.
In Chinese running text, the short name is **妙影2**, with no space.

- `icon.svg` is the canonical source for the application icon. The studio and
  splash use the same artwork as `src/meocosub2/overlay/static/mark.svg`.
- `icon.png` and the packaged icons in `src-tauri/icons/` are renders of
  `icon.svg`. Render each size from the SVG rather than scaling a large PNG
  down; `icon.ico` holds 16, 24, 32, 48, 64, 128 and 256 px PNG entries.
- `wordmark.svg` and `wordmark.zh-CN.svg` are the English and Chinese lockups for
  dark backgrounds. The text stays editable; use Segoe UI and Microsoft YaHei.
- `banner.svg` and `banner.zh-CN.svg` head `README.md` and `README.zh-CN.md`.
  After you edit either SVG, run `python scripts/update_branding.py` to refresh
  its PNG export. Verification rejects a stale export.
