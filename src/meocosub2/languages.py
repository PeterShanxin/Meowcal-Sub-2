"""Language catalogs and normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageOption:
    code: str
    label: str


SOURCE_TARGET_OPTIONS = (
    LanguageOption("en", "English"),
    LanguageOption("zh", "Chinese (Simplified)"),
    LanguageOption("zht", "Chinese (Traditional)"),
    LanguageOption("ja", "Japanese"),
    LanguageOption("ko", "Korean"),
    LanguageOption("es", "Spanish"),
    LanguageOption("fr", "French"),
    LanguageOption("de", "German"),
)

OCR_OPTIONS = (
    LanguageOption("en-US", "English"),
    LanguageOption("zh-CN", "Chinese (Simplified)"),
    LanguageOption("zh-TW", "Chinese (Traditional)"),
    LanguageOption("ja-JP", "Japanese"),
    LanguageOption("ko-KR", "Korean"),
    LanguageOption("es-ES", "Spanish"),
    LanguageOption("fr-FR", "French"),
    LanguageOption("de-DE", "German"),
)

_LANGUAGE_LABELS = {option.code: option.label for option in SOURCE_TARGET_OPTIONS}
_OCR_LABELS = {option.code: option.label for option in OCR_OPTIONS}

_SOURCE_ALIASES = {
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "zh": "zh",
    "zh-cn": "zh",
    "zh-hans": "zh",
    "zh-hans-cn": "zh",
    "zhs": "zh",
    "zht": "zht",
    "zh-tw": "zht",
    "zh-hant": "zht",
    "zh-hant-tw": "zht",
    "ja": "ja",
    "ja-jp": "ja",
    "ko": "ko",
    "ko-kr": "ko",
    "es": "es",
    "es-es": "es",
    "fr": "fr",
    "fr-fr": "fr",
    "de": "de",
    "de-de": "de",
}

_OCR_ALIASES = {
    "en": "en-US",
    "en-us": "en-US",
    "en-gb": "en-US",
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
    "zh-hans-cn": "zh-CN",
    "zhs": "zh-CN",
    "zht": "zh-TW",
    "zh-tw": "zh-TW",
    "zh-hant": "zh-TW",
    "zh-hant-tw": "zh-TW",
    "ja": "ja-JP",
    "ja-jp": "ja-JP",
    "ko": "ko-KR",
    "ko-kr": "ko-KR",
    "es": "es-ES",
    "es-es": "es-ES",
    "fr": "fr-FR",
    "fr-fr": "fr-FR",
    "de": "de-DE",
    "de-de": "de-DE",
}

_CHINESE_FAMILY = {"zh", "zht"}


def normalize_source_language(code: str) -> str:
    if not code:
        return "en"
    lowered = code.strip().lower()
    return _SOURCE_ALIASES.get(lowered, lowered)


def normalize_target_language(code: str) -> str:
    return normalize_source_language(code)


def normalize_ocr_language(code: str) -> str:
    if not code:
        return "en-US"
    lowered = code.strip().lower()
    return _OCR_ALIASES.get(lowered, code.strip())


def is_chinese_family(code: str) -> bool:
    normalized = normalize_source_language(code)
    return normalized in _CHINESE_FAMILY or normalized.startswith("zh")


def expand_search_languages(source_language: str, target_language: str) -> str:
    codes: set[str] = {
        normalize_source_language(source_language),
        normalize_target_language(target_language),
    }
    if any(is_chinese_family(code) for code in codes):
        codes.update(_CHINESE_FAMILY)
    return ",".join(sorted(code for code in codes if code))


def derive_ocr_language(source_language: str, existing_ocr_language: str = "") -> str:
    normalized = normalize_source_language(source_language)
    if normalized in {"en", "ja", "ko", "es", "fr", "de"}:
        return normalize_ocr_language(normalized)
    if normalized == "zht":
        return "zh-TW"
    if normalized == "zh":
        return "zh-CN"
    if existing_ocr_language:
        return normalize_ocr_language(existing_ocr_language)
    return "en-US"


def source_result_matches_requested_language(requested_language: str, result_language: str) -> bool:
    requested = normalize_source_language(requested_language)
    result = normalize_source_language(result_language)
    if requested == result:
        return True
    return is_chinese_family(requested) and is_chinese_family(result)


def source_language_mode(requested_language: str, resolved_language: str) -> str:
    requested = normalize_source_language(requested_language)
    resolved = normalize_source_language(resolved_language)
    if requested == resolved:
        return "exact"
    if is_chinese_family(requested) and is_chinese_family(resolved):
        return "family_fallback"
    return "exact"


def language_label(code: str) -> str:
    normalized = normalize_source_language(code)
    return _LANGUAGE_LABELS.get(normalized, code)


def ocr_label(code: str) -> str:
    normalized = normalize_ocr_language(code)
    return _OCR_LABELS.get(normalized, code)


def languages_payload(installed_ocr_languages: set[str]) -> dict[str, object]:
    normalized_installed = {normalize_ocr_language(code) for code in installed_ocr_languages}
    return {
        "sourceTarget": [
            {"code": option.code, "label": option.label} for option in SOURCE_TARGET_OPTIONS
        ],
        "ocr": [
            {
                "code": option.code,
                "label": option.label,
                "installed": option.code in normalized_installed,
            }
            for option in OCR_OPTIONS
        ],
        "customSourceTargetEnabled": True,
    }
