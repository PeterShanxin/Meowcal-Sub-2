from dataclasses import replace

import httpx
import pytest

from meocosub2.config import AppConfig
from meocosub2.errors import SubtitleSourceError
from meocosub2.subtitle_sources.aggregator import SubtitleSearchAggregator
from meocosub2.subtitle_sources.assrt import AssrtProvider
from meocosub2.subtitle_sources.types import ProviderSearchCatalog, ProviderSubtitleMatch
from meocosub2.subtitle_sources.utils import canonical_imdb_id, map_assrt_languages


@pytest.fixture
def provider(tmp_path):
    provider = AssrtProvider(AppConfig(assrt_enabled=True, assrt_token="token"))
    provider._cache_dir = tmp_path
    return provider


def pack(files):
    return {
        "status": 0,
        "sub": {
            "subs": [
                {
                    "id": 42,
                    "native_name": "Paper Lanterns! 2026",
                    "videoname": "[Group] Paper Lanterns - 纸灯笼！ (2026) [1080p]",
                    "lang": {
                        "desc": "英 简 繁 双语",
                        "langlist": {"langeng": True, "langchs": True, "langcht": True},
                    },
                    "filelist": [
                        {"f": name, "url": f"https://files.example/{i}"}
                        for i, name in enumerate(files)
                    ],
                }
            ],
        },
    }


@pytest.mark.parametrize("value", ["tt1234567", "1234567", " TT01234567 "])
def test_movie_identity_accepts_numeric_and_prefixed_imdb_ids(value):
    assert canonical_imdb_id(value) == "tt1234567"


@pytest.mark.parametrize("value", [None, "", "0", "tt0000000", "tt-not-an-id"])
def test_missing_or_invalid_movie_identity_does_not_group_unrelated_titles(value):
    assert canonical_imdb_id(value) is None


def test_language_flags_keep_all_enabled_languages_without_inventing_chinese():
    assert map_assrt_languages(None, {"langeng": True, "langchs": True, "langcht": False}) == (
        "en",
        "zh",
    )
    assert map_assrt_languages("英 简 繁 双语") == ("en", "zh", "zht")
    assert map_assrt_languages("双语") == ()


@pytest.mark.asyncio
async def test_missing_language_metadata_keeps_the_member_available_as_unknown(
    provider, monkeypatch
):
    async def request(*args):
        payload = pack(["Lanterns.srt"])
        payload["sub"]["subs"][0].pop("lang")
        return payload

    monkeypatch.setattr(provider, "_request", request)
    catalog = await provider.search_catalog("Paper", "zh,en")
    assert [(r.file_name, r.language) for r in catalog.results] == [("Lanterns.srt", "")]


@pytest.mark.asyncio
async def test_detail_does_not_substitute_a_single_file_in_another_language(provider, monkeypatch):
    async def request(path, params):
        return pack([] if path.endswith("search") else ["Lanterns.eng.srt"])

    monkeypatch.setattr(provider, "_request", request)
    source = (await provider.search_catalog("Paper", "zh")).results[0]
    with pytest.raises(SubtitleSourceError, match="selected language"):
        await provider.download(source)


@pytest.mark.asyncio
async def test_unlabelled_multilingual_members_do_not_inherit_every_pack_language(
    provider, monkeypatch
):
    async def request(*args):
        return pack(["The English Patient.srt", "Track2.srt"])

    monkeypatch.setattr(provider, "_request", request)
    catalog = await provider.search_catalog("Paper", "zh,en")
    assert len(catalog.results) == 2
    assert all(result.language == "" for result in catalog.results)


@pytest.mark.asyncio
async def test_pack_exposes_each_file_in_its_languages(provider, monkeypatch):
    async def request(*args):
        return pack(
            [
                "Lanterns.chs.srt",
                "Lanterns.cht.srt",
                "Lanterns.chs&eng.ass",
                "Lanterns.eng.srt",
                "readme.txt",
            ]
        )

    monkeypatch.setattr(provider, "_request", request)
    catalog = await provider.search_catalog("纸灯笼", "en,zh,zht")
    assert {(r.file_name, r.language) for r in catalog.results} == {
        ("Lanterns.chs.srt", "zh"),
        ("Lanterns.cht.srt", "zht"),
        ("Lanterns.chs&eng.ass", "zh"),
        ("Lanterns.chs&eng.ass", "en"),
        ("Lanterns.eng.srt", "en"),
    }
    assert len({(r.id, r.language) for r in catalog.results}) == 5
    assert all(r.year == 2026 for r in catalog.results)


@pytest.mark.asyncio
async def test_download_keeps_selected_file_when_detail_order_changes(
    provider, monkeypatch, respx_mock
):
    async def request(path, params):
        names = ["Lanterns.chs.srt", "Lanterns.cht.srt", "Lanterns.eng.srt"]
        return pack(names if path.endswith("search") else list(reversed(names)))

    monkeypatch.setattr(provider, "_request", request)
    catalog = await provider.search_catalog("纸灯笼", "zht")
    assert len(catalog.results) == 1
    route = respx_mock.get("https://files.example/1").mock(
        return_value=httpx.Response(200, content=b"traditional subtitle")
    )
    path = await provider.download(catalog.results[0])
    assert path.name == "Lanterns.cht.srt"
    assert path.read_bytes() == b"traditional subtitle"
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_missing_selected_file_does_not_download_another_language(provider, monkeypatch):
    async def request(path, params):
        return pack(["Lanterns.cht.srt"] if path.endswith("search") else ["Lanterns.chs.srt"])

    monkeypatch.setattr(provider, "_request", request)
    selected = (await provider.search_catalog("纸灯笼", "zht")).results[0]
    with pytest.raises(SubtitleSourceError, match="selected file"):
        await provider.download(selected)


@pytest.mark.asyncio
async def test_movie_alias_merges_files_into_existing_title_without_merging_other_years(
    provider, monkeypatch
):
    async def request(*args):
        return pack(["Lanterns.chs.srt"])

    monkeypatch.setattr(provider, "_request", request)
    assrt = await provider.search_catalog("Paper Lanterns", "zh")
    original = ProviderSubtitleMatch(
        "os-match", "opensubtitles", "OpenSubtitles", "纸灯笼！", 2026, "tt123", "456", "movie"
    )
    aggregator = SubtitleSearchAggregator(AppConfig())
    catalog = aggregator._merge_catalogs([ProviderSearchCatalog([original], []), assrt], "zh")
    assert len(catalog.matches) == 1
    assert catalog.results[0].match_id == catalog.matches[0].id
    different = aggregator._merge_catalogs(
        [ProviderSearchCatalog([replace(original, year=1985)], []), assrt], "zh"
    )
    assert len(different.matches) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse", [False, True])
async def test_late_movie_alias_with_the_same_imdb_keeps_selected_files_grouped(
    provider, monkeypatch, reverse
):
    async def request(*args):
        payload = pack(["Lanterns.chs.srt", "Lanterns.eng.srt"])
        payload["sub"]["subs"][0]["native_name"] = "纸灯笼！ 2026"
        return payload

    monkeypatch.setattr(provider, "_request", request)
    assrt = await provider.search_catalog("Paper Lanterns", "zh,en")
    english = ProviderSubtitleMatch(
        "sd-movie", "subdl", "SubDL", "Paper Lanterns!", 2026, "tt1234567", "456", "movie"
    )
    native = replace(
        english,
        id="os-movie",
        provider="opensubtitles",
        provider_label="OpenSubtitles",
        title="纸灯笼！",
        imdb_id="1234567",
    )
    aggregator = SubtitleSearchAggregator(AppConfig())
    early = aggregator._merge_catalogs([ProviderSearchCatalog([english], []), assrt], "zh,en")
    catalogs = [ProviderSearchCatalog([english], []), assrt, ProviderSearchCatalog([native], [])]
    final = aggregator._merge_catalogs(catalogs[::-1] if reverse else catalogs, "zh,en")
    assert len(early.matches) == len(final.matches) == 1
    assert early.matches[0].id == final.matches[0].id
    assert early.works[0].id == final.works[0].id
    assert {(r.result_id, r.match_id) for r in early.results} == {
        (r.result_id, r.match_id) for r in final.results
    }
    assert set(final.matches[0].providers) == {"assrt", "subdl", "opensubtitles"}


def test_same_movie_title_with_different_imdb_ids_does_not_merge():
    original = ProviderSubtitleMatch(
        "sd-movie", "subdl", "SubDL", "Paper Lanterns", 2026, "tt1234567", None, "movie"
    )
    other = replace(original, id="os-movie", provider="opensubtitles", imdb_id="7654321")
    catalog = SubtitleSearchAggregator(AppConfig())._merge_catalogs(
        [ProviderSearchCatalog([original, other], [])], "zh,en"
    )
    assert len(catalog.matches) == len(catalog.works) == 2


@pytest.mark.asyncio
async def test_yearless_assrt_member_still_joins_a_known_movie(provider, monkeypatch):
    async def request(*args):
        return pack(["Lanterns.chs.srt"])

    monkeypatch.setattr(provider, "_request", request)
    assrt = await provider.search_catalog("Paper Lanterns", "zh")
    assrt.results[0].year = None
    original = ProviderSubtitleMatch(
        "sd-movie", "subdl", "SubDL", assrt.results[0].title, 2026, "tt1234567", None, "movie"
    )
    catalog = SubtitleSearchAggregator(AppConfig())._merge_catalogs(
        [ProviderSearchCatalog([original], []), assrt], "zh"
    )
    assert len(catalog.matches) == 1
    assert catalog.results[0].match_id == catalog.matches[0].id
