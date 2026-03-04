import tomllib
from pathlib import Path

from meocosub2.config import AppConfig, load_config, save_config


def test_default_config() -> None:
    cfg = AppConfig()
    assert cfg.source_language == "en"
    assert cfg.target_language == "zh"
    assert cfg.capture_interval_ms == 1500
    assert cfg.fuzzy_threshold == 65
    assert cfg.overlay_port == 8765


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    cfg = AppConfig(source_language="ja", target_language="en", overlay_font_size=32)
    config_file = tmp_path / "config.toml"
    save_config(cfg, config_file)
    loaded = load_config(config_file)
    assert loaded.source_language == "ja"
    assert loaded.target_language == "en"
    assert loaded.overlay_font_size == 32


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
