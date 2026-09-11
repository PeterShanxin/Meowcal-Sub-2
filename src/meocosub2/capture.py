"""Screen capture and OCR helpers."""

from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass
from time import monotonic

import mss
from PIL import Image, ImageChops, ImageOps
from rapidfuzz.distance import LCSseq

from meocosub2 import native_ocr
from meocosub2.languages import normalize_ocr_language
from meocosub2.textnorm import clean_cjk_text, is_cjk_char

logger = logging.getLogger(__name__)
_OCR_PASS_TIMEOUT_SECONDS = 1.0


@dataclass(frozen=True)
class OcrResolution:
    requested_language: str
    resolved_language: str
    warning_message: str = ""


def available_ocr_languages(*, refresh: bool = True) -> list[str]:
    try:
        return sorted(set(native_ocr.available_languages(refresh=refresh)))
    except Exception:
        return []


def resolve_ocr_language(language: str) -> OcrResolution:
    requested = normalize_ocr_language(language)
    installed = available_ocr_languages(refresh=False)
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
        return OcrResolution(
            requested,
            "zh-Hans-CN",
            "Traditional Chinese OCR pack is missing. Falling back to Simplified Chinese OCR.",
        )
    if requested == "zh-CN" and "zh-TW" in installed:
        return OcrResolution(
            requested,
            "zh-TW",
            "Simplified Chinese OCR pack is missing. Falling back to Traditional Chinese OCR.",
        )
    if requested == "en-US" and "en-GB" in installed:
        return OcrResolution(
            requested, "en-GB", "English (US) OCR pack is missing. Falling back to English."
        )

    return OcrResolution(requested, requested, f"OCR language '{requested}' is not installed.")


def capture_region(region: tuple[int, int, int, int]) -> Image.Image:
    left, top, width, height = region
    with mss.mss() as sct:
        screenshot = sct.grab({"left": left, "top": top, "width": width, "height": height})
        return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")


def capture_region_jpeg(region: tuple[int, int, int, int], quality: int = 80) -> bytes:
    """The screen as it looks right now, for the capture selector to draw on.

    JPEG rather than PNG: nothing reads these pixels, they are only there for the
    user to aim at, and a full screen encodes and travels an order of magnitude
    cheaper this way.
    """
    buffer = io.BytesIO()
    capture_region(region).save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def preprocess_for_ocr(image: Image.Image) -> Image.Image:
    grayscale = image.convert("L")
    equalized = ImageOps.equalize(grayscale)
    return equalized.point(lambda pixel: 255 if pixel >= 128 else 0)


def preprocess_white_text_for_ocr(image: Image.Image) -> Image.Image:
    # Equalization preserves scene edges that can hide an entire subtitle row.
    # Require every channel to be bright so colored scenery stays out of the mask.
    red, green, blue = image.convert("RGB").split()
    darkest_channel = ImageChops.darker(ImageChops.darker(red, green), blue)
    return darkest_channel.point(lambda pixel: 255 if pixel >= 200 else 0)


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
    return await native_ocr.recognize(image, language, _OCR_PASS_TIMEOUT_SECONDS)


async def ocr_image(image: Image.Image, language: str) -> str:
    resolution = await asyncio.to_thread(resolve_ocr_language, language)
    raw_first = _should_try_raw_first(resolution.resolved_language)
    passes = [image, preprocess_for_ocr(image)] if raw_first else [preprocess_for_ocr(image), image]
    pass_names = ["raw", "preprocessed"] if raw_first else ["preprocessed", "raw"]
    passes.append(preprocess_white_text_for_ocr(image))
    pass_names.append("white-text")
    best_text = ""
    best_score = (0, 0)
    best_pass = "none"
    whole_scene_reads: list[str] = []
    t0 = monotonic()
    for pass_name, candidate in zip(pass_names, passes, strict=True):
        try:
            text = await asyncio.wait_for(
                _run_ocr(candidate, resolution.resolved_language), timeout=_OCR_PASS_TIMEOUT_SECONDS
            )
        except TimeoutError:
            logger.debug("OCR pass=%s timed out", pass_name)
            break
        except Exception as exc:
            logger.debug("OCR pass=%s failed: %s", pass_name, exc)
            text = ""
        score = _ocr_score(text)
        letters = "".join(ch for ch in text.casefold() if ch.isalpha())
        if pass_name == "white-text":
            # A mask can retain scenery text while removing colored subtitles.
            # Require most of a prior read, allowing one OCR error per five letters.
            if not any(
                LCSseq.similarity(prior, letters) >= 0.8 * len(prior) for prior in whole_scene_reads
            ):
                continue
        elif len(letters) >= 3:
            whole_scene_reads.append(letters)
        if score > best_score:
            best_score = score
            best_text = text
            best_pass = pass_name
    best_text = clean_cjk_text(best_text)
    elapsed_ms = int((monotonic() - t0) * 1000)
    logger.debug(
        "OCR pass=%s score=%s len=%d text=%r duration_ms=%d",
        best_pass,
        best_score,
        len(best_text),
        best_text[:80],
        elapsed_ms,
    )
    return best_text
