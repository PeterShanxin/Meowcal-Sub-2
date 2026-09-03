"""Subtitle translation through the managed local HY-MT engine.

Prompt shape and sampling are ported from Meowcal Sub v1, where they were tuned
for HY-MT1.5: a single instruction line per subtitle, recent lines as context,
and low-temperature sampling so the model translates instead of chatting.
"""

from __future__ import annotations

import logging
import re

import httpx

from meocosub2 import engine
from meocosub2.config import AppConfig
from meocosub2.errors import TranslationError
from meocosub2.languages import language_label
from meocosub2.textnorm import collapse_whitespace, is_cjk_char

logger = logging.getLogger(__name__)

MAX_SOURCE_CHARS = 300
MAX_CONTEXT_CHARS = 400
SAMPLING = {"temperature": 0.3, "top_k": 20, "top_p": 0.6, "repeat_penalty": 1.05}
MAX_OUTPUT_TOKENS = 150


def is_untranslatable(text: str) -> bool:
    """OCR noise that should never reach the model."""
    cleaned = collapse_whitespace(text)
    if not cleaned:
        return True
    meaningful = sum(1 for ch in cleaned if ch.isalpha() or is_cjk_char(ch))
    return meaningful < 2


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def _clip_context(lines: list[str], limit: int) -> str:
    kept: list[str] = []
    used = 0
    for line in reversed(lines):
        if used + len(line) > limit:
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(reversed(kept))


def build_prompt(text: str, target_language: str, context_lines: list[str] | None = None) -> str:
    source = _truncate(collapse_whitespace(text), MAX_SOURCE_CHARS)
    label = language_label(target_language)
    chinese_template = target_language.lower().startswith("zh")
    context = _clip_context(list(context_lines or []), MAX_CONTEXT_CHARS)

    if chinese_template:
        if context:
            return (
                f"{context}\n参考上面的信息，把下面的文本翻译成{label}，"
                f"注意不需要翻译上文，也不要额外解释：\n{source}"
            )
        return f"将以下文本翻译为{label}，注意只需要输出翻译后的结果，不要额外解释：\n\n{source}"
    if context:
        return (
            f"{context}\nBased on the information above, translate the text below into "
            f"{label}. Do not translate the context or add explanations:\n{source}"
        )
    return f"Translate the following segment into {label}, without additional explanation.\n\n{source}"


def sanitize_output(text: str) -> str:
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        line = re.sub(r"^\s*(translation|output|译文)\s*[:：]\s*", "", line, flags=re.IGNORECASE)
        line = line.strip().strip("\"'")
        if not line:
            continue
        if re.match(r"^(here|note|explanation)\b", line, flags=re.IGNORECASE):
            continue
        cleaned_lines.append(line)
    return " ".join(cleaned_lines).strip()


class TranslationClient:
    """A short-lived connection to the managed engine, reused for a whole session."""

    def __init__(self, base_url: str, model: str, timeout_s: float) -> None:
        self._base_url = base_url
        self._model = model
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def translate(
        self,
        text: str,
        target_language: str,
        context_lines: list[str] | None = None,
    ) -> str:
        if is_untranslatable(text):
            return ""
        prompt = build_prompt(text, target_language, context_lines)
        try:
            response = await self._client.post(
                f"{self._base_url}/v1/chat/completions",
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": MAX_OUTPUT_TOKENS,
                    **SAMPLING,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise TranslationError(f"The local translation engine did not respond: {exc}") from exc
        except ValueError as exc:
            raise TranslationError("The local translation engine returned an unreadable reply.") from exc

        choices = payload.get("choices") or []
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        return sanitize_output(content)

    async def close(self) -> None:
        await self._client.aclose()


async def open_translation_client(config: AppConfig) -> TranslationClient:
    endpoint = await engine.ensure_ready()
    manifest_model = engine.load_manifest().model.id
    return TranslationClient(endpoint, manifest_model, config.translation_timeout_s)
