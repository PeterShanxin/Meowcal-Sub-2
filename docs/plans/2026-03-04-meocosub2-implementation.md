# MeoCoSub2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python CLI app that fetches subtitles from OpenSubtitles, optionally translates them via Foundry Local, then syncs display via periodic OCR fuzzy matching and a floating web overlay.

**Architecture:** CLI entry point (`typer`) orchestrates subtitle acquisition (OpenSubtitles REST API), optional local LLM batch translation (Foundry Local), and a live sync loop (screen capture → OCR → rapidfuzz match → WebSocket broadcast to a FastAPI overlay server).

**Tech Stack:** Python 3.11+, typer, httpx, pysubs2, mss, winocr, rapidfuzz, openai SDK, fastapi, uvicorn, tomllib (stdlib), tomli-w, pytest, pytest-asyncio, respx, pytest-mock

**Design doc:** `D:/Repos/Meowcal-Sub/docs/plans/2026-03-04-meocosub2-design.md`

---

## Task 1: Project Skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `src/meocosub2/__init__.py`
- Create: `src/meocosub2/models.py`
- Create: `tests/__init__.py`
- Create: `tests/test_models.py`

---

**Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "meocosub2"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "typer[all]>=0.9",
    "httpx>=0.25",
    "pysubs2>=1.6",
    "mss>=9.0",
    "winocr>=0.2",
    "rapidfuzz>=3.0",
    "openai>=1.0",
    "fastapi>=0.100",
    "uvicorn[standard]>=0.23",
    "tomli-w>=1.0",
]

[project.scripts]
meocosub2 = "meocosub2.cli:app"

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "respx>=0.21",
    "pytest-mock>=3.12",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.hatch.build.targets.wheel]
packages = ["src/meocosub2"]
```

**Step 2: Create `src/meocosub2/__init__.py`**

```python
__version__ = "0.1.0"
```

**Step 3: Write the failing test for models**

`tests/test_models.py`:
```python
from meocosub2.models import SubtitleLine, SubtitlePair, MatchResult


def test_subtitle_line_defaults():
    line = SubtitleLine(index=0, start_ms=1000, end_ms=3000, text="Hello")
    assert line.translated == ""
    assert line.index == 0


def test_subtitle_pair_empty_target():
    source = [SubtitleLine(index=0, start_ms=0, end_ms=1000, text="Hi")]
    pair = SubtitlePair(source_lines=source, target_lines=[])
    assert len(pair.target_lines) == 0


def test_match_result_fields():
    result = MatchResult(line_index=5, score=87.3, source_text="Hello", target_text="你好")
    assert result.line_index == 5
    assert result.score == 87.3
```

**Step 4: Run test to verify it fails**

```
cd D:/Repos/Meowcal-Sub2
pip install -e ".[dev]"
pytest tests/test_models.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'meocosub2.models'`

**Step 5: Create `src/meocosub2/models.py`**

```python
from dataclasses import dataclass, field


@dataclass
class SubtitleLine:
    index: int
    start_ms: int
    end_ms: int
    text: str
    translated: str = ""


@dataclass
class SubtitlePair:
    source_lines: list[SubtitleLine]
    target_lines: list[SubtitleLine] = field(default_factory=list)


@dataclass
class MatchResult:
    line_index: int
    score: float
    source_text: str
    target_text: str
```

**Step 6: Run test to verify it passes**

```
pytest tests/test_models.py -v
```
Expected: 3 PASSED

**Step 7: Commit**

```bash
git init
git add pyproject.toml src/ tests/
git commit -m "feat: project skeleton with models"
```

---

## Task 2: Configuration

**Files:**
- Create: `src/meocosub2/config.py`
- Create: `tests/test_config.py`

---

**Step 1: Write the failing tests**

`tests/test_config.py`:
```python
import tomllib
from pathlib import Path
import pytest
from meocosub2.config import AppConfig, load_config, save_config


def test_default_config():
    cfg = AppConfig()
    assert cfg.source_language == "en"
    assert cfg.target_language == "zh"
    assert cfg.capture_interval_ms == 1500
    assert cfg.fuzzy_threshold == 65
    assert cfg.overlay_port == 8765


def test_save_and_load_roundtrip(tmp_path):
    cfg = AppConfig(source_language="ja", target_language="en", overlay_font_size=32)
    config_file = tmp_path / "config.toml"
    save_config(cfg, config_file)
    loaded = load_config(config_file)
    assert loaded.source_language == "ja"
    assert loaded.target_language == "en"
    assert loaded.overlay_font_size == 32


def test_load_missing_file_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "nonexistent.toml")
    assert cfg.source_language == "en"


def test_save_creates_parent_dirs(tmp_path):
    cfg = AppConfig()
    config_file = tmp_path / "sub" / "dir" / "config.toml"
    save_config(cfg, config_file)
    assert config_file.exists()
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_config.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'meocosub2.config'`

**Step 3: Create `src/meocosub2/config.py`**

```python
from __future__ import annotations
import tomllib
import tomli_w
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class AppConfig:
    # OpenSubtitles
    opensubtitles_api_key: str = ""
    opensubtitles_username: str = ""
    opensubtitles_password: str = ""

    # Languages (ISO 639-2B for OpenSubtitles API)
    source_language: str = "en"
    target_language: str = "zh"

    # Capture + OCR
    capture_region: list[int] = field(default_factory=list)  # [x, y, w, h] or empty
    capture_interval_ms: int = 1500
    ocr_language: str = "en"

    # Matching
    fuzzy_threshold: int = 65
    match_window_size: int = 30

    # Translation (Foundry Local)
    foundry_endpoint: str = "http://127.0.0.1:5273/v1"
    foundry_model: str = ""
    translation_timeout_s: int = 30
    translation_batch_size: int = 5

    # Overlay
    overlay_port: int = 8765
    overlay_font_size: int = 28
    overlay_font_family: str = "Segoe UI"
    overlay_text_color: str = "#FFFFFF"
    overlay_bg_color: str = "rgba(0,0,0,0.75)"
    overlay_position: str = "bottom"


def _default_config_path() -> Path:
    import os
    appdata = os.environ.get("APPDATA", Path.home())
    return Path(appdata) / "meocosub2" / "config.toml"


def load_config(path: Path | None = None) -> AppConfig:
    path = path or _default_config_path()
    if not path.exists():
        return AppConfig()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    # Flatten nested TOML sections into flat dict matching AppConfig fields
    flat: dict = {}
    flat.update(data.get("opensubtitles", {}))
    flat.update({
        "source_language": data.get("languages", {}).get("source", "en"),
        "target_language": data.get("languages", {}).get("target", "zh"),
    })
    flat.update(data.get("capture", {}))
    flat.update(data.get("matching", {}))
    flat.update(data.get("translation", {}))
    # Overlay fields prefixed to avoid collision
    overlay = data.get("overlay", {})
    flat.update({f"overlay_{k}": v for k, v in overlay.items()})
    # Filter to known fields only
    known = {f.name for f in AppConfig.__dataclass_fields__.values()}
    return AppConfig(**{k: v for k, v in flat.items() if k in known})


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    path = path or _default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "opensubtitles": {
            "api_key": cfg.opensubtitles_api_key,
            "username": cfg.opensubtitles_username,
            "password": cfg.opensubtitles_password,
        },
        "languages": {
            "source": cfg.source_language,
            "target": cfg.target_language,
        },
        "capture": {
            "region": cfg.capture_region,
            "interval_ms": cfg.capture_interval_ms,
            "ocr_language": cfg.ocr_language,
        },
        "matching": {
            "fuzzy_threshold": cfg.fuzzy_threshold,
            "window_size": cfg.match_window_size,
        },
        "translation": {
            "endpoint": cfg.foundry_endpoint,
            "model": cfg.foundry_model,
            "timeout_s": cfg.translation_timeout_s,
            "batch_size": cfg.translation_batch_size,
        },
        "overlay": {
            "port": cfg.overlay_port,
            "font_size": cfg.overlay_font_size,
            "font_family": cfg.overlay_font_family,
            "text_color": cfg.overlay_text_color,
            "bg_color": cfg.overlay_bg_color,
            "position": cfg.overlay_position,
        },
    }
    with open(path, "wb") as f:
        tomli_w.dump(doc, f)
```

**Step 4: Run tests to verify they pass**

```
pytest tests/test_config.py -v
```
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add src/meocosub2/config.py tests/test_config.py
git commit -m "feat: config loading and saving (TOML)"
```

---

## Task 3: CLI Skeleton

**Files:**
- Create: `src/meocosub2/cli.py`
- Create: `tests/test_cli.py`

---

**Step 1: Write the failing tests**

`tests/test_cli.py`:
```python
from typer.testing import CliRunner
from meocosub2.cli import app

runner = CliRunner()


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "search" in result.output


def test_search_requires_title():
    result = runner.invoke(app, ["search"])
    assert result.exit_code != 0


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_cli.py -v
```
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Create `src/meocosub2/cli.py`**

```python
from __future__ import annotations
import typer
from typing import Optional
from meocosub2 import __version__

app = typer.Typer(help="MeoCoSub2 — fetch, translate, and sync subtitles for any video.")


def _version_callback(value: bool):
    if value:
        typer.echo(f"meocosub2 {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(None, "--version", callback=_version_callback, is_eager=True),
):
    pass


@app.command()
def search(title: str = typer.Argument(..., help="Movie or show title to search for")):
    """Search OpenSubtitles for subtitle files."""
    typer.echo(f"[stub] Searching for: {title}")


@app.command()
def download(file_id: int = typer.Argument(..., help="OpenSubtitles file_id to download")):
    """Download a subtitle file by file_id."""
    typer.echo(f"[stub] Downloading file_id: {file_id}")


@app.command()
def translate(srt_file: str = typer.Argument(..., help="Path to .srt file to translate")):
    """Batch translate a subtitle file using Foundry Local."""
    typer.echo(f"[stub] Translating: {srt_file}")


@app.command()
def start():
    """Start the sync loop (uses already-downloaded subtitles)."""
    typer.echo("[stub] Starting sync loop...")


@app.command()
def run(title: str = typer.Argument(..., help="Movie or show title")):
    """Full flow: search, download, translate if needed, start overlay."""
    typer.echo(f"[stub] Full run for: {title}")
```

**Step 4: Run tests to verify they pass**

```
pytest tests/test_cli.py -v
```
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add src/meocosub2/cli.py tests/test_cli.py
git commit -m "feat: CLI skeleton with all commands stubbed"
```

---

## Task 4: Subtitle Parser

**Files:**
- Create: `src/meocosub2/subtitles.py`
- Create: `tests/fixtures/sample.srt`
- Create: `tests/test_subtitles.py`

---

**Step 1: Create fixture SRT file**

`tests/fixtures/sample.srt`:
```
1
00:00:01,000 --> 00:00:03,500
Hello, welcome to the movie.

2
00:00:04,000 --> 00:00:06,000
This is the second subtitle line.

3
00:00:07,500 --> 00:00:10,000
<i>An italic line with formatting.</i>
```

**Step 2: Write the failing tests**

`tests/test_subtitles.py`:
```python
from pathlib import Path
import pytest
from meocosub2.subtitles import load_subtitle_file, align_subtitles
from meocosub2.models import SubtitleLine, SubtitlePair

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_srt_parses_lines():
    lines = load_subtitle_file(FIXTURES / "sample.srt")
    assert len(lines) == 3
    assert lines[0].index == 0
    assert lines[0].text == "Hello, welcome to the movie."
    assert lines[0].start_ms == 1000
    assert lines[0].end_ms == 3500


def test_load_srt_strips_formatting_tags():
    lines = load_subtitle_file(FIXTURES / "sample.srt")
    # pysubs2 should strip <i> tags from plain text
    assert "<i>" not in lines[2].text


def test_align_subtitles_pairs_by_index():
    source = [
        SubtitleLine(index=0, start_ms=0, end_ms=1000, text="Hello"),
        SubtitleLine(index=1, start_ms=1000, end_ms=2000, text="World"),
    ]
    target = [
        SubtitleLine(index=0, start_ms=0, end_ms=1000, text="你好"),
        SubtitleLine(index=1, start_ms=1000, end_ms=2000, text="世界"),
    ]
    pair = align_subtitles(source, target)
    assert pair.source_lines[0].text == "Hello"
    assert pair.target_lines[0].text == "你好"
    assert len(pair.source_lines) == 2


def test_align_subtitles_empty_target():
    source = [SubtitleLine(index=0, start_ms=0, end_ms=1000, text="Hello")]
    pair = align_subtitles(source, [])
    assert len(pair.target_lines) == 0
```

**Step 3: Run test to verify it fails**

```
pytest tests/test_subtitles.py -v
```
Expected: FAIL — `ModuleNotFoundError`

**Step 4: Create `src/meocosub2/subtitles.py`**

```python
from __future__ import annotations
from pathlib import Path
import pysubs2
from meocosub2.models import SubtitleLine, SubtitlePair


def load_subtitle_file(path: Path) -> list[SubtitleLine]:
    """Parse a subtitle file (.srt/.ass/.ssa) into SubtitleLine objects."""
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            subs = pysubs2.load(str(path), encoding=encoding)
            break
        except (UnicodeDecodeError, pysubs2.exceptions.UnknownFPSError):
            continue
    else:
        raise ValueError(f"Could not decode subtitle file: {path}")

    lines = []
    for i, event in enumerate(subs):
        if event.is_comment:
            continue
        # plaintext() strips formatting tags
        text = event.plaintext.strip()
        if not text:
            continue
        lines.append(SubtitleLine(
            index=len(lines),
            start_ms=event.start,
            end_ms=event.end,
            text=text,
        ))
    return lines


def align_subtitles(
    source: list[SubtitleLine],
    target: list[SubtitleLine],
) -> SubtitlePair:
    """Pair source and target subtitle lines by index."""
    return SubtitlePair(source_lines=source, target_lines=target)
```

**Step 5: Run tests to verify they pass**

```
pytest tests/test_subtitles.py -v
```
Expected: 4 PASSED

**Step 6: Commit**

```bash
git add src/meocosub2/subtitles.py tests/test_subtitles.py tests/fixtures/
git commit -m "feat: subtitle parser (pysubs2 wrapper)"
```

---

## Task 5: OpenSubtitles API Client

**Files:**
- Create: `src/meocosub2/opensubtitles/__init__.py`
- Create: `src/meocosub2/opensubtitles/types.py`
- Create: `src/meocosub2/opensubtitles/client.py`
- Create: `tests/test_opensubtitles.py`

---

**Step 1: Create `src/meocosub2/opensubtitles/types.py`**

```python
from dataclasses import dataclass


@dataclass
class SubtitleFile:
    file_id: int
    file_name: str


@dataclass
class SearchResult:
    id: str
    title: str
    year: int | None
    imdb_id: str | None
    media_type: str         # "movie" or "episode"
    season: int | None
    episode: int | None
    language: str
    download_count: int
    file_id: int
    file_name: str

    def display_label(self) -> str:
        if self.media_type == "episode" and self.season and self.episode:
            return f"{self.title} S{self.season:02d}E{self.episode:02d} ({self.year}) [{self.language}]"
        return f"{self.title} ({self.year}) [{self.language}]"
```

**Step 2: Write the failing tests**

`tests/test_opensubtitles.py`:
```python
import pytest
import respx
import httpx
from pathlib import Path
from meocosub2.opensubtitles.client import OpenSubtitlesClient
from meocosub2.opensubtitles.types import SearchResult

BASE_URL = "https://api.opensubtitles.com/api/v1"

SEARCH_RESPONSE = {
    "data": [
        {
            "id": "123",
            "type": "subtitle",
            "attributes": {
                "language": "en",
                "download_count": 5000,
                "feature_details": {
                    "feature_type": "Movie",
                    "title": "Inception",
                    "year": 2010,
                    "imdb_id": "tt1375666",
                    "season_number": None,
                    "episode_number": None,
                },
                "files": [{"file_id": 9001, "file_name": "Inception.srt"}],
            },
        }
    ],
    "total_count": 1,
}

DOWNLOAD_RESPONSE = {
    "link": "https://dl.opensubtitles.com/abc/Inception.srt",
    "file_name": "Inception.srt",
    "remaining": 19,
    "reset_time": "2026-03-05T00:00:00Z",
}


@pytest.fixture
def client():
    return OpenSubtitlesClient(api_key="test-key", user_agent="MeoCoSub2/0.1")


@respx.mock
@pytest.mark.asyncio
async def test_search_returns_results(client):
    respx.get(f"{BASE_URL}/subtitles").mock(
        return_value=httpx.Response(200, json=SEARCH_RESPONSE)
    )
    results = await client.search("Inception", languages="en")
    assert len(results) == 1
    assert results[0].title == "Inception"
    assert results[0].file_id == 9001
    assert results[0].language == "en"


@respx.mock
@pytest.mark.asyncio
async def test_search_passes_language_param(client):
    route = respx.get(f"{BASE_URL}/subtitles").mock(
        return_value=httpx.Response(200, json={"data": [], "total_count": 0})
    )
    await client.search("Inception", languages="en,zh")
    assert route.called
    assert "en,zh" in str(route.calls[0].request.url)


@respx.mock
@pytest.mark.asyncio
async def test_get_download_link(client):
    respx.post(f"{BASE_URL}/download").mock(
        return_value=httpx.Response(200, json=DOWNLOAD_RESPONSE)
    )
    link, remaining = await client.get_download_link(file_id=9001)
    assert link == "https://dl.opensubtitles.com/abc/Inception.srt"
    assert remaining == 19


@respx.mock
@pytest.mark.asyncio
async def test_rate_limit_retry(client):
    respx.get(f"{BASE_URL}/subtitles").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "1"}, json={}),
        httpx.Response(200, json=SEARCH_RESPONSE),
    ])
    results = await client.search("Inception", languages="en")
    assert len(results) == 1
```

**Step 3: Run test to verify it fails**

```
pytest tests/test_opensubtitles.py -v
```
Expected: FAIL — `ModuleNotFoundError`

**Step 4: Create `src/meocosub2/opensubtitles/__init__.py`** (empty)

**Step 5: Create `src/meocosub2/opensubtitles/client.py`**

```python
from __future__ import annotations
import asyncio
import httpx
from meocosub2.opensubtitles.types import SearchResult

BASE_URL = "https://api.opensubtitles.com/api/v1"
MAX_RETRIES = 3


class OpenSubtitlesClient:
    def __init__(self, api_key: str, user_agent: str = "MeoCoSub2/0.1"):
        self._headers = {
            "Api-Key": api_key,
            "User-Agent": user_agent,
            "Content-Type": "application/json",
        }

    async def search(
        self,
        query: str,
        languages: str,
        media_type: str | None = None,
    ) -> list[SearchResult]:
        params: dict = {"query": query, "languages": languages}
        if media_type:
            params["type"] = media_type

        data = await self._get("/subtitles", params=params)
        return [self._parse_result(item) for item in data.get("data", [])]

    async def get_download_link(self, file_id: int) -> tuple[str, int]:
        """Returns (download_url, remaining_quota)."""
        data = await self._post("/download", json={"file_id": file_id})
        return data["link"], data.get("remaining", 0)

    def _parse_result(self, item: dict) -> SearchResult:
        attrs = item["attributes"]
        feat = attrs.get("feature_details", {})
        files = attrs.get("files", [{}])
        first_file = files[0] if files else {}
        return SearchResult(
            id=item["id"],
            title=feat.get("title", "Unknown"),
            year=feat.get("year"),
            imdb_id=feat.get("imdb_id"),
            media_type=feat.get("feature_type", "Movie").lower(),
            season=feat.get("season_number"),
            episode=feat.get("episode_number"),
            language=attrs.get("language", ""),
            download_count=attrs.get("download_count", 0),
            file_id=first_file.get("file_id", 0),
            file_name=first_file.get("file_name", ""),
        )

    async def _get(self, path: str, params: dict | None = None) -> dict:
        return await self._request("GET", path, params=params)

    async def _post(self, path: str, json: dict | None = None) -> dict:
        return await self._request("POST", path, json=json)

    async def _request(
        self, method: str, path: str, *, params=None, json=None
    ) -> dict:
        for attempt in range(MAX_RETRIES):
            async with httpx.AsyncClient(headers=self._headers) as client:
                response = await client.request(
                    method, BASE_URL + path, params=params, json=json, timeout=10.0
                )
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 2 ** attempt))
                await asyncio.sleep(retry_after)
                continue
            response.raise_for_status()
            return response.json()
        raise httpx.HTTPStatusError(
            "Rate limit exceeded after retries", request=None, response=None
        )
```

**Step 6: Run tests to verify they pass**

```
pytest tests/test_opensubtitles.py -v
```
Expected: 4 PASSED

**Step 7: Commit**

```bash
git add src/meocosub2/opensubtitles/ tests/test_opensubtitles.py
git commit -m "feat: OpenSubtitles API client with rate limit retry"
```

---

## Task 6: Fuzzy Matcher (Core Algorithm)

**Files:**
- Create: `src/meocosub2/matcher.py`
- Create: `tests/test_matcher.py`

---

**Step 1: Write the failing tests**

`tests/test_matcher.py`:
```python
import pytest
from meocosub2.matcher import SubtitleMatcher
from meocosub2.models import SubtitleLine


def make_lines(texts: list[str]) -> list[SubtitleLine]:
    return [
        SubtitleLine(index=i, start_ms=i * 3000, end_ms=(i + 1) * 3000, text=t)
        for i, t in enumerate(texts)
    ]


def test_exact_match():
    lines = make_lines(["Hello world", "Good morning", "How are you"])
    matcher = SubtitleMatcher(lines, threshold=60)
    result = matcher.match("Hello world")
    assert result is not None
    assert result.line_index == 0
    assert result.score >= 90


def test_partial_ocr_match():
    # OCR might capture only part of the subtitle line
    lines = make_lines(["The quick brown fox jumps over the lazy dog"])
    matcher = SubtitleMatcher(lines, threshold=60)
    result = matcher.match("quick brown fox jumps")
    assert result is not None
    assert result.line_index == 0


def test_ocr_with_formatting_tags_ignored():
    lines = make_lines(["<i>Hello world</i>"])
    matcher = SubtitleMatcher(lines, threshold=60)
    result = matcher.match("Hello world")
    assert result is not None


def test_duplicate_frame_returns_none():
    lines = make_lines(["Hello world"])
    matcher = SubtitleMatcher(lines, threshold=60)
    matcher.match("Hello world")  # First call updates hash
    result = matcher.match("Hello world")  # Identical second call
    assert result is None


def test_noise_too_short_returns_none():
    lines = make_lines(["Hello world"])
    matcher = SubtitleMatcher(lines, threshold=60)
    result = matcher.match("Hi")
    assert result is None


def test_below_threshold_returns_none():
    lines = make_lines(["The quick brown fox"])
    matcher = SubtitleMatcher(lines, threshold=90)
    result = matcher.match("completely unrelated text here")
    assert result is None


def test_windowed_search_advances_forward():
    # After matching line 10, search should find line 11 next, not restart from 0
    texts = [f"Line number {i}" for i in range(100)]
    lines = make_lines(texts)
    matcher = SubtitleMatcher(lines, threshold=60)

    # Match line 10
    r1 = matcher.match("Line number 10")
    assert r1 is not None
    assert r1.line_index == 10

    # Now match line 15 (within window)
    r2 = matcher.match("Line number 15")
    assert r2 is not None
    assert r2.line_index == 15


def test_returns_target_text_when_translated():
    lines = make_lines(["Hello world"])
    lines[0].translated = "你好世界"
    matcher = SubtitleMatcher(lines, threshold=60)
    result = matcher.match("Hello world")
    assert result.target_text == "你好世界"


def test_returns_source_text_when_no_translation():
    lines = make_lines(["Hello world"])
    matcher = SubtitleMatcher(lines, threshold=60)
    result = matcher.match("Hello world")
    assert result.target_text == "Hello world"
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_matcher.py -v
```
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Create `src/meocosub2/matcher.py`**

```python
from __future__ import annotations
import re
from rapidfuzz import fuzz, process
from meocosub2.models import SubtitleLine, MatchResult

_TAG_RE = re.compile(r'<[^>]+>|\{[^}]+\}')
_HI_RE = re.compile(r'[\[\(][^\]\)]*[\]\)]')
_SPACE_RE = re.compile(r'\s+')


def _normalize(text: str) -> str:
    text = _TAG_RE.sub('', text)
    text = _HI_RE.sub('', text)
    text = text.lower()
    text = _SPACE_RE.sub(' ', text).strip()
    return text


class SubtitleMatcher:
    def __init__(self, lines: list[SubtitleLine], threshold: int = 65):
        self.lines = lines
        self.threshold = threshold
        self._last_index: int = -1
        self._last_ocr_hash: int | None = None
        self._normalized: list[str] = [_normalize(line.text) for line in lines]

    def match(self, ocr_text: str) -> MatchResult | None:
        # Deduplicate identical frames
        ocr_hash = hash(ocr_text.strip().lower())
        if ocr_hash == self._last_ocr_hash:
            return None
        self._last_ocr_hash = ocr_hash

        normalized_ocr = _normalize(ocr_text)
        if len(normalized_ocr) < 3:
            return None

        result = self._search_window(normalized_ocr)
        if result is None:
            result = self._search_full(normalized_ocr)
        if result is None:
            return None

        idx, score = result
        self._last_index = idx
        line = self.lines[idx]
        return MatchResult(
            line_index=idx,
            score=score,
            source_text=line.text,
            target_text=line.translated or line.text,
        )

    def _search_window(self, normalized_ocr: str) -> tuple[int, float] | None:
        if self._last_index < 0:
            start, end = 0, min(50, len(self._normalized))
        else:
            start = max(0, self._last_index - 5)
            end = min(len(self._normalized), self._last_index + 30)

        candidates = self._normalized[start:end]
        if not candidates:
            return None

        result = process.extractOne(
            normalized_ocr, candidates,
            scorer=fuzz.token_set_ratio,
            score_cutoff=self.threshold,
        )
        if result is None:
            return None
        # result = (matched_text, score, index_within_candidates)
        return start + result[2], result[1]

    def _search_full(self, normalized_ocr: str) -> tuple[int, float] | None:
        result = process.extractOne(
            normalized_ocr, self._normalized,
            scorer=fuzz.token_set_ratio,
            score_cutoff=self.threshold,
        )
        if result is None:
            return None
        return result[2], result[1]
```

**Step 4: Run tests to verify they pass**

```
pytest tests/test_matcher.py -v
```
Expected: 9 PASSED

**Step 5: Commit**

```bash
git add src/meocosub2/matcher.py tests/test_matcher.py
git commit -m "feat: fuzzy subtitle matcher with windowed search"
```

---

## Task 7: Screen Capture + OCR Preprocessing + OCR

> **Note:** MeoCoSub1 (Rust) improved OCR quality via a preprocessing pipeline: grayscale → histogram equalization → binary threshold at 128. We implement the same pipeline here using PIL, which makes all three steps trivial. The preprocessing is applied before handing the image to Windows OCR. Reference: `D:/Repos/Meowcal-Sub/src-tauri/src/ocr/preprocessing.rs`.

**Files:**
- Create: `src/meocosub2/capture.py`
- Create: `tests/test_capture.py`

---

**Step 1: Write the failing tests**

`tests/test_capture.py`:
```python
import pytest
from unittest.mock import MagicMock, AsyncMock
from PIL import Image, ImageOps
from meocosub2.capture import capture_region, ocr_image, preprocess_for_ocr


def test_capture_region_returns_pil_image(mocker):
    mock_sct = MagicMock()
    mock_sct.__enter__ = MagicMock(return_value=mock_sct)
    mock_sct.__exit__ = MagicMock(return_value=False)
    mock_screenshot = MagicMock()
    mock_screenshot.rgb = b'\xff\xff\xff' * 100 * 50  # 100x50 white image
    mock_screenshot.size = (100, 50)
    mock_sct.grab.return_value = mock_screenshot
    mocker.patch("mss.mss", return_value=mock_sct)

    img = capture_region((0, 0, 100, 50))
    assert isinstance(img, Image.Image)
    assert img.size == (100, 50)


def test_preprocess_converts_to_grayscale():
    # RGB input should come out as grayscale (L mode)
    img = Image.new("RGB", (10, 10), color=(100, 150, 200))
    result = preprocess_for_ocr(img)
    assert result.mode == "L"


def test_preprocess_binarizes_output():
    # After preprocessing, all pixels must be 0 or 255
    img = Image.new("RGB", (20, 20), color=(80, 80, 80))
    result = preprocess_for_ocr(img)
    for pixel in result.getdata():
        assert pixel in (0, 255), f"Expected 0 or 255, got {pixel}"


def test_preprocess_binarize_threshold():
    # Pixel below 128 → 0 (black), at/above 128 → 255 (white)
    # Create a pure-value grayscale image with known intensity
    img = Image.new("L", (4, 1))
    img.putdata([0, 127, 128, 255])
    # Skip EQ for this test by calling binarize directly
    result = img.point(lambda x: 0 if x < 128 else 255)
    pixels = list(result.getdata())
    assert pixels[0] == 0    # 0 → black
    assert pixels[1] == 0    # 127 → black
    assert pixels[2] == 255  # 128 → white
    assert pixels[3] == 255  # 255 → white


@pytest.mark.asyncio
async def test_ocr_image_returns_string(mocker):
    mock_image = Image.new("RGB", (200, 50), color=(255, 255, 255))
    mocker.patch(
        "meocosub2.capture._run_ocr",
        new=AsyncMock(return_value="Hello world"),
    )
    text = await ocr_image(mock_image, "en")
    assert text == "Hello world"


@pytest.mark.asyncio
async def test_ocr_image_returns_empty_on_failure(mocker):
    mock_image = Image.new("RGB", (50, 20))
    mocker.patch(
        "meocosub2.capture._run_ocr",
        new=AsyncMock(side_effect=Exception("OCR failed")),
    )
    text = await ocr_image(mock_image, "en")
    assert text == ""
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_capture.py -v
```
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Create `src/meocosub2/capture.py`**

```python
from __future__ import annotations
import asyncio
from PIL import Image, ImageOps
import mss


def capture_region(region: tuple[int, int, int, int]) -> Image.Image:
    """Capture a screen region. region = (x, y, width, height)."""
    x, y, w, h = region
    monitor = {"left": x, "top": y, "width": w, "height": h}
    with mss.mss() as sct:
        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
    return img


def preprocess_for_ocr(image: Image.Image) -> Image.Image:
    """Apply the same 3-step preprocessing pipeline as MeoCoSub1.

    Pipeline: Grayscale → Histogram Equalization → Binary Threshold (128)

    Grayscale reduces noise from color variation. Histogram equalization
    stretches contrast so dark subtitle text pops against any background.
    Binarizing at 128 (after EQ) gives Windows OCR a clean black/white
    image with no ambiguous mid-grays.
    """
    # Step 1: Grayscale (PIL uses luminance formula: 0.299R + 0.587G + 0.114B)
    gray = image.convert("L")

    # Step 2: Histogram equalization — stretches contrast to full 0-255 range
    equalized = ImageOps.equalize(gray)

    # Step 3: Binary threshold at midpoint 128 (post-EQ so midpoint is meaningful)
    binarized = equalized.point(lambda x: 0 if x < 128 else 255)

    return binarized


async def ocr_image(image: Image.Image, language: str) -> str:
    """Preprocess image then run OCR. Returns text or empty string on failure."""
    try:
        preprocessed = preprocess_for_ocr(image)
        return await _run_ocr(preprocessed, language)
    except Exception:
        return ""


async def _run_ocr(image: Image.Image, language: str) -> str:
    """Windows OCR via winocr, run in thread executor to not block event loop."""
    import winocr
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: winocr.recognize_pil_sync(image, language)
    )
    return result.text if result and result.text else ""
```

**Step 4: Run tests to verify they pass**

```
pytest tests/test_capture.py -v
```
Expected: 6 PASSED

**Step 5: Commit**

```bash
git add src/meocosub2/capture.py tests/test_capture.py
git commit -m "feat: screen capture + OCR preprocessing (grayscale → histogram EQ → binarize)"
```

---

## Task 8: Translation Engine

**Files:**
- Create: `src/meocosub2/translator.py`
- Create: `tests/test_translator.py`

---

**Step 1: Write the failing tests**

`tests/test_translator.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from meocosub2.translator import sanitize_output, build_translation_prompt, parse_batch_response
from meocosub2.models import SubtitleLine


def test_sanitize_strips_quotes():
    assert sanitize_output('"Hello"') == "Hello"
    assert sanitize_output("'Hello'") == "Hello"
    assert sanitize_output("\u201cHello\u201d") == "Hello"


def test_sanitize_strips_translation_prefix():
    assert sanitize_output("Translation: Hello") == "Hello"
    assert sanitize_output("翻译: 你好") == "你好"
    assert sanitize_output("output: Hello") == "Hello"


def test_sanitize_stops_at_explanation():
    text = "Hello\nExplanation: this is a note"
    assert sanitize_output(text) == "Hello"


def test_sanitize_passthrough_for_clean_text():
    assert sanitize_output("你好世界") == "你好世界"


def test_build_prompt_includes_line_count():
    prompt = build_translation_prompt(
        source="1. Hello\n2. World", src_lang="en", tgt_lang="zh",
        is_batch=True, count=2
    )
    assert "2" in prompt
    assert "zh" in prompt.lower() or "chinese" in prompt.lower()


def test_build_prompt_includes_context():
    prompt = build_translation_prompt(
        source="1. Hello", src_lang="en", tgt_lang="zh",
        context="Previously: Hi there", is_batch=True, count=1
    )
    assert "Previously" in prompt


def test_parse_batch_response_extracts_lines():
    response = "1. 你好\n2. 世界\n3. 早上好"
    lines = parse_batch_response(response, expected=3)
    assert lines == ["你好", "世界", "早上好"]


def test_parse_batch_response_handles_missing_lines():
    response = "1. 你好\n2. 世界"
    lines = parse_batch_response(response, expected=3)
    assert len(lines) == 3
    assert lines[2] == ""  # Missing line becomes empty string
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_translator.py -v
```
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Create `src/meocosub2/translator.py`**

```python
from __future__ import annotations
import re
import openai
from meocosub2.models import SubtitleLine
from meocosub2.config import AppConfig

_LANG_LABELS = {
    "zh": "Simplified Chinese",
    "zhe": "Simplified Chinese",
    "zht": "Traditional Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "ru": "Russian",
    "ar": "Arabic",
}

_PREFIX_RE = re.compile(
    r'^(translation|translated|output|翻译|译文)\s*[:：]\s*', re.IGNORECASE
)
_NUMBERED_RE = re.compile(r'^\s*\d+[\.\)]\s*')


def sanitize_output(text: str) -> str:
    text = text.strip().strip('"\'`\u201c\u201d\u2018\u2019')
    text = _PREFIX_RE.sub('', text.strip())
    lines = []
    for line in text.split('\n'):
        stripped = line.strip().lower()
        if stripped.startswith(('explanation', 'note', '解释', '说明')):
            break
        lines.append(line.strip())
    return '\n'.join(lines).strip()


def build_translation_prompt(
    source: str,
    src_lang: str,
    tgt_lang: str,
    context: str | None = None,
    is_batch: bool = False,
    count: int = 1,
) -> str:
    target_label = _LANG_LABELS.get(tgt_lang, tgt_lang)
    if is_batch:
        instruction = (
            f"Translate these {count} subtitle lines into {target_label}. "
            f"Output ONLY the translations, numbered 1-{count}. "
            "No explanations. Keep each translation concise."
        )
    else:
        instruction = (
            f"Translate this subtitle line into {target_label}. "
            "Output ONLY the translation, no explanation."
        )
    parts = []
    if context:
        parts.append(context)
    parts.append(instruction)
    parts.append(source)
    return '\n'.join(parts)


def parse_batch_response(response: str, expected: int) -> list[str]:
    """Parse numbered response lines back into a list of translated strings."""
    output = [''] * expected
    for line in response.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        m = re.match(r'^(\d+)[\.\)]\s*(.*)', line)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < expected:
                output[idx] = m.group(2).strip()
    return output


async def translate_lines(
    lines: list[SubtitleLine],
    config: AppConfig,
    progress_callback=None,
) -> list[SubtitleLine]:
    """Batch translate all subtitle lines via Foundry Local."""
    client = openai.AsyncOpenAI(
        base_url=config.foundry_endpoint,
        api_key="unused",
        timeout=config.translation_timeout_s,
    )
    batch_size = config.translation_batch_size
    recent_translated: list[str] = []

    for i in range(0, len(lines), batch_size):
        batch = lines[i : i + batch_size]
        source_block = '\n'.join(f'{j+1}. {line.text}' for j, line in enumerate(batch))
        context_str = '\n'.join(f'- {t}' for t in recent_translated[-3:]) if recent_translated else None
        if context_str:
            context_str = f"Recent context:\n{context_str}"

        prompt = build_translation_prompt(
            source=source_block,
            src_lang=config.source_language,
            tgt_lang=config.target_language,
            context=context_str,
            is_batch=True,
            count=len(batch),
        )

        try:
            response = await client.chat.completions.create(
                model=config.foundry_model or "auto",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=len(batch) * 80,
            )
            raw = response.choices[0].message.content or ""
        except Exception:
            raw = ""

        parsed = parse_batch_response(raw, len(batch))
        for line, translation in zip(batch, parsed):
            line.translated = sanitize_output(translation) or line.text
            recent_translated.append(line.translated)

        if progress_callback:
            progress_callback(min(i + batch_size, len(lines)), len(lines))

    return lines
```

**Step 4: Run tests to verify they pass**

```
pytest tests/test_translator.py -v
```
Expected: 8 PASSED

**Step 5: Commit**

```bash
git add src/meocosub2/translator.py tests/test_translator.py
git commit -m "feat: batch translation engine with sanitization"
```

---

## Task 9: Web Overlay Server

**Files:**
- Create: `src/meocosub2/overlay/__init__.py`
- Create: `src/meocosub2/overlay/server.py`
- Create: `src/meocosub2/overlay/static/index.html`
- Create: `src/meocosub2/overlay/static/overlay.css`
- Create: `src/meocosub2/overlay/static/overlay.js`
- Create: `tests/test_overlay.py`

---

**Step 1: Write the failing tests**

`tests/test_overlay.py`:
```python
import pytest
import asyncio
from fastapi.testclient import TestClient
from meocosub2.config import AppConfig
from meocosub2.overlay.server import OverlayServer


@pytest.fixture
def server():
    return OverlayServer(AppConfig())


def test_index_route_returns_html(server):
    client = TestClient(server.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_config_route_returns_overlay_settings(server):
    client = TestClient(server.app)
    response = client.get("/config")
    assert response.status_code == 200
    data = response.json()
    assert "fontSize" in data
    assert "textColor" in data
    assert data["fontSize"] == 28


@pytest.mark.asyncio
async def test_broadcast_sends_to_connected_clients():
    server = OverlayServer(AppConfig())
    received: list[str] = []

    # Simulate a connected WebSocket by injecting a mock
    class MockWS:
        async def send_text(self, text: str):
            received.append(text)

    server.connections.append(MockWS())
    await server.broadcast("Hello subtitle")
    assert len(received) == 1
    import json
    msg = json.loads(received[0])
    assert msg["type"] == "subtitle"
    assert msg["text"] == "Hello subtitle"


@pytest.mark.asyncio
async def test_broadcast_removes_dead_connections():
    server = OverlayServer(AppConfig())

    class DeadWS:
        async def send_text(self, text: str):
            raise Exception("disconnected")

    server.connections.append(DeadWS())
    await server.broadcast("test")
    assert len(server.connections) == 0
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_overlay.py -v
```
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Create `src/meocosub2/overlay/__init__.py`** (empty)

**Step 4: Create `src/meocosub2/overlay/server.py`**

```python
from __future__ import annotations
import json
from pathlib import Path
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from meocosub2.config import AppConfig

STATIC_DIR = Path(__file__).parent / "static"


class OverlayServer:
    def __init__(self, config: AppConfig):
        self.config = config
        self.connections: list[WebSocket] = []
        self.app = FastAPI()
        self._setup_routes()

    def _setup_routes(self):
        self.app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @self.app.get("/", response_class=HTMLResponse)
        async def index():
            return FileResponse(STATIC_DIR / "index.html")

        @self.app.get("/config")
        async def config():
            return {
                "fontSize": self.config.overlay_font_size,
                "fontFamily": self.config.overlay_font_family,
                "textColor": self.config.overlay_text_color,
                "bgColor": self.config.overlay_bg_color,
                "position": self.config.overlay_position,
            }

        @self.app.websocket("/ws")
        async def ws_endpoint(websocket: WebSocket):
            await websocket.accept()
            self.connections.append(websocket)
            try:
                while True:
                    await websocket.receive_text()
            except Exception:
                if websocket in self.connections:
                    self.connections.remove(websocket)

    async def broadcast(self, subtitle_text: str):
        message = json.dumps({"type": "subtitle", "text": subtitle_text})
        dead = []
        for ws in self.connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.remove(ws)
```

**Step 5: Create `src/meocosub2/overlay/static/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>MeoCoSub2</title>
  <link rel="stylesheet" href="/static/overlay.css">
</head>
<body>
  <div id="subtitle-container">
    <div id="subtitle-text"></div>
  </div>
  <script src="/static/overlay.js"></script>
</body>
</html>
```

**Step 6: Create `src/meocosub2/overlay/static/overlay.css`**

```css
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  background: transparent;
  overflow: hidden;
  user-select: none;
  -webkit-user-select: none;
}

#subtitle-container {
  position: fixed;
  bottom: 10%;
  left: 50%;
  transform: translateX(-50%);
  max-width: 85vw;
  text-align: center;
  pointer-events: none;
}

#subtitle-text {
  display: inline-block;
  padding: 8px 18px;
  border-radius: 4px;
  font-size: var(--font-size, 28px);
  font-family: var(--font-family, 'Segoe UI', sans-serif);
  color: var(--text-color, #fff);
  background: var(--bg-color, rgba(0, 0, 0, 0.75));
  text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.85);
  line-height: 1.4;
  opacity: 1;
  transition: opacity 0.4s ease;
  white-space: pre-wrap;
}
```

**Step 7: Create `src/meocosub2/overlay/static/overlay.js`**

```javascript
const subtitleEl = document.getElementById('subtitle-text');
let ws;
let fadeTimer;

async function loadConfig() {
  try {
    const res = await fetch('/config');
    const cfg = await res.json();
    document.documentElement.style.setProperty('--font-size', cfg.fontSize + 'px');
    document.documentElement.style.setProperty('--font-family', cfg.fontFamily);
    document.documentElement.style.setProperty('--text-color', cfg.textColor);
    document.documentElement.style.setProperty('--bg-color', cfg.bgColor);
    if (cfg.position === 'top') {
      document.getElementById('subtitle-container').style.bottom = 'auto';
      document.getElementById('subtitle-container').style.top = '5%';
    }
  } catch (e) {
    console.warn('Could not load config', e);
  }
}

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'subtitle') showSubtitle(data.text);
    } catch (e) {}
  };
  ws.onclose = () => setTimeout(connect, 2000);
}

function showSubtitle(text) {
  clearTimeout(fadeTimer);
  if (!text || !text.trim()) {
    subtitleEl.style.opacity = '0';
    return;
  }
  subtitleEl.textContent = text;
  subtitleEl.style.opacity = '1';
  fadeTimer = setTimeout(() => { subtitleEl.style.opacity = '0'; }, 8000);
}

loadConfig();
connect();
```

**Step 8: Run tests to verify they pass**

```
pytest tests/test_overlay.py -v
```
Expected: 4 PASSED

**Step 9: Commit**

```bash
git add src/meocosub2/overlay/ tests/test_overlay.py
git commit -m "feat: web overlay server with WebSocket broadcast"
```

---

## Task 10: Sync Loop

**Files:**
- Create: `src/meocosub2/sync.py`
- Create: `tests/test_sync.py`

---

**Step 1: Write the failing tests**

`tests/test_sync.py`:
```python
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from meocosub2.sync import run_sync_loop
from meocosub2.models import SubtitleLine, SubtitlePair, MatchResult
from meocosub2.config import AppConfig


def make_pair() -> SubtitlePair:
    lines = [
        SubtitleLine(index=0, start_ms=0, end_ms=3000, text="Hello", translated="你好"),
        SubtitleLine(index=1, start_ms=3000, end_ms=6000, text="World", translated="世界"),
    ]
    return SubtitlePair(source_lines=lines, target_lines=[])


@pytest.mark.asyncio
async def test_sync_loop_broadcasts_match(mocker):
    pair = make_pair()
    config = AppConfig(capture_interval_ms=50)  # Fast for tests
    broadcasts = []

    mocker.patch("meocosub2.sync.capture_region", return_value=MagicMock())
    mocker.patch("meocosub2.sync.ocr_image", new=AsyncMock(return_value="Hello"))

    async def stop_after_one(text):
        broadcasts.append(text)
        raise asyncio.CancelledError()

    await asyncio.wait_for(
        run_sync_loop(pair, config, broadcast=stop_after_one),
        timeout=2.0,
    )
    assert broadcasts == ["你好"]


@pytest.mark.asyncio
async def test_sync_loop_skips_no_match(mocker):
    pair = make_pair()
    config = AppConfig(capture_interval_ms=50)
    broadcasts = []

    mocker.patch("meocosub2.sync.capture_region", return_value=MagicMock())
    mocker.patch(
        "meocosub2.sync.ocr_image",
        new=AsyncMock(side_effect=["completely unrelated noise", asyncio.CancelledError()])
    )

    with pytest.raises((asyncio.CancelledError, asyncio.TimeoutError)):
        await asyncio.wait_for(
            run_sync_loop(pair, config, broadcast=AsyncMock(side_effect=lambda t: broadcasts.append(t))),
            timeout=1.0,
        )

    assert len(broadcasts) == 0


@pytest.mark.asyncio
async def test_sync_loop_does_not_repeat_same_line(mocker):
    pair = make_pair()
    config = AppConfig(capture_interval_ms=50)
    broadcasts = []
    call_count = 0

    async def fake_ocr(image, lang):
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            raise asyncio.CancelledError()
        return "Hello"  # Same line every call

    mocker.patch("meocosub2.sync.capture_region", return_value=MagicMock())
    mocker.patch("meocosub2.sync.ocr_image", new=fake_ocr)

    with pytest.raises((asyncio.CancelledError, asyncio.TimeoutError)):
        await asyncio.wait_for(
            run_sync_loop(pair, config, broadcast=AsyncMock(side_effect=lambda t: broadcasts.append(t))),
            timeout=2.0,
        )
    assert len(broadcasts) == 1  # Only broadcast once despite multiple matching frames
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_sync.py -v
```
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Create `src/meocosub2/sync.py`**

```python
from __future__ import annotations
import asyncio
import time
from typing import Callable, Awaitable
from meocosub2.models import SubtitlePair
from meocosub2.config import AppConfig
from meocosub2.matcher import SubtitleMatcher
from meocosub2.capture import capture_region, ocr_image


async def run_sync_loop(
    pair: SubtitlePair,
    config: AppConfig,
    broadcast: Callable[[str], Awaitable[None]],
) -> None:
    """Main sync loop: capture → OCR → fuzzy match → broadcast target subtitle."""
    matcher = SubtitleMatcher(pair.source_lines, config.fuzzy_threshold)
    last_displayed_index = -1
    region = tuple(config.capture_region) if config.capture_region else (0, 800, 1920, 200)
    interval_s = config.capture_interval_ms / 1000.0

    while True:
        loop_start = time.monotonic()

        try:
            image = capture_region(region)
            ocr_text = await ocr_image(image, config.ocr_language)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(interval_s)
            continue

        result = matcher.match(ocr_text)
        if result is not None and result.line_index != last_displayed_index:
            await broadcast(result.target_text)
            last_displayed_index = result.line_index

        elapsed = time.monotonic() - loop_start
        await asyncio.sleep(max(0, interval_s - elapsed))
```

**Step 4: Run tests to verify they pass**

```
pytest tests/test_sync.py -v
```
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add src/meocosub2/sync.py tests/test_sync.py
git commit -m "feat: sync loop (capture → OCR → match → broadcast)"
```

---

## Task 11: Wire Up Full CLI Commands

**Files:**
- Modify: `src/meocosub2/cli.py`
- Modify: `tests/test_cli.py`

---

**Step 1: Write the new CLI integration tests**

Add to `tests/test_cli.py`:
```python
import respx
import httpx

SEARCH_RESPONSE = {
    "data": [{
        "id": "1",
        "type": "subtitle",
        "attributes": {
            "language": "en",
            "download_count": 100,
            "feature_details": {
                "feature_type": "Movie", "title": "Inception",
                "year": 2010, "imdb_id": None,
                "season_number": None, "episode_number": None,
            },
            "files": [{"file_id": 42, "file_name": "Inception.en.srt"}],
        },
    }],
    "total_count": 1,
}


@respx.mock
def test_search_command_shows_results(mocker):
    mocker.patch("meocosub2.cli._get_config", return_value=AppConfig(opensubtitles_api_key="key"))
    respx.get("https://api.opensubtitles.com/api/v1/subtitles").mock(
        return_value=httpx.Response(200, json=SEARCH_RESPONSE)
    )
    result = runner.invoke(app, ["search", "Inception"])
    assert result.exit_code == 0
    assert "Inception" in result.output
```

**Step 2: Run test to verify it fails**

```
pytest tests/test_cli.py::test_search_command_shows_results -v
```
Expected: FAIL

**Step 3: Replace `src/meocosub2/cli.py` with full implementation**

```python
from __future__ import annotations
import asyncio
import sys
import webbrowser
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table
import uvicorn

from meocosub2 import __version__
from meocosub2.config import AppConfig, load_config, save_config
from meocosub2.opensubtitles.client import OpenSubtitlesClient
from meocosub2.subtitles import load_subtitle_file, align_subtitles
from meocosub2.models import SubtitlePair

app = typer.Typer(help="MeoCoSub2 — fetch, translate, and sync subtitles for any video.")
console = Console()


def _get_config() -> AppConfig:
    return load_config()


def _version_callback(value: bool):
    if value:
        typer.echo(f"meocosub2 {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True
    ),
):
    pass


@app.command()
def search(
    title: str = typer.Argument(..., help="Movie or show title"),
    source_lang: str = typer.Option("", "--source", "-s", help="Source language code (e.g. en)"),
    target_lang: str = typer.Option("", "--target", "-t", help="Target language code (e.g. zh)"),
):
    """Search OpenSubtitles for subtitle files."""
    cfg = _get_config()
    src = source_lang or cfg.source_language
    tgt = target_lang or cfg.target_language

    if not cfg.opensubtitles_api_key:
        console.print("[red]Error:[/red] OpenSubtitles API key not set. Add it to config.toml.")
        raise typer.Exit(1)

    client = OpenSubtitlesClient(api_key=cfg.opensubtitles_api_key)
    results = asyncio.run(client.search(title, languages=f"{src},{tgt}"))

    if not results:
        console.print(f"[yellow]No subtitles found for:[/yellow] {title}")
        raise typer.Exit(0)

    table = Table(title=f"Results for '{title}'")
    table.add_column("#", style="dim")
    table.add_column("Title")
    table.add_column("Lang")
    table.add_column("Downloads", justify="right")
    table.add_column("file_id", style="dim")

    for i, r in enumerate(results[:20]):
        table.add_row(str(i + 1), r.display_label(), r.language, str(r.download_count), str(r.file_id))

    console.print(table)


@app.command()
def run(
    title: str = typer.Argument(..., help="Movie or show title"),
    source_lang: str = typer.Option("", "--source", "-s"),
    target_lang: str = typer.Option("", "--target", "-t"),
):
    """Full flow: search → download → translate if needed → start overlay."""
    cfg = _get_config()
    src = source_lang or cfg.source_language
    tgt = target_lang or cfg.target_language

    if not cfg.opensubtitles_api_key:
        console.print("[red]Error:[/red] OpenSubtitles API key not configured.")
        raise typer.Exit(1)

    asyncio.run(_run_flow(title, src, tgt, cfg))


async def _run_flow(title: str, src: str, tgt: str, cfg: AppConfig):
    from meocosub2.translator import translate_lines
    from meocosub2.overlay.server import OverlayServer
    from meocosub2.sync import run_sync_loop

    client = OpenSubtitlesClient(api_key=cfg.opensubtitles_api_key)

    # Step 1: Search
    console.print(f"Searching OpenSubtitles for '[bold]{title}[/bold]'...")
    results = await client.search(title, languages=f"{src},{tgt}")

    src_results = [r for r in results if r.language == src]
    tgt_results = [r for r in results if r.language == tgt]

    if not src_results:
        console.print(f"[red]No {src} subtitles found.[/red]")
        return

    # Pick best result (most downloaded)
    src_result = sorted(src_results, key=lambda r: r.download_count, reverse=True)[0]
    tgt_result = sorted(tgt_results, key=lambda r: r.download_count, reverse=True)[0] if tgt_results else None

    console.print(f"Selected: [green]{src_result.display_label()}[/green]")

    # Step 2: Download
    cache_dir = Path.home() / ".cache" / "meocosub2"
    cache_dir.mkdir(parents=True, exist_ok=True)

    src_path = await _download(client, src_result.file_id, cache_dir)
    tgt_path = await _download(client, tgt_result.file_id, cache_dir) if tgt_result else None

    # Step 3: Parse subtitles
    source_lines = load_subtitle_file(src_path)
    target_lines = load_subtitle_file(tgt_path) if tgt_path else []

    # Step 4: Translate if needed
    if not target_lines:
        console.print(f"No {tgt} subtitles found. Translating with Foundry Local...")
        source_lines = await translate_lines(
            source_lines, cfg,
            progress_callback=lambda done, total: console.print(f"  {done}/{total}")
        )
        pair = align_subtitles(source_lines, [])
    else:
        # Merge translated text into source lines for matcher
        for src_line, tgt_line in zip(source_lines, target_lines):
            src_line.translated = tgt_line.text
        pair = align_subtitles(source_lines, target_lines)

    # Step 5: Start overlay
    overlay = OverlayServer(cfg)
    config = uvicorn.Config(overlay.app, host="127.0.0.1", port=cfg.overlay_port, log_level="error")
    server = uvicorn.Server(config)

    overlay_url = f"http://127.0.0.1:{cfg.overlay_port}"
    console.print(f"Overlay running at [link={overlay_url}]{overlay_url}[/link]")
    webbrowser.open(overlay_url)

    console.print("\nStart your video, then press [bold]Enter[/bold]...")
    input()

    # Step 6: Sync loop (run alongside overlay server)
    async def serve():
        await server.serve()

    async def sync():
        await run_sync_loop(pair, cfg, broadcast=overlay.broadcast)

    console.print("Syncing subtitles. Press [bold]Ctrl+C[/bold] to stop.")
    await asyncio.gather(serve(), sync())


async def _download(client: OpenSubtitlesClient, file_id: int, dest_dir: Path) -> Path:
    dest = dest_dir / f"{file_id}.srt"
    if dest.exists():
        return dest
    link, _ = await client.get_download_link(file_id)
    import httpx
    async with httpx.AsyncClient() as http:
        response = await http.get(link)
        response.raise_for_status()
        dest.write_bytes(response.content)
    return dest
```

**Step 4: Run the full test suite**

```
pytest -v
```
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/meocosub2/cli.py tests/test_cli.py
git commit -m "feat: wire up full run/search CLI commands"
```

---

## Task 12: Logging and Error Handling Polish

**Files:**
- Create: `src/meocosub2/errors.py`
- Modify: `src/meocosub2/cli.py` (add logging setup)

---

**Step 1: Create `src/meocosub2/errors.py`**

```python
class MeoCoSubError(Exception):
    """Base exception for the app."""

class OpenSubtitlesError(MeoCoSubError):
    """OpenSubtitles API error."""

class TranslationError(MeoCoSubError):
    """Translation failure."""

class CaptureError(MeoCoSubError):
    """Screen capture failure."""
```

**Step 2: Add logging setup to `src/meocosub2/cli.py`**

Add this function and call it from `main()`:

```python
def _setup_logging():
    import logging
    import os
    from logging.handlers import TimedRotatingFileHandler

    log_dir = Path(os.environ.get("APPDATA", Path.home())) / "meocosub2" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    handler = TimedRotatingFileHandler(
        log_dir / "meocosub2.log",
        when="D", backupCount=7, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    logging.basicConfig(handlers=[handler], level=logging.INFO)
```

**Step 3: Run all tests**

```
pytest -v
```
Expected: All PASS

**Step 4: Commit**

```bash
git add src/meocosub2/errors.py src/meocosub2/cli.py
git commit -m "feat: structured error types and file logging"
```

---

## Task 13: README and `config.example.toml`

**Step 1: Create `config.example.toml`**

```toml
[opensubtitles]
api_key = "YOUR_API_KEY_HERE"
# Get your key at: https://www.opensubtitles.com/consumers

[languages]
source = "en"
target = "zht"   # Traditional Chinese

[capture]
region = []       # Empty = prompts you to enter coordinates
interval_ms = 1500
ocr_language = "en"

[matching]
fuzzy_threshold = 65
window_size = 30

[translation]
endpoint = "http://127.0.0.1:5273/v1"
model = ""
timeout_s = 30
batch_size = 5

[overlay]
port = 8765
font_size = 28
font_family = "Segoe UI"
text_color = "#FFFFFF"
bg_color = "rgba(0,0,0,0.75)"
position = "bottom"
```

**Step 2: Commit**

```bash
git add config.example.toml README.md
git commit -m "docs: add example config and README"
```

---

## Final Verification

Run the complete test suite:

```
pytest -v --tb=short
```

Expected: All tests pass across all modules:
- `test_models.py` — 3 tests
- `test_config.py` — 4 tests
- `test_cli.py` — 4+ tests
- `test_subtitles.py` — 4 tests
- `test_opensubtitles.py` — 4 tests
- `test_matcher.py` — 9 tests
- `test_capture.py` — 3 tests
- `test_translator.py` — 8 tests
- `test_overlay.py` — 4 tests
- `test_sync.py` — 3 tests

Verify the CLI entry point is registered:

```
pip install -e .
meocosub2 --help
```

Expected: Help text showing all commands (search, run, download, translate, start).
