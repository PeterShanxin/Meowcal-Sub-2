"""Keep the repository banner's PNG export current with its SVG artwork."""

from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path

from PIL import Image, PngImagePlugin


def update_branding(root: Path, *, check: bool = False) -> bool:
    svg_path = root / "docs/assets/banner.svg"
    png_path = svg_path.with_suffix(".png")
    source = svg_path.read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    png_current = False
    if png_path.exists():
        try:
            with Image.open(png_path) as image:
                image.verify()
                png_current = image.info.get("SourceSHA256") == digest
        except (OSError, SyntaxError):
            # A damaged export can be regenerated from the editable SVG.
            pass
    if png_current:
        return False
    if check:
        raise ValueError(
            "Banner is stale. Run python scripts/update_branding.py and commit the PNG export."
        )

    # Playwright is already a development dependency; no runtime dependency or
    # external image service is needed to render the editable SVG.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 640}, device_scale_factor=1)
            page.route("**/*", lambda route: route.abort())
            page.set_content("<style>body{margin:0}</style>" + source)
            page.evaluate("document.fonts.ready")
            pixels = page.locator("svg").screenshot()
        finally:
            browser.close()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("SourceSHA256", digest)
    with Image.open(io.BytesIO(pixels)) as image:
        image.save(png_path, pnginfo=metadata)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail without writing if assets are stale."
    )
    args = parser.parse_args()
    changed = update_branding(Path(__file__).resolve().parents[1], check=args.check)
    print("Banner export updated." if changed else "Banner export matches the SVG artwork.")
