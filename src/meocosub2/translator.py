"""Subtitle translation through the managed local HY-MT engine.

Prompt shape and sampling are ported from Meowcal Sub v1, where they were tuned
for HY-MT1.5: a single instruction line per subtitle, recent lines as context,
and low-temperature sampling so the model translates instead of chatting.
"""

from __future__ import annotations

import logging
import re
from itertools import pairwise

import httpx
from rapidfuzz import fuzz

from meocosub2 import engine
from meocosub2.config import AppConfig
from meocosub2.errors import TranslationError
from meocosub2.languages import language_label
from meocosub2.textnorm import collapse_whitespace, is_cjk_char, is_cjk_compactable_char

logger = logging.getLogger(__name__)

# Output limits ported from Meowcal Sub v1, where they were measured against real
# HY-MT sessions. A model that translates its own context, loops, or echoes the
# prompt produces output that is obvious by shape, and showing it is worse than
# showing nothing.
MAX_OUTPUT_CHARS = 240
DEFAULT_OUTPUT_RATIO = 4
MIN_SHORT_OUTPUT_CHARS = 32
# Short CJK phrases routinely expand into much longer natural English.
CJK_TO_ENGLISH_RATIO = 12
MIN_CJK_TO_ENGLISH_CHARS = 64
MIN_TOKENS_FOR_REPETITION = 8
MAX_REPEATED_TOKEN_STREAK = 4
MIN_CHARS_TO_JUDGE_SCRIPT = 6
# How closely a leading sentence must restate a line already on screen before it
# is treated as the model repeating its context rather than translating.
RESTATED_CONTEXT_SIMILARITY = 80.0
# How closely a whole answer must restate one context line before it is read as
# the model handing back what it was given instead of translating.
ECHOED_CONTEXT_SIMILARITY = 88.0

MAX_SOURCE_CHARS = 300
MAX_CONTEXT_CHARS = 400
SAMPLING = {"temperature": 0.3, "top_k": 20, "top_p": 0.6, "repeat_penalty": 1.05}
MAX_OUTPUT_TOKENS = 150


def is_untranslatable(text: str) -> bool:
    """OCR noise that should never reach the model.

    One CJK character can be a whole word - 好, 是 - so a single one counts,
    while a lone Latin letter is a stray glyph.
    """
    cleaned = collapse_whitespace(text)
    if not cleaned:
        return True
    if any(is_cjk_compactable_char(ch) for ch in cleaned):
        return False
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


# The instruction template is written in Chinese whenever either side of the pair
# is Chinese: HY-MT follows a Chinese instruction far more reliably there, and a
# zh->en session asked in English re-emitted the context as part of its answer.
_CHINESE_TARGET_LABELS = {
    "zh": "中文",
    "zht": "繁体中文",
    "en": "英语",
    "ja": "日语",
    "ko": "韩语",
    "fr": "法语",
    "de": "德语",
    "es": "西班牙语",
}


def _is_chinese(code: str) -> bool:
    return code.lower().split("-")[0] in {"zh", "zht"}


def build_prompt(
    text: str,
    source_language: str,
    target_language: str,
    context_lines: list[str] | None = None,
) -> str:
    source = _truncate(collapse_whitespace(text), MAX_SOURCE_CHARS)
    chinese_template = _is_chinese(target_language) or _is_chinese(source_language)
    label = (
        _CHINESE_TARGET_LABELS.get(target_language.lower(), language_label(target_language))
        if chinese_template
        else language_label(target_language)
    )
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
    return (
        f"Translate the following segment into {label}, without additional explanation.\n\n{source}"
    )


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


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    for ch in text:
        if ch.isalnum() or is_cjk_char(ch):
            current.append(ch.lower())
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def looks_like_a_loop(text: str) -> bool:
    tokens = _tokenize(text)
    if len(tokens) < MIN_TOKENS_FOR_REPETITION:
        return False
    streak = longest = 1
    for previous, token in pairwise(tokens):
        streak = streak + 1 if token == previous else 1
        longest = max(longest, streak)
    return longest >= MAX_REPEATED_TOKEN_STREAK or len(set(tokens)) * 3 <= len(tokens)


def _says_it_twice(text: str) -> bool:
    """Whether the model emitted one sentence and then repeated it verbatim."""
    tokens = _tokenize(text)
    if len(tokens) < 6 or len(tokens) % 2:
        return False
    half = len(tokens) // 2
    return tokens[:half] == tokens[half:]


def _looks_like_a_proper_name(text: str) -> bool:
    """One name the model chose not to render is a real translation, not an echo.

    Deliberately narrow, as in v1: a single token, letters all the way through,
    set the way a name is set - `Ariadne` or `ARIADNE` - with hyphens and
    apostrophes joining parts that are each judged the same way.
    """
    token = text.strip()
    if not token or " " in token:
        return False
    parts = re.split(r"[-']", token)
    return all(part and part.isalpha() and (part.istitle() or part.isupper()) for part in parts)


def _wrong_script(translated: str, target_language: str) -> bool:
    """Whether the output is written in the wrong script for the target.

    A local MT model asked for English sometimes returns the Chinese it was
    given. Judging by script catches that without judging the translation.
    """
    target = target_language.lower().split("-")[0]
    body = [ch for ch in translated if not ch.isspace()]
    if len(body) < MIN_CHARS_TO_JUDGE_SCRIPT:
        return False
    alphabetic = [ch for ch in body if ch.isalpha()]
    cjk = [ch for ch in body if is_cjk_char(ch)]
    latin = [ch for ch in alphabetic if ch.isascii()]
    if target == "en":
        if not cjk:
            return False
        if not latin:
            return True
        if len(cjk) * 100 < len(body) * 30:
            return False
        return len(latin) * 10 < len(alphabetic) * 7
    if target.startswith("zh") or target in {"ja", "ko"}:
        if cjk or not latin or _looks_like_a_proper_name(translated):
            return False
        return len(latin) * 10 >= len(alphabetic) * 7
    return False


def is_usable_translation(source: str, translated: str, target_language: str) -> bool:
    """Whether model output is a translation of this line rather than noise.

    A local model asked for one subtitle sometimes returns the context it was
    given as well, or loops. Both are recognisable by length and repetition, and
    keeping the previous line on screen beats replacing it with either.
    """
    if not translated:
        return False
    length = len(translated)
    if length > MAX_OUTPUT_CHARS:
        return False
    cjk_to_english = any(is_cjk_char(ch) for ch in source) and target_language.lower().startswith(
        "en"
    )
    ratio, floor = (
        (CJK_TO_ENGLISH_RATIO, MIN_CJK_TO_ENGLISH_CHARS)
        if cjk_to_english
        else (DEFAULT_OUTPUT_RATIO, MIN_SHORT_OUTPUT_CHARS)
    )
    if length > max(len(source) * ratio, floor):
        return False
    if _says_it_twice(translated) or looks_like_a_loop(translated):
        return False
    return not _wrong_script(translated, target_language)


def echoes_context(translated: str, context_lines: list[str]) -> bool:
    """Whether the answer is one of the lines the model was given as context.

    Measured against a real HY-MT session: asked to translate a new subtitle
    with the previous two as context, the model sometimes returns the previous
    one word for word. Sentence-by-sentence trimming does not catch it, because
    every sentence is genuine - they are just the wrong line. Showing the line
    already on screen a second time reads as new dialogue, so nothing is shown
    and the plate keeps the line it has.
    """
    if not translated:
        return False
    # Length-sensitive on purpose: a set comparison scores a short context line
    # whose words all appear in a longer answer as a perfect echo, so "Wait." in
    # the context would condemn any translation containing the word.
    return any(
        fuzz.ratio(translated.lower(), line.lower()) >= ECHOED_CONTEXT_SIMILARITY
        for line in context_lines
    )


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+", text.strip())
    return [part for part in parts if part.strip()]


def drop_restated_context(translated: str, context_lines: list[str]) -> str:
    """Remove leading sentences that repeat a line the viewer has already seen.

    Asked to translate one subtitle with recent lines as context, the model
    sometimes answers with the context and the new line together. The new line is
    the tail, so the leading restatements are dropped; an answer that is nothing
    but restatement is dropped entirely, leaving the line already on screen.
    """
    if not context_lines:
        return translated
    sentences = _sentences(translated)
    if len(sentences) < 2:
        return translated

    def restates(sentence: str) -> bool:
        return any(
            fuzz.ratio(sentence.lower(), line.lower()) >= RESTATED_CONTEXT_SIMILARITY
            for line in context_lines
        )

    start = 0
    while start < len(sentences) and restates(sentences[start]):
        start += 1
    end = len(sentences)
    while end > start and restates(sentences[end - 1]):
        end -= 1
    if start == 0 and end == len(sentences):
        return translated
    # Nothing survives when every sentence restates something already on screen:
    # the answer carries nothing new, and the line being read is still the right one.
    return " ".join(sentences[start:end]).strip()


class TranslationClient:
    """A short-lived connection to the managed engine, reused for a whole session."""

    def __init__(self, base_url: str, model: str, timeout_s: float) -> None:
        self._base_url = base_url
        self._model = model
        self._client = httpx.AsyncClient(timeout=timeout_s)

    async def _complete(self, prompt: str) -> str:
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
            raise TranslationError(
                "The local translation engine returned an unreadable reply."
            ) from exc

        choices = payload.get("choices") or []
        return choices[0].get("message", {}).get("content", "") if choices else ""

    async def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
        context_lines: list[str] | None = None,
    ) -> str:
        if is_untranslatable(text):
            return ""
        context = list(context_lines or [])
        prompt = build_prompt(text, source_language, target_language, context)
        translated = drop_restated_context(sanitize_output(await self._complete(prompt)), context)

        if context and echoes_context(translated, context):
            # Handing back the context is what this model does when the read is
            # too damaged to translate, and the answer it hands back is the line
            # already on screen. Asked again with nothing to copy, it either
            # translates the read or fails in a way the checks below catch - and
            # either beats a plate that stays blank for the rest of the session,
            # because the context only advances when a line gets through.
            logger.debug("Echoed context for %r, retrying without it", text[:40])
            translated = sanitize_output(
                await self._complete(build_prompt(text, source_language, target_language, None))
            )
            if echoes_context(translated, context):
                logger.debug("Discarded echoed context for %r: %r", text[:40], translated[:80])
                return ""

        if not is_usable_translation(text, translated, target_language):
            logger.debug("Discarded unusable translation for %r: %r", text[:40], translated[:80])
            return ""
        return translated

    async def close(self) -> None:
        await self._client.aclose()


async def open_translation_client(config: AppConfig) -> TranslationClient:
    endpoint = await engine.ensure_ready()
    manifest_model = engine.load_manifest().model.id
    return TranslationClient(endpoint, manifest_model, config.translation_timeout_s)
