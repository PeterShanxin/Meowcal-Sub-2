"""Screen capture and OCR helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import mss
from PIL import Image, ImageOps
from winocr import OcrEngine

from meocosub2.languages import normalize_ocr_language
from meocosub2.textnorm import clean_cjk_text, is_cjk_char


@dataclass(frozen=True)
class OcrResolution:
    requested_language: str
    resolved_language: str
    warning_message: str = ""


def available_ocr_languages() -> list[str]:
    try:
        return sorted({item.language_tag for item in OcrEngine.available_recognizer_languages})
    except Exception:
        return []


def resolve_ocr_language(language: str) -> OcrResolution:
    requested = normalize_ocr_language(language)
    installed = available_ocr_languages()
    if not installed:
        return OcrResolution(requested, requested, "Windows OCR languages could not be enumerated.")

    alias_candidates = {
        "zh-CN": ["zh-CN", "zh-Hans-CN"],
        "zh-TW": ["zh-TW", "zh-Hant", "zh-Hant-TW"],
        "en-US": ["en-US", "en-GB"],
        "ja-JP": ["ja-JP"],
        "ko-KR": ["ko-KR"],
    }.get(requested, [requested])
    for candidate in alias_candidates:
        if candidate in installed:
            return OcrResolution(requested, candidate)

    if requested == "zh-TW" and "zh-Hans-CN" in installed:
        return OcrResolution(requested, "zh-Hans-CN", "Traditional Chinese OCR pack is missing. Falling back to Simplified Chinese OCR.")
    if requested == "zh-CN" and "zh-TW" in installed:
        return OcrResolution(requested, "zh-TW", "Simplified Chinese OCR pack is missing. Falling back to Traditional Chinese OCR.")
    if requested == "en-US" and "en-GB" in installed:
        return OcrResolution(requested, "en-GB", "English (US) OCR pack is missing. Falling back to English.")

    return OcrResolution(requested, requested, f"OCR language '{requested}' is not installed.")


def capture_region(region: tuple[int, int, int, int]) -> Image.Image:
    left, top, width, height = region
    with mss.mss() as sct:
        screenshot = sct.grab({"left": left, "top": top, "width": width, "height": height})
        return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")


def preprocess_for_ocr(image: Image.Image) -> Image.Image:
    grayscale = image.convert("L")
    equalized = ImageOps.equalize(grayscale)
    return equalized.point(lambda pixel: 255 if pixel >= 128 else 0)


def _should_try_raw_first(language: str) -> bool:
    normalized = normalize_ocr_language(language)
    return normalized.startswith("zh") or normalized.startswith("ja")


def _ocr_score(text: str) -> tuple[int, int]:
    if not text:
        return (0, 0)
    cleaned = clean_cjk_text(text)
    meaningful = sum(1 for ch in cleaned if ch.isalpha() or is_cjk_char(ch))
    return (meaningful, len(cleaned))


async def _run_ocr(image: Image.Image, language: str) -> str:
    loop = asyncio.get_running_loop()

    def recognize() -> str:
        import winocr

        result = winocr.recognize_pil(image, language)
        if hasattr(result, "get"):
            result = result.get()
        return getattr(result, "text", str(result)).strip()

    return await loop.run_in_executor(None, recognize)


async def ocr_image(image: Image.Image, language: str) -> str:
    resolution = resolve_ocr_language(language)
    passes = [image, preprocess_for_ocr(image)] if _should_try_raw_first(resolution.resolved_language) else [preprocess_for_ocr(image), image]
    best_text = ""
    best_score = (0, 0)
    for candidate in passes:
        try:
            text = await _run_ocr(candidate, resolution.resolved_language)
        except Exception:
            text = ""
        score = _ocr_score(text)
        if score > best_score:
            best_score = score
            best_text = text
    return best_text
