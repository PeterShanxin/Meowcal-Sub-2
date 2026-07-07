"""Configuration loading and saving for Meowcal-Sub-2."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

from meocosub2.languages import derive_ocr_language, normalize_source_language, normalize_target_language


@dataclass
class AppConfig:
    opensubtitles_enabled: bool = True
    opensubtitles_api_key: str = ""
    opensubtitles_username: str = ""
    opensubtitles_password: str = ""
    opensubtitles_enable_org_fallback: bool = False
    subdl_enabled: bool = True
    subdl_api_key: str = ""
    assrt_enabled: bool = False
    assrt_token: str = ""
    tmdb_api_key: str = ""
    tmdb_merge_enabled: bool = True
    search_provider_timeout_s: int = 20
    source_language: str = "en"
    target_language: str = "zh"
    capture_region: list[int] = field(default_factory=list)
    capture_interval_ms: int = 1500
    ocr_language: str = "en-US"
    fuzzy_threshold: int = 65
    match_window_size: int = 30
    match_window_backward: int = 5
    foundry_endpoint: str = "http://127.0.0.1:5273/v1"
    foundry_model: str = ""
    translation_timeout_s: int = 30
    translation_batch_size: int = 5
    overlay_port: int = 8765
    overlay_font_size: int = 28
    overlay_font_family: str = "Aptos"
    overlay_text_color: str = "#FFFFFF"
    overlay_bg_color: str = "rgba(0,0,0,0.75)"
    overlay_position: str = "bottom"
    overlay_theme: str = "glass-cinematic"
    overlay_radius_px: int = 28
    overlay_padding_px: int = 20
    overlay_max_width_vw: int = 78
    overlay_blur_px: int = 20
    overlay_shadow_strength: float = 0.45
    overlay_offset_pct: int = 10
    overlay_animation_ms: int = 220
    debug_mode: bool = False


def default_config_path() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home()))
    return Path(appdata) / "meowcal-sub-2" / "config.toml"


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or default_config_path()
    try:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return AppConfig()
    except tomllib.TOMLDecodeError:
        return AppConfig()

    # New config writes live under subtitle_sources, but older local installs may
    # still carry a top-level [opensubtitles] section.
    subtitle_sources = data.get("subtitle_sources", {})
    if not isinstance(subtitle_sources, dict):
        subtitle_sources = {}

    opensubtitles = subtitle_sources.get("opensubtitles", {})
    legacy_opensubtitles = data.get("opensubtitles", {})
    subdl = subtitle_sources.get("subdl", {})
    assrt = subtitle_sources.get("assrt", {})
    tmdb = subtitle_sources.get("tmdb", {})
    if not isinstance(opensubtitles, dict):
        opensubtitles = {}
    if not isinstance(legacy_opensubtitles, dict):
        legacy_opensubtitles = {}
    if not isinstance(subdl, dict):
        subdl = {}
    if not isinstance(assrt, dict):
        assrt = {}
    if not isinstance(tmdb, dict):
        tmdb = {}

    source_language = normalize_source_language(data.get("languages", {}).get("source", "en"))
    target_language = normalize_target_language(data.get("languages", {}).get("target", "zh"))
    ocr_language = str(data.get("capture", {}).get("ocr_language", "")) or derive_ocr_language(source_language)

    return AppConfig(
        opensubtitles_enabled=_coerce_bool(
            opensubtitles.get("enabled", legacy_opensubtitles.get("enabled", True)),
            True,
        ),
        opensubtitles_api_key=str(opensubtitles.get("api_key", legacy_opensubtitles.get("api_key", ""))),
        opensubtitles_username=str(opensubtitles.get("username", legacy_opensubtitles.get("username", ""))),
        opensubtitles_password=str(opensubtitles.get("password", legacy_opensubtitles.get("password", ""))),
        opensubtitles_enable_org_fallback=_coerce_bool(
            opensubtitles.get("enable_org_fallback", legacy_opensubtitles.get("enable_org_fallback", False)),
            False,
        ),
        subdl_enabled=_coerce_bool(subdl.get("enabled", True), True),
        subdl_api_key=str(subdl.get("api_key", "")),
        assrt_enabled=_coerce_bool(assrt.get("enabled", False), False),
        assrt_token=str(assrt.get("token", "")),
        tmdb_api_key=str(tmdb.get("api_key", "")),
        tmdb_merge_enabled=_coerce_bool(tmdb.get("merge_enabled", True), True),
        search_provider_timeout_s=_coerce_int(subtitle_sources.get("provider_timeout_s", 20), 20),
        source_language=source_language,
        target_language=target_language,
        capture_region=data.get("capture", {}).get("region", []),
        capture_interval_ms=data.get("capture", {}).get("interval_ms", 1500),
        ocr_language=derive_ocr_language(source_language, ocr_language),
        fuzzy_threshold=data.get("matching", {}).get("fuzzy_threshold", 65),
        match_window_size=data.get("matching", {}).get("window_size", 30),
        match_window_backward=data.get("matching", {}).get("window_backward", 5),
        foundry_endpoint=data.get("translation", {}).get("endpoint", "http://127.0.0.1:5273/v1"),
        foundry_model=data.get("translation", {}).get("model", ""),
        translation_timeout_s=data.get("translation", {}).get("timeout_s", 30),
        translation_batch_size=data.get("translation", {}).get("batch_size", 5),
        overlay_port=data.get("overlay", {}).get("port", 8765),
        overlay_font_size=data.get("overlay", {}).get("font_size", 28),
        overlay_font_family=data.get("overlay", {}).get("font_family", "Aptos"),
        overlay_text_color=data.get("overlay", {}).get("text_color", "#FFFFFF"),
        overlay_bg_color=data.get("overlay", {}).get("bg_color", "rgba(0,0,0,0.75)"),
        overlay_position=data.get("overlay", {}).get("position", "bottom"),
        overlay_theme=data.get("overlay", {}).get("theme", "glass-cinematic"),
        overlay_radius_px=data.get("overlay", {}).get("radius_px", 28),
        overlay_padding_px=data.get("overlay", {}).get("padding_px", 20),
        overlay_max_width_vw=data.get("overlay", {}).get("max_width_vw", 78),
        overlay_blur_px=data.get("overlay", {}).get("blur_px", 20),
        overlay_shadow_strength=data.get("overlay", {}).get("shadow_strength", 0.45),
        overlay_offset_pct=data.get("overlay", {}).get("offset_pct", 10),
        overlay_animation_ms=data.get("overlay", {}).get("animation_ms", 220),
        debug_mode=_coerce_bool(data.get("debug", {}).get("mode", False), False),
    )


def save_config(config: AppConfig, path: Path | None = None) -> None:
    config_path = path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "subtitle_sources": {
            # Scalar keys must precede subtables so the emitted TOML stays valid.
            "provider_timeout_s": config.search_provider_timeout_s,
            "opensubtitles": {
                "enabled": config.opensubtitles_enabled,
                "api_key": config.opensubtitles_api_key,
                "username": config.opensubtitles_username,
                "password": config.opensubtitles_password,
                "enable_org_fallback": config.opensubtitles_enable_org_fallback,
            },
            "subdl": {
                "enabled": config.subdl_enabled,
                "api_key": config.subdl_api_key,
            },
            "assrt": {
                "enabled": config.assrt_enabled,
                "token": config.assrt_token,
            },
            "tmdb": {
                "api_key": config.tmdb_api_key,
                "merge_enabled": config.tmdb_merge_enabled,
            },
        },
        # Keep the legacy mirror for one release to preserve older tooling.
        "opensubtitles": {
            "enabled": config.opensubtitles_enabled,
            "api_key": config.opensubtitles_api_key,
            "username": config.opensubtitles_username,
            "password": config.opensubtitles_password,
            "enable_org_fallback": config.opensubtitles_enable_org_fallback,
        },
        "languages": {
            "source": config.source_language,
            "target": config.target_language,
        },
        "capture": {
            "region": config.capture_region,
            "interval_ms": config.capture_interval_ms,
            "ocr_language": derive_ocr_language(config.source_language, config.ocr_language),
        },
        "matching": {
            "fuzzy_threshold": config.fuzzy_threshold,
            "window_size": config.match_window_size,
            "window_backward": config.match_window_backward,
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
            "theme": config.overlay_theme,
            "radius_px": config.overlay_radius_px,
            "padding_px": config.overlay_padding_px,
            "max_width_vw": config.overlay_max_width_vw,
            "blur_px": config.overlay_blur_px,
            "shadow_strength": config.overlay_shadow_strength,
            "offset_pct": config.overlay_offset_pct,
            "animation_ms": config.overlay_animation_ms,
        },
        "debug": {
            "mode": config.debug_mode,
        },
    }
    with config_path.open("wb") as handle:
        tomli_w.dump(payload, handle)


def overlay_style_payload(config: AppConfig) -> dict[str, object]:
    return {
        "theme": config.overlay_theme,
        "fontSize": config.overlay_font_size,
        "fontFamily": config.overlay_font_family,
        "textColor": config.overlay_text_color,
        "bgColor": config.overlay_bg_color,
        "position": config.overlay_position,
        "radiusPx": config.overlay_radius_px,
        "paddingPx": config.overlay_padding_px,
        "maxWidthVw": config.overlay_max_width_vw,
        "blurPx": config.overlay_blur_px,
        "shadowStrength": config.overlay_shadow_strength,
        "offsetPct": config.overlay_offset_pct,
        "animationMs": config.overlay_animation_ms,
    }


def config_to_payload(config: AppConfig) -> dict[str, object]:
    return {
        "subtitleSources": {
            "providerTimeoutS": config.search_provider_timeout_s,
            "opensubtitles": {
                "enabled": config.opensubtitles_enabled,
                "apiKey": config.opensubtitles_api_key,
                "username": config.opensubtitles_username,
                "password": config.opensubtitles_password,
                "enableOrgFallback": config.opensubtitles_enable_org_fallback,
            },
            "subdl": {
                "enabled": config.subdl_enabled,
                "apiKey": config.subdl_api_key,
            },
            "assrt": {
                "enabled": config.assrt_enabled,
                "token": config.assrt_token,
            },
            "tmdb": {
                "apiKey": config.tmdb_api_key,
                "mergeEnabled": config.tmdb_merge_enabled,
            },
        },
        "opensubtitles": {
            "enabled": config.opensubtitles_enabled,
            "apiKey": config.opensubtitles_api_key,
            "username": config.opensubtitles_username,
            "password": config.opensubtitles_password,
            "enableOrgFallback": config.opensubtitles_enable_org_fallback,
        },
        "languages": {
            "source": config.source_language,
            "target": config.target_language,
        },
        "capture": {
            "region": list(config.capture_region),
            "intervalMs": config.capture_interval_ms,
            "ocrLanguage": derive_ocr_language(config.source_language, config.ocr_language),
        },
        "matching": {
            "fuzzyThreshold": config.fuzzy_threshold,
            "windowSize": config.match_window_size,
            "windowBackward": config.match_window_backward,
        },
        "translation": {
            "endpoint": config.foundry_endpoint,
            "model": config.foundry_model,
            "timeoutS": config.translation_timeout_s,
            "batchSize": config.translation_batch_size,
        },
        "overlay": {
            "port": config.overlay_port,
            **overlay_style_payload(config),
        },
        "debug": {
            "mode": config.debug_mode,
        },
    }


def _coerce_int_list(value: Any, fallback: list[int]) -> list[int]:
    if not isinstance(value, list):
        return list(fallback)
    coerced: list[int] = []
    for item in value:
        try:
            coerced.append(int(item))
        except (TypeError, ValueError):
            return list(fallback)
    return coerced


def _coerce_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return fallback


def config_from_payload(payload: dict[str, object], fallback: AppConfig | None = None) -> AppConfig:
    base = fallback or AppConfig()
    subtitle_sources = payload.get("subtitleSources", {})
    opensubtitles_legacy = payload.get("opensubtitles", {})
    languages = payload.get("languages", {})
    capture = payload.get("capture", {})
    matching = payload.get("matching", {})
    translation = payload.get("translation", {})
    overlay = payload.get("overlay", {})

    if not isinstance(subtitle_sources, dict):
        subtitle_sources = {}
    if not isinstance(opensubtitles_legacy, dict):
        opensubtitles_legacy = {}
    if not isinstance(languages, dict):
        languages = {}
    if not isinstance(capture, dict):
        capture = {}
    if not isinstance(matching, dict):
        matching = {}
    if not isinstance(translation, dict):
        translation = {}
    if not isinstance(overlay, dict):
        overlay = {}

    # Payload merges are intentionally partial because the dashboard can persist
    # one subsection at a time, such as language-only saves.
    opensubtitles = subtitle_sources.get("opensubtitles", {})
    subdl = subtitle_sources.get("subdl", {})
    assrt = subtitle_sources.get("assrt", {})
    tmdb = subtitle_sources.get("tmdb", {})
    if not isinstance(opensubtitles, dict):
        opensubtitles = {}
    if not isinstance(subdl, dict):
        subdl = {}
    if not isinstance(assrt, dict):
        assrt = {}
    if not isinstance(tmdb, dict):
        tmdb = {}

    return AppConfig(
        opensubtitles_enabled=_coerce_bool(
            opensubtitles.get("enabled", opensubtitles_legacy.get("enabled", base.opensubtitles_enabled)),
            base.opensubtitles_enabled,
        ),
        opensubtitles_api_key=str(opensubtitles.get("apiKey", opensubtitles_legacy.get("apiKey", base.opensubtitles_api_key))),
        opensubtitles_username=str(opensubtitles.get("username", opensubtitles_legacy.get("username", base.opensubtitles_username))),
        opensubtitles_password=str(opensubtitles.get("password", opensubtitles_legacy.get("password", base.opensubtitles_password))),
        opensubtitles_enable_org_fallback=_coerce_bool(
            opensubtitles.get("enableOrgFallback", opensubtitles_legacy.get("enableOrgFallback", base.opensubtitles_enable_org_fallback)),
            base.opensubtitles_enable_org_fallback,
        ),
        subdl_enabled=_coerce_bool(subdl.get("enabled", base.subdl_enabled), base.subdl_enabled),
        subdl_api_key=str(subdl.get("apiKey", base.subdl_api_key)),
        assrt_enabled=_coerce_bool(assrt.get("enabled", base.assrt_enabled), base.assrt_enabled),
        assrt_token=str(assrt.get("token", base.assrt_token)),
        tmdb_api_key=str(tmdb.get("apiKey", base.tmdb_api_key)),
        tmdb_merge_enabled=_coerce_bool(tmdb.get("mergeEnabled", base.tmdb_merge_enabled), base.tmdb_merge_enabled),
        search_provider_timeout_s=_coerce_int(
            subtitle_sources.get("providerTimeoutS", base.search_provider_timeout_s),
            base.search_provider_timeout_s,
        ),
        source_language=normalize_source_language(str(languages.get("source", base.source_language))),
        target_language=normalize_target_language(str(languages.get("target", base.target_language))),
        capture_region=_coerce_int_list(capture.get("region", base.capture_region), base.capture_region),
        capture_interval_ms=_coerce_int(capture.get("intervalMs", base.capture_interval_ms), base.capture_interval_ms),
        ocr_language=derive_ocr_language(
            str(languages.get("source", base.source_language)),
            str(capture.get("ocrLanguage", base.ocr_language)),
        ),
        fuzzy_threshold=_coerce_int(matching.get("fuzzyThreshold", base.fuzzy_threshold), base.fuzzy_threshold),
        match_window_size=_coerce_int(matching.get("windowSize", base.match_window_size), base.match_window_size),
        match_window_backward=_coerce_int(
            matching.get("windowBackward", base.match_window_backward), base.match_window_backward
        ),
        foundry_endpoint=str(translation.get("endpoint", base.foundry_endpoint)),
        foundry_model=str(translation.get("model", base.foundry_model)),
        translation_timeout_s=_coerce_int(translation.get("timeoutS", base.translation_timeout_s), base.translation_timeout_s),
        translation_batch_size=_coerce_int(translation.get("batchSize", base.translation_batch_size), base.translation_batch_size),
        overlay_port=_coerce_int(overlay.get("port", base.overlay_port), base.overlay_port),
        overlay_font_size=_coerce_int(overlay.get("fontSize", base.overlay_font_size), base.overlay_font_size),
        overlay_font_family=str(overlay.get("fontFamily", base.overlay_font_family)),
        overlay_text_color=str(overlay.get("textColor", base.overlay_text_color)),
        overlay_bg_color=str(overlay.get("bgColor", base.overlay_bg_color)),
        overlay_position=str(overlay.get("position", base.overlay_position)),
        overlay_theme=str(overlay.get("theme", base.overlay_theme)),
        overlay_radius_px=_coerce_int(overlay.get("radiusPx", base.overlay_radius_px), base.overlay_radius_px),
        overlay_padding_px=_coerce_int(overlay.get("paddingPx", base.overlay_padding_px), base.overlay_padding_px),
        overlay_max_width_vw=_coerce_int(overlay.get("maxWidthVw", base.overlay_max_width_vw), base.overlay_max_width_vw),
        overlay_blur_px=_coerce_int(overlay.get("blurPx", base.overlay_blur_px), base.overlay_blur_px),
        overlay_shadow_strength=_coerce_float(
            overlay.get("shadowStrength", base.overlay_shadow_strength),
            base.overlay_shadow_strength,
        ),
        overlay_offset_pct=_coerce_int(overlay.get("offsetPct", base.overlay_offset_pct), base.overlay_offset_pct),
        overlay_animation_ms=_coerce_int(overlay.get("animationMs", base.overlay_animation_ms), base.overlay_animation_ms),
        debug_mode=_coerce_bool(payload.get("debug", {}).get("mode", base.debug_mode), base.debug_mode),
    )
