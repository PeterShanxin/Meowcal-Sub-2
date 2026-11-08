"""ASSRT provider implementation."""

from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from pathlib import Path

import httpx

from meocosub2.config import AppConfig
from meocosub2.errors import SubtitleSourceError
from meocosub2.event_log import log_event
from meocosub2.http_timeouts import provider_timeout
from meocosub2.subtitle_sources.cache_paths import (
    contained_path,
    safe_segment,
    subtitle_file_name,
)
from meocosub2.subtitle_sources.types import (
    ProviderCapabilities,
    ProviderSearchCatalog,
    ProviderSubtitleResult,
)
from meocosub2.subtitle_sources.utils import (
    SUBTITLE_EXTENSIONS,
    best_title_guess,
    canonical_title,
    extract_episode_info,
    extract_year,
    map_assrt_languages,
    title_similarity,
)

API_BASE = "https://api.assrt.net/v1"
MAX_RESULTS = 15
YEAR_SUFFIX_PATTERN = re.compile(r"\s*[\(（]?(?:19|20|21)\d{2}[\)）]?\s*$")
LATIN_TITLE_SEGMENT_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9'’&:.\- ]*[A-Za-z0-9)]?")
TRAILING_SEASON_PATTERN = re.compile(r"\bS\d{1,2}\s*$", re.IGNORECASE)


class AssrtProvider:
    provider_code = "assrt"
    provider_label = "ASSRT"
    capabilities = ProviderCapabilities(search=True, download=True, requires_auth=True)

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._cache_dir = Path.home() / ".cache" / "meowcal-sub-2" / "assrt"

    @property
    def enabled(self) -> bool:
        return self.config.assrt_enabled

    async def search_catalog(self, query: str, languages: str) -> ProviderSearchCatalog:
        if not self.config.assrt_enabled:
            return ProviderSearchCatalog(matches=[], results=[], warnings=["ASSRT is disabled."])
        if not self.config.assrt_token:
            return ProviderSearchCatalog(
                matches=[], results=[], warnings=["ASSRT token is not configured."]
            )

        requested_languages = {code.strip() for code in languages.split(",") if code.strip()}
        payload = await self._request(
            "/sub/search",
            {"token": self.config.assrt_token, "q": query, "cnt": MAX_RESULTS, "filelist": 1},
        )
        subtitles = payload.get("sub", {}).get("subs", [])
        results: list[ProviderSubtitleResult] = []
        for item in subtitles:
            if not isinstance(item, dict):
                continue
            lang_block = item.get("lang") if isinstance(item.get("lang"), dict) else {}
            languages_in_pack = map_assrt_languages(
                str(lang_block.get("desc", "")),
                lang_block.get("langlist")
                if isinstance(lang_block.get("langlist"), dict)
                else None,
            )
            native_name = str(item.get("native_name") or "")
            videoname = str(item.get("videoname") or "")
            filelist = item.get("filelist") if isinstance(item.get("filelist"), list) else []
            file_names = [
                str(entry["f"])
                for entry in filelist
                if isinstance(entry, dict)
                and str(entry.get("f", "")).casefold().endswith(SUBTITLE_EXTENSIONS)
            ]
            if filelist and not file_names:
                continue
            metadata_values = [native_name, videoname, *file_names]
            aliases = movie_title_aliases(*metadata_values)
            for file_name in file_names or [f"{item.get('id')}.srt"]:
                season, episode = extract_episode_info(file_name, native_name, videoname)
                guessed_title = best_title_guess(query, *(aliases or metadata_values))
                parent_title = (
                    self._episode_parent_title(query, *metadata_values, fallback=guessed_title)
                    if episode
                    else None
                )
                file_languages = (
                    assrt_file_languages(file_name)
                    or (
                        ("",)
                        if len(file_names) > 1 and len(languages_in_pack) > 1
                        else languages_in_pack
                    )
                    or ("",)
                )
                for language in file_languages:
                    if language and requested_languages and language not in requested_languages:
                        continue
                    file_key = hashlib.blake2s(file_name.encode("utf-8"), digest_size=8).hexdigest()
                    results.append(
                        ProviderSubtitleResult(
                            id=f"assrt-result-{item.get('id')}-{file_key}",
                            match_id=f"assrt-match-{item.get('id')}",
                            provider=self.provider_code,
                            provider_label=self.provider_label,
                            title=parent_title or guessed_title,
                            year=extract_year(native_name, videoname, file_name),
                            imdb_id=None,
                            tmdb_id=None,
                            media_type="episode" if episode else "movie",
                            season=season,
                            episode=episode,
                            parent_title=parent_title,
                            language=language,
                            download_count=self._coerce_int(item.get("down_count")) or 0,
                            file_name=file_name,
                            match_score=title_similarity(query, aliases or metadata_values),
                            download_ref=str(item.get("id") or ""),
                            raw={
                                "file_name": file_name if file_names else None,
                                "title_aliases": aliases,
                            },
                        )
                    )
        return ProviderSearchCatalog(matches=[], results=results)

    async def download(self, result: ProviderSubtitleResult) -> Path:
        subtitle_id = str(result.download_ref or "")
        if not subtitle_id:
            raise SubtitleSourceError("ASSRT result is missing a subtitle id.")
        payload = await self._request(
            "/sub/detail", {"token": self.config.assrt_token, "id": subtitle_id}
        )
        subs = payload.get("sub", {}).get("subs", [])
        if not subs:
            raise SubtitleSourceError("ASSRT detail did not return subtitle files.")
        item = subs[0]
        if not isinstance(item, dict):
            raise SubtitleSourceError("ASSRT detail payload is malformed.")
        filelist = item.get("filelist") if isinstance(item.get("filelist"), list) else []
        if not filelist and str(item.get("filename", "")).casefold().endswith(SUBTITLE_EXTENSIONS):
            filelist = [{"f": item["filename"], "url": item.get("url")}]
        files = [
            entry
            for entry in filelist
            if isinstance(entry, dict)
            and str(entry.get("f", "")).casefold().endswith(SUBTITLE_EXTENSIONS)
            and entry.get("url")
        ]
        selected_name = result.raw.get("file_name")
        if selected_name:
            chosen = next((entry for entry in files if entry["f"] == selected_name), None)
            if chosen is None:
                raise SubtitleSourceError(
                    "ASSRT no longer provides the selected file. Search again."
                )
        else:
            matching = [
                entry for entry in files if result.language in assrt_file_languages(str(entry["f"]))
            ]
            if matching:
                chosen = matching[0]
            elif len(files) == 1 and not assrt_file_languages(str(files[0]["f"])):
                chosen = files[0]
            else:
                chosen = None
        if chosen is None:
            raise SubtitleSourceError(
                "ASSRT did not expose a subtitle file for the selected language."
            )
        direct_url = str(chosen["url"])
        file_name = str(chosen["f"])
        destination = contained_path(
            self._cache_dir,
            safe_segment(result.id, "assrt"),
            subtitle_file_name(file_name, "subtitle"),
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(
            timeout=provider_timeout(30.0), follow_redirects=True
        ) as client:
            response = await client.get(direct_url)
            response.raise_for_status()
            destination.write_bytes(response.content)
        return destination

    async def _request(self, path: str, params: dict[str, object]) -> dict[str, object]:
        async with httpx.AsyncClient(
            timeout=provider_timeout(30.0), follow_redirects=True
        ) as client:
            started = time.perf_counter()
            response = await client.get(f"{API_BASE}{path}", params=params)
            log_event(
                "provider.http",
                layer="backend",
                provider="assrt",
                method="GET",
                path=path,
                status_code=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000),
                params={key: value for key, value in params.items() if key != "token"},
            )
            response.raise_for_status()
        payload = response.json()
        if payload.get("status") not in {0, "0"}:
            raise SubtitleSourceError(str(payload))
        return payload

    def _coerce_int(self, value: object) -> int | None:
        try:
            return int(value) if value not in {None, ""} else None
        except (TypeError, ValueError):
            return None

    def _episode_parent_title(self, query: str, *values: str, fallback: str) -> str:
        query_key = canonical_title(self._strip_episode_or_season_marker(query))
        if not query_key:
            return fallback
        for value in values:
            for segment in self._latin_title_segments(value):
                if canonical_title(segment) == query_key:
                    return segment
        return fallback

    def _strip_episode_or_season_marker(self, value: str) -> str:
        text = unicodedata.normalize("NFKC", value)
        text = re.sub(r"\bS\d{1,2}E\d{1,3}\b.*$", "", text, flags=re.IGNORECASE)
        text = TRAILING_SEASON_PATTERN.sub("", text)
        return text.strip(" -_:.")

    def _latin_title_segments(self, value: str) -> list[str]:
        text = unicodedata.normalize("NFKC", value)
        text = re.sub(r"\bS\d{1,2}E\d{1,3}\b.*$", "", text, flags=re.IGNORECASE)
        text = YEAR_SUFFIX_PATTERN.sub("", text).strip()
        segments: list[str] = []
        for match in LATIN_TITLE_SEGMENT_PATTERN.finditer(text):
            segment = match.group(0).strip(" -_:.'’")
            if segment:
                segments.append(segment)
        return segments


_FILE_LANGUAGES = {
    "chs": "zh",
    "sc": "zh",
    "zh": "zh",
    "zh-cn": "zh",
    "zh-hans": "zh",
    "简体": "zh",
    "简体中文": "zh",
    "简中": "zh",
    "cht": "zht",
    "tc": "zht",
    "zht": "zht",
    "zh-tw": "zht",
    "zh-hant": "zht",
    "繁体": "zht",
    "繁體": "zht",
    "繁中": "zht",
    "繁體中文": "zht",
    "eng": "en",
    "en": "en",
    "english": "en",
    "英文": "en",
    "jpn": "ja",
    "ja": "ja",
    "日文": "ja",
    "kor": "ko",
    "ko": "ko",
    "fre": "fr",
    "fr": "fr",
    "ger": "de",
    "de": "de",
    "spa": "es",
    "es": "es",
}
_FILE_LANGUAGE_TAGS = "|".join(sorted(_FILE_LANGUAGES, key=len, reverse=True))
_FILE_LANGUAGE_PATTERN = re.compile(
    rf"(?:^|[. _\[(])((?:{_FILE_LANGUAGE_TAGS})(?:[+&._ -](?:{_FILE_LANGUAGE_TAGS}))*)[\])]*$",
    re.IGNORECASE,
)


def assrt_file_languages(file_name: str) -> tuple[str, ...]:
    stem = Path(file_name.replace("\\", "/")).stem
    suffix = _FILE_LANGUAGE_PATTERN.search(stem)
    if suffix is None:
        return ()
    return tuple(
        sorted(
            {
                _FILE_LANGUAGES[tag.casefold()]
                for tag in re.findall(_FILE_LANGUAGE_TAGS, suffix[1], re.IGNORECASE)
            }
        )
    )


def movie_title_aliases(*values: str) -> list[str]:
    aliases: list[str] = []
    for value in values:
        text = re.sub(r"\[[^]]*\]", " ", value)
        text = re.split(r"\b(?:19|20|21)\d{2}\b", text, maxsplit=1)[0].strip(" .(-_")
        for segment in re.split(r"/|\s+-\s+", text):
            # Release names often carry the native title next to a Latin alias.
            parts = [segment, *re.findall(r"[\u3400-\u9fff][\u3400-\u9fff！!？?：:·]*", segment)]
            for part in parts:
                cleaned = part.strip(" .(-_")
                if cleaned and cleaned not in aliases:
                    aliases.append(cleaned)
    return aliases
