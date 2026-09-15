"""Prepared subtitle files and immutable corrected copies used by the next sync."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from meocosub2.bilingual import split_bilingual
from meocosub2.models import PreparedRuntime, PreparedSession
from meocosub2.subtitles import align_subtitles, load_subtitle_file

if TYPE_CHECKING:
    from meocosub2.overlay.controller import GuiController

MAX_BYTES = 4 * 1024 * 1024


class EditFile(BaseModel):
    key: str
    revision: str
    format: Literal["srt", "vtt"]
    content: str = Field(max_length=MAX_BYTES)


class SaveEdits(BaseModel):
    sessionId: str
    files: list[EditFile] = Field(min_length=1, max_length=4)


def track_paths(session: PreparedSession, runtime: PreparedRuntime) -> dict[str, Path]:
    paths = {f"source:{c.result_id}": Path(c.path) for c in runtime.source_candidates}
    if session.target_path:
        paths["target"] = Path(session.target_path)
    return paths


def read_track(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Subtitle editing supports files up to 4 MiB.")
    return raw


def revision(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def editor_files(session: PreparedSession, runtime: PreparedRuntime) -> dict[str, object]:
    files = []
    for key, path in track_paths(session, runtime).items():
        item = {
            "key": key,
            "filename": path.name,
            "role": "target" if key == "target" else "source",
        }
        try:
            raw = read_track(path)
            item["revision"] = revision(raw)
            if path.suffix.lower() not in {".srt", ".vtt"}:
                raise ValueError(
                    "Editing supports SRT and WebVTT files. This track remains usable for playback."
                )
            item["content"] = raw.decode("utf-8")
        except UnicodeError:
            item["error"] = "This file is not UTF-8. Import a UTF-8 SRT or WebVTT copy to edit it."
        except (ValueError, OSError) as exc:
            item["error"] = str(exc)
        files.append(item)
    return {"sessionId": session.session_id, "files": files}


def validate_content(content: str, format: str) -> bytes:
    """Reject broken exports before the playback parser can discard their bad cues."""
    try:
        raw = content.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Incomplete Unicode characters cannot be saved as UTF-8.") from exc
    if len(raw) > MAX_BYTES or "\0" in content or "\r" in content:
        raise ValueError("Use an LF-delimited subtitle without NUL characters, up to 4 MiB.")
    blocks = content.removeprefix("\ufeff").strip("\n").split("\n\n")
    if format == "vtt":
        if not re.fullmatch(r"WEBVTT(?:[ \t][^\n]*)?", blocks[0]) or "-->" in blocks[0]:
            raise ValueError("Invalid WebVTT header.")
        blocks = blocks[1:]
    count = 0
    for block in blocks:
        lines = block.split("\n")
        if format == "vtt" and re.match(r"^NOTE(?:[ \t]|$)", lines[0]):
            if "-->" in block:
                raise ValueError("Invalid WebVTT NOTE block.")
            continue
        offset = 1 if format == "srt" or "-->" not in lines[0] else 0
        if format == "srt" and not re.fullmatch(r"\d+", lines[0]):
            raise ValueError("Invalid SRT sequence.")
        if len(lines) <= offset + 1 or not "\n".join(lines[offset + 1 :]).strip():
            raise ValueError("Each subtitle needs a timing line and nonempty text.")
        stamp = r"(\d{2,}):([0-5]\d):([0-5]\d)[,.](\d{3})"
        timing = re.fullmatch(rf"{stamp} --> {stamp}([ \t]+[^\n]*)?", lines[offset])
        if not timing or (format == "srt" and timing[9]):
            raise ValueError("Invalid subtitle timing line.")
        values = [int(value) for value in timing.groups()[:8]]
        start = ((values[0] * 60 + values[1]) * 60 + values[2]) * 1000 + values[3]
        end = ((values[4] * 60 + values[5]) * 60 + values[6]) * 1000 + values[7]
        if not 0 <= start < end <= 9007199254740991:
            raise ValueError("Subtitle intervals must have 0 <= start < end in safe milliseconds.")
        count += 1
    if not count:
        raise ValueError("A playback track needs at least one subtitle.")
    return raw


def rebuild_tracks(
    session: PreparedSession, runtime: PreparedRuntime, request: SaveEdits, directory: Path
) -> tuple[PreparedSession, PreparedRuntime]:
    paths = track_paths(session, runtime)
    edits: dict[str, tuple[Path, bytes]] = {}
    for edit in request.files:
        if edit.key not in paths or edit.key in edits:
            raise ValueError("Select each prepared track at most once.")
        if revision(read_track(paths[edit.key])) != edit.revision:
            raise ValueError("The subtitle changed on disk. Reopen the editor before saving.")
        raw = validate_content(edit.content, edit.format)
        stem = re.sub(r"\.corrected-[0-9a-f]{8}$", "", paths[edit.key].stem)
        name = f"{stem[:160]}.corrected-{uuid4().hex[:8]}.{edit.format}"
        edits[edit.key] = (directory / name, raw)

    created: list[Path] = []
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for key, (path, raw) in edits.items():
            with path.open("xb") as stream:
                created.append(path)
                stream.write(raw)
            paths[key] = path
        target = load_subtitle_file(paths["target"]) if "target" in paths else []
        candidates = []
        split_count = 0
        for candidate in runtime.source_candidates:
            key = f"source:{candidate.result_id}"
            source = load_subtitle_file(paths[key])
            bilingual = split_bilingual(source, session.source_language, session.target_language)
            split_count += bilingual.split_cues
            candidates.append(
                replace(
                    candidate,
                    path=str(paths[key]),
                    file_name=paths[key].name,
                    pair=align_subtitles(source, target),
                )
            )
        updated_runtime = replace(runtime, source_candidates=candidates, target_lines=target)
        source_path = (
            str(paths[f"source:{candidates[0].result_id}"])
            if session.source_path and candidates
            else None
        )
        updated = replace(
            session,
            session_id=uuid4().hex[:8],
            source_path=source_path,
            source_file_name=Path(source_path).name if source_path else session.source_file_name,
            target_path=str(paths["target"]) if "target" in paths else None,
            target_file_name=paths["target"].name
            if "target" in paths
            else session.target_file_name,
            source_line_count=sum(len(c.pair.source_lines) for c in candidates),
            target_line_count=len(target) if target else split_count,
            used_translation=not target and not split_count
            if candidates
            else session.used_translation,
            translated_line_count=sum(
                bool(c.pair.presentation.answer(line))
                for c in candidates
                for line in c.pair.source_lines
            ),
            target_alignment=[],
        )
        if session.target_match_mode == "source_own_translation" and source_path:
            updated.target_file_name = Path(source_path).name
        return updated, updated_runtime
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def editor_router(controller: GuiController) -> APIRouter:
    router = APIRouter(prefix="/api/subtitle-editor")

    @router.get("/{session_id}")
    async def read(session_id: str) -> dict[str, object]:
        try:
            return controller.read_subtitle_editor(session_id)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/save")
    async def save(body: SaveEdits) -> dict[str, object]:
        try:
            session = await controller.save_subtitle_edits(body)
            return {"session": asdict(session), "state": controller.state_snapshot()}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    return router
