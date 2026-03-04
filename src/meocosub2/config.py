"""Configuration loading and saving for MeoCoSub2."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w


@dataclass
class AppConfig:
    opensubtitles_api_key: str = ""
    opensubtitles_username: str = ""
    opensubtitles_password: str = ""
    source_language: str = "en"
    target_language: str = "zh"
    capture_region: list[int] = field(default_factory=list)
    capture_interval_ms: int = 1500
    ocr_language: str = "en"
    fuzzy_threshold: int = 65
    match_window_size: int = 30
    foundry_endpoint: str = "http://127.0.0.1:5273/v1"
    foundry_model: str = ""
    translation_timeout_s: int = 30
    translation_batch_size: int = 5
    overlay_port: int = 8765
    overlay_font_size: int = 28
    overlay_font_family: str = "Segoe UI"
    overlay_text_color: str = "#FFFFFF"
    overlay_bg_color: str = "rgba(0,0,0,0.75)"
    overlay_position: str = "bottom"


def default_config_path() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home()))
    return Path(appdata) / "meocosub2" / "config.toml"


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or default_config_path()
    try:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return AppConfig()
    except tomllib.TOMLDecodeError:
        return AppConfig()

    return AppConfig(
        opensubtitles_api_key=data.get("opensubtitles", {}).get("api_key", ""),
        opensubtitles_username=data.get("opensubtitles", {}).get("username", ""),
        opensubtitles_password=data.get("opensubtitles", {}).get("password", ""),
        source_language=data.get("languages", {}).get("source", "en"),
        target_language=data.get("languages", {}).get("target", "zh"),
        capture_region=data.get("capture", {}).get("region", []),
        capture_interval_ms=data.get("capture", {}).get("interval_ms", 1500),
        ocr_language=data.get("capture", {}).get("ocr_language", "en"),
        fuzzy_threshold=data.get("matching", {}).get("fuzzy_threshold", 65),
        match_window_size=data.get("matching", {}).get("window_size", 30),
        foundry_endpoint=data.get("translation", {}).get("endpoint", "http://127.0.0.1:5273/v1"),
        foundry_model=data.get("translation", {}).get("model", ""),
        translation_timeout_s=data.get("translation", {}).get("timeout_s", 30),
        translation_batch_size=data.get("translation", {}).get("batch_size", 5),
        overlay_port=data.get("overlay", {}).get("port", 8765),
        overlay_font_size=data.get("overlay", {}).get("font_size", 28),
        overlay_font_family=data.get("overlay", {}).get("font_family", "Segoe UI"),
        overlay_text_color=data.get("overlay", {}).get("text_color", "#FFFFFF"),
        overlay_bg_color=data.get("overlay", {}).get("bg_color", "rgba(0,0,0,0.75)"),
        overlay_position=data.get("overlay", {}).get("position", "bottom"),
    )


def save_config(config: AppConfig, path: Path | None = None) -> None:
    config_path = path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "opensubtitles": {
            "api_key": config.opensubtitles_api_key,
            "username": config.opensubtitles_username,
            "password": config.opensubtitles_password,
        },
        "languages": {
            "source": config.source_language,
            "target": config.target_language,
        },
        "capture": {
            "region": config.capture_region,
            "interval_ms": config.capture_interval_ms,
            "ocr_language": config.ocr_language,
        },
        "matching": {
            "fuzzy_threshold": config.fuzzy_threshold,
            "window_size": config.match_window_size,
        },
        "translation": {
            "endpoint": config.foundry_endpoint,
            "model": config.foundry_model,
            "timeout_s": config.translation_timeout_s,
            "batch_size": config.translation_batch_size,
        },
        "overlay": {
            "port": config.overlay_port,
            "font_size": config.overlay_font_size,
            "font_family": config.overlay_font_family,
            "text_color": config.overlay_text_color,
            "bg_color": config.overlay_bg_color,
            "position": config.overlay_position,
        },
    }
    with config_path.open("wb") as handle:
        tomli_w.dump(payload, handle)
