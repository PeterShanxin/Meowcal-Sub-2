import tomllib
from pathlib import Path

from meocosub2.config import AppConfig, config_from_payload, config_to_payload, load_config, save_config


def test_default_config() -> None:
    cfg = AppConfig()
    assert cfg.source_language == "en"
    assert cfg.target_language == "zh"
    assert cfg.capture_interval_ms == 1500
    assert cfg.fuzzy_threshold == 65
    assert cfg.overlay_port == 8765


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    cfg = AppConfig(
        opensubtitles_enable_org_fallback=True,
        source_language="ja",
        target_language="en",
        overlay_font_size=32,
        overlay_theme="glass-cinematic",
        overlay_radius_px=34,
        overlay_shadow_strength=0.6,
    )
    config_file = tmp_path / "config.toml"
    save_config(cfg, config_file)
    loaded = load_config(config_file)
    assert loaded.opensubtitles_enable_org_fallback is True
    assert loaded.source_language == "ja"
    assert loaded.target_language == "en"
    assert loaded.overlay_font_size == 32
    assert loaded.overlay_radius_px == 34
    assert loaded.overlay_shadow_strength == 0.6


def test_load_missing_file_returns_defaults(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg.source_language == "en"


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    cfg = AppConfig()
    config_file = tmp_path / "sub" / "dir" / "config.toml"
    save_config(cfg, config_file)
    assert config_file.exists()


def test_load_invalid_toml_returns_defaults(tmp_path: Path) -> None:
    config_file = tmp_path / "bad.toml"
    config_file.write_text("[broken", encoding="utf-8")
    cfg = load_config(config_file)
    assert cfg == AppConfig()


def test_config_example_contains_all_sections() -> None:
    payload = tomllib.loads(Path("config.example.toml").read_text(encoding="utf-8"))
    assert set(payload) == {"opensubtitles", "languages", "capture", "matching", "translation", "overlay"}


def test_config_to_payload_uses_nested_camel_case_sections() -> None:
    payload = config_to_payload(
        AppConfig(
            overlay_radius_px=36,
            capture_region=[1, 2, 3, 4],
            opensubtitles_enable_org_fallback=True,
        )
    )
    assert payload["capture"]["region"] == [1, 2, 3, 4]
    assert payload["capture"]["ocrLanguage"] == "en-US"
    assert payload["opensubtitles"]["enableOrgFallback"] is True
    assert payload["overlay"]["radiusPx"] == 36
    assert payload["overlay"]["theme"] == "glass-cinematic"


def test_config_from_payload_merges_with_fallback() -> None:
    payload = {
        "opensubtitles": {"enableOrgFallback": "true"},
        "languages": {"source": "it"},
        "overlay": {"fontSize": 40, "maxWidthVw": 72},
    }
    loaded = config_from_payload(payload, fallback=AppConfig(target_language="fr", overlay_blur_px=12))
    assert loaded.opensubtitles_enable_org_fallback is True
    assert loaded.source_language == "it"
    assert loaded.target_language == "fr"
    assert loaded.overlay_font_size == 40
    assert loaded.overlay_max_width_vw == 72
    assert loaded.overlay_blur_px == 12


def test_config_ocr_language_follows_source_language() -> None:
    loaded = config_from_payload({"languages": {"source": "zht"}}, fallback=AppConfig())
    assert loaded.ocr_language == "zh-TW"
