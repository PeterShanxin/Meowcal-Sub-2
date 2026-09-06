"""What the local model is asked, for a read off the screen and for a gap.

The two callers know different things. A read has only the lines already shown
as context, and nothing to check them against. A line the target file never
answered sits inside a file whose neighbours *are* answered, so the model can be
shown what this translation already calls things - the names, the register, the
way a running joke is rendered - and asked to match it.
"""

from __future__ import annotations

from meocosub2.languages import language_label
from meocosub2.textnorm import collapse_whitespace

MAX_SOURCE_CHARS = 300
MAX_CONTEXT_CHARS = 400
# A pair spends both of its halves, so the same budget buys fewer of them. It is
# separate from the context budget because it answers a different question: how
# much of the file's own voice fits, rather than how much of the recent screen.
MAX_PAIR_CHARS = 600
# How a pair is written for the model: the file's own line, then what this
# translation made of it.
PAIR_ARROW = " => "

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


def _is_chinese(code: str) -> bool:
    return code.lower().split("-")[0] in {"zh", "zht"}


def _template_is_chinese(source_language: str, target_language: str) -> bool:
    return _is_chinese(target_language) or _is_chinese(source_language)


def _label(source_language: str, target_language: str) -> str:
    if _template_is_chinese(source_language, target_language):
        return _CHINESE_TARGET_LABELS.get(target_language.lower(), language_label(target_language))
    return language_label(target_language)


def build_prompt(
    text: str,
    source_language: str,
    target_language: str,
    context_lines: list[str] | None = None,
) -> str:
    source = _truncate(collapse_whitespace(text), MAX_SOURCE_CHARS)
    label = _label(source_language, target_language)
    context = _clip_context(list(context_lines or []), MAX_CONTEXT_CHARS)

    if _template_is_chinese(source_language, target_language):
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


def _clip_pairs(pairs: list[tuple[str, str]], limit: int) -> list[str]:
    """The pairs nearest the gap that fit, in the order the episode plays them."""
    kept: list[str] = []
    used = 0
    for source, target in reversed(pairs):
        rendered = f"{collapse_whitespace(source)}{PAIR_ARROW}{collapse_whitespace(target)}"
        if used + len(rendered) > limit:
            break
        kept.append(rendered)
        used += len(rendered) + 1
    kept.reverse()
    return kept


def build_paired_prompt(
    text: str,
    source_language: str,
    target_language: str,
    pairs: list[tuple[str, str]],
) -> str:
    """Ask for a missing line in the voice the rest of the file already uses.

    Falls back to the plain prompt when no neighbour is paired, which is what a
    file answering almost nothing looks like.
    """
    rendered = _clip_pairs(list(pairs), MAX_PAIR_CHARS)
    if not rendered:
        return build_prompt(text, source_language, target_language)

    source = _truncate(collapse_whitespace(text), MAX_SOURCE_CHARS)
    label = _label(source_language, target_language)
    examples = "\n".join(rendered)

    if _template_is_chinese(source_language, target_language):
        return (
            f"这部片子已有的译文：\n{examples}\n"
            f"按同样的风格和用词，把下面这句翻译成{label}，只输出译文：\n{source}"
        )
    return (
        f"This subtitle file already renders these lines:\n{examples}\n"
        f"Translate the line below into {label} in the same style and wording. "
        f"Output only the translation:\n{source}"
    )
