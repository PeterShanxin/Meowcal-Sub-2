"""Session translation with recent screen context and source-file examples."""

from __future__ import annotations

from collections import OrderedDict, deque

from meocosub2.config import AppConfig
from meocosub2.matcher import SubtitleMatcher
from meocosub2.translator import TranslationClient, open_translation_client

TRANSLATION_CACHE_SIZE = 64
CONTEXT_LINES = 3


class LiveTranslator:
    """Caches translations and carries recent lines as context, like v1's session cache."""

    def __init__(
        self, client: TranslationClient, source_language: str, target_language: str
    ) -> None:
        self._client = client
        self._source_language = source_language
        self._target_language = target_language
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._context: deque[str] = deque(maxlen=CONTEXT_LINES)

    async def translate_from_file(self, text: str, pairs: list[tuple[str, str]]) -> str:
        """Translate a line of the subtitle file, in the voice the file already uses.

        Deliberately outside the cache and the rolling context: both describe
        what has been on screen, and a cue being answered ahead of time has not.
        The pairs carry their own echo context, so none is passed here.
        """
        return await self._client.translate(
            text,
            self._source_language,
            self._target_language,
            pairs=pairs,
        )

    async def translate(self, text: str) -> str:
        key = SubtitleMatcher.normalize_text(text)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        translated = await self._client.translate(
            text, self._source_language, self._target_language, list(self._context)
        )
        if translated:
            self._cache[key] = translated
            while len(self._cache) > TRANSLATION_CACHE_SIZE:
                self._cache.popitem(last=False)
            self._context.append(translated)
        return translated


async def open_live_translator(config: AppConfig) -> tuple[TranslationClient, LiveTranslator]:
    client = await open_translation_client(config)
    return client, LiveTranslator(client, config.source_language, config.target_language)
