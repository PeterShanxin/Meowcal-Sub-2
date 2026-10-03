from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from scripts.update_branding import update_branding


@pytest.fixture
def branding_root(tmp_path: Path) -> Path:
    assets = tmp_path / "docs/assets"
    assets.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1]
    for name in ("banner.svg", "banner.png"):
        shutil.copyfile(source / "docs/assets" / name, assets / name)
    return tmp_path


def test_version_bump_does_not_invalidate_banner(branding_root: Path) -> None:
    config_path = branding_root / "src-tauri/tauri.conf.json"
    config_path.parent.mkdir()
    config_path.write_text(json.dumps({"version": "9.8.7-rc.1"}), encoding="utf-8")
    svg = branding_root / "docs/assets/banner.svg"
    png = svg.with_suffix(".png")
    original = (svg.read_bytes(), png.read_bytes())
    assert not update_branding(branding_root, check=True)
    assert not update_branding(branding_root)
    assert (svg.read_bytes(), png.read_bytes()) == original


def test_artwork_edit_invalidates_png_export(branding_root: Path) -> None:
    svg = branding_root / "docs/assets/banner.svg"
    png = svg.with_suffix(".png")
    with Image.open(png) as image:
        previous = image.convert("RGB")
    svg.write_text(
        svg.read_text(encoding="utf-8").replace("Subtitles, in your language.", "Updated artwork."),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Banner is stale"):
        update_branding(branding_root, check=True)
    artwork = svg.read_bytes()
    assert update_branding(branding_root)
    assert svg.read_bytes() == artwork
    with Image.open(png) as image:
        assert ImageChops.difference(previous, image.convert("RGB")).getbbox() is not None
        assert "Version" not in image.info
    assert not update_branding(branding_root, check=True)


def test_export_check_does_not_require_app_manifests(branding_root: Path) -> None:
    assert not update_branding(branding_root, check=True)


@pytest.mark.parametrize("damage", ["invalid", "truncated"])
def test_unreadable_png_is_rejected_by_check_and_repaired_by_update(
    branding_root: Path, damage: str
) -> None:
    png = branding_root / "docs/assets/banner.png"
    broken = b"not a PNG" if damage == "invalid" else png.read_bytes()[:100]
    png.write_bytes(broken)
    with pytest.raises(ValueError, match="Banner is stale"):
        update_branding(branding_root, check=True)
    assert png.read_bytes() == broken
    assert update_branding(branding_root)
    with Image.open(png) as image:
        assert image.size == (1280, 640)
        image.verify()
    assert not update_branding(branding_root, check=True)
