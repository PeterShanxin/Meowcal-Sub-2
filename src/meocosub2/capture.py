"""Screen capture and OCR helpers."""

from __future__ import annotations

import asyncio

import mss
from PIL import Image, ImageOps


def capture_region(region: tuple[int, int, int, int]) -> Image.Image:
    left, top, width, height = region
    with mss.mss() as sct:
        screenshot = sct.grab({"left": left, "top": top, "width": width, "height": height})
        return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")


def preprocess_for_ocr(image: Image.Image) -> Image.Image:
    grayscale = image.convert("L")
    equalized = ImageOps.equalize(grayscale)
    return equalized.point(lambda pixel: 255 if pixel >= 128 else 0)


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
    try:
        prepared = preprocess_for_ocr(image)
        return await _run_ocr(prepared, language)
    except Exception:
        return ""
