"""Windows OCR through an owned Core process independent of translation."""

from __future__ import annotations

import base64

from PIL import Image

from meocosub2.core_client import CoreClient, resolve_core_executable

_client: CoreClient | None = None


def shutdown() -> None:
    global _client
    client, _client = _client, None
    if client is not None:
        client.close_sync()


def _ocr_client() -> CoreClient:
    global _client
    if _client is None:
        _client = CoreClient(resolve_core_executable())
    return _client


def available_languages() -> list[str]:
    response = _ocr_client().request_sync("ocrLanguages", {}, timeout_s=5.0)
    languages = response.get("languages")
    if not isinstance(languages, list) or not all(isinstance(tag, str) for tag in languages):
        raise RuntimeError("Core returned invalid OCR languages")
    return languages


async def recognize(image: Image.Image, language: str, timeout_s: float) -> str:
    width, height = image.size
    if not (0 < width <= 4096 and 0 < height <= 4096):
        raise ValueError("OCR frame dimensions must be within 1..=4096")
    # Packed rows in BGRA8 order; Core ignores alpha. Product preprocessing has
    # already chosen the pixels and Core performs no resizing or thresholding.
    pixels = image.convert("RGBA").tobytes("raw", "BGRA")
    response = await _ocr_client().request(
        "ocrRecognize",
        {
            "language": language,
            "width": width,
            "height": height,
            "stride": width * 4,
            "bgraBase64": base64.b64encode(pixels).decode("ascii"),
            "timeoutMs": max(1, int(timeout_s * 1000)),
        },
        timeout_s=timeout_s,
    )
    text = response.get("text")
    if not isinstance(text, str):
        raise RuntimeError("Core returned invalid OCR text")
    return text.strip()
