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
    (tmp_path / "src-tauri").mkdir()
    shutil.copyfile(source / "src-tauri/tauri.conf.json", tmp_path / "src-tauri/tauri.conf.json")
    return tmp_path


def test_version_bump_refreshes_both_assets_without_rewriting_current_files(
    branding_root: Path,
) -> None:
    config_path = branding_root / "src-tauri/tauri.conf.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["version"] = "9.8.7-rc.1"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    svg = branding_root / "docs/assets/banner.svg"
    png = svg.with_suffix(".png")
    original = (svg.read_bytes(), png.read_bytes())
    with pytest.raises(ValueError, match="Banner is stale"):
        update_branding(branding_root, check=True)
    assert (svg.read_bytes(), png.read_bytes()) == original
    with Image.open(png) as image:
        previous_label = image.convert("RGB").crop((950, 550, 1220, 590))

    assert update_branding(branding_root)
    assert ">v9.8.7-rc.1</text>" in svg.read_text(encoding="utf-8")
    with Image.open(png) as image:
        assert image.size == (1280, 640)
        assert image.info["Version"] == "9.8.7-rc.1"
        label = image.convert("RGB").crop((950, 550, 1220, 590))
        assert ImageChops.difference(previous_label, label).getbbox() is not None
    current = (svg.read_bytes(), png.read_bytes())
    assert not update_branding(branding_root, check=True)
    assert not update_branding(branding_root)
    assert (svg.read_bytes(), png.read_bytes()) == current


def test_artwork_edit_invalidates_png_export(branding_root: Path) -> None:
    svg = branding_root / "docs/assets/banner.svg"
    svg.write_text(
        svg.read_text(encoding="utf-8").replace("Subtitles, in your language.", "Updated artwork."),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Banner is stale"):
        update_branding(branding_root, check=True)


def test_missing_version_marker_does_not_overwrite_artwork(branding_root: Path) -> None:
    svg = branding_root / "docs/assets/banner.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    original = svg.read_bytes()
    with pytest.raises(ValueError, match="exactly one release-version"):
        update_branding(branding_root)
    assert svg.read_bytes() == original


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
