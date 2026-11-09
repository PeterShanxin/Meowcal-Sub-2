"""Benchmark Sub 2 OCR policies on ordered, locally labelled subtitle frames.

Windows only. Inputs are PNG frames/ plus truth.csv, or cues.csv and labels.csv.
Frame rows must follow the sorted PNG sequence. Timings include preprocessing,
transport and recognition, not screen capture or PNG loading. Text matching is
measured without duplicate suppression or semantic recovery; native playback is
an independent acceptance gate. JSONL outputs contain private subtitle text.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import ctypes
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PIL import Image
from rapidfuzz.distance import LCSseq, Levenshtein

from meocosub2 import capture, native_ocr
from meocosub2.matcher import SubtitleMatcher
from meocosub2.models import SubtitleLine
from meocosub2.textnorm import clean_cjk_text, to_simplified


def norm(text: str) -> str:
    return "".join(c for c in SubtitleMatcher.normalize_text(to_simplified(text)) if c.isalnum())


def truth(root: Path) -> list[dict]:
    if (root / "truth.csv").exists():
        rows = list(csv.DictReader((root / "truth.csv").open(encoding="utf-8-sig")))
    else:
        labels = {
            r["cue_id"]: r["truth"]
            for r in csv.DictReader((root / "labels.csv").open(encoding="utf-8-sig"))
        }
        rows = list(csv.DictReader((root / "cues.csv").open(encoding="utf-8-sig")))
        for r in rows:
            if r["cue_id"] and r["cue_id"] not in labels:
                raise ValueError("Unlabelled real cue")
            r["truth"] = labels[r["cue_id"]] if r["cue_id"] else ""
    for r in rows:
        r["frame"] = int(r["frame"])
        r["seconds"] = float(r["seconds"])
        if r["truth"] == "IGNORE":
            r["phase"] = "ignore"
            r["truth"] = ""
    paths = sorted((root / "frames").glob("*.png"))
    if len(paths) != len(rows) or not rows:
        raise ValueError("Frame/label count mismatch or empty corpus")
    if [r["frame"] for r in rows] != list(range(rows[0]["frame"], rows[0]["frame"] + len(rows))):
        raise ValueError("Frame labels must be consecutive and ordered")
    for r, path in zip(rows, paths, strict=True):
        r["imageFile"] = path.name
    return rows


def frame_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((root / "frames").glob("*.png")):
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def cpu(process) -> float:
    if not process:
        return 0.0
    values = [wintypes.FILETIME() for _ in range(4)]
    if not ctypes.windll.kernel32.GetProcessTimes(
        wintypes.HANDLE(int(process._handle)), *[ctypes.byref(v) for v in values]
    ):
        return 0.0
    return sum((v.dwHighDateTime << 32) + v.dwLowDateTime for v in values[2:]) / 10_000_000


def owned_cpu(handles: dict) -> float:
    client = native_ocr._client
    if client and client._process:
        handles[client._process.pid] = client._process
    return sum(cpu(process) for process in handles.values())


async def read(
    image: Image.Image, language: str, policy: str, threads: int, errors: list[str] | None = None
) -> str:
    report_error = errors.append if errors is not None else None
    if policy == "windows":
        return await capture.ocr_image(image, language, on_error=report_error)
    if policy == "ppocr-height" and threads == 2:
        return await capture.ocr_image(image, language, engine="ppOcrV6", on_error=report_error)
    await native_ocr.initialize_ppocr(threads)
    if policy == "ppocr-three":
        passes = [image, capture.preprocess_for_ocr(image)]
        if not language.startswith(("zh", "ja")):
            passes.reverse()
        passes.append(capture.preprocess_white_text_for_ocr(image))
        best = ""
        score = (0, 0)
        whole = []
        for i, candidate in enumerate(passes):
            text = await native_ocr.recognize(
                candidate, None, 1, engine="ppOcrV6", max_threads=threads
            )
            letters = "".join(c for c in text.casefold() if c.isalpha())
            if i == 2 and not any(LCSseq.similarity(p, letters) >= 0.8 * len(p) for p in whole):
                continue
            if i < 2 and len(letters) >= 3:
                whole.append(letters)
            quality = capture._ocr_score(text)
            if quality > score:
                best = text
                score = quality
        return clean_cjk_text(best)
    if policy == "ppocr-raw":
        return clean_cjk_text(
            await native_ocr.recognize(image, None, 1, engine="ppOcrV6", max_threads=threads)
        )
    lines = await native_ocr.recognize_ppocr_lines(image, 1, max_threads=threads)
    tallest = max((line.height for line in lines), default=0)
    return clean_cjk_text("\n".join(line.text for line in lines if line.height >= 0.6 * tallest))


def summarize(
    rows: list[dict], all_truth: list[dict], seconds: float, core_cpu: float, client_cpu: float
) -> dict:
    stable = [r for r in rows if r["phase"] == "stable" and r["truth"]]
    blanks = [
        r for r in rows if r["phase"] == "blank" or (r["phase"] == "stable" and not r["truth"])
    ]
    comparisons = changes = 0
    previous = None
    groups = defaultdict(list)
    for r in rows:
        if r["phase"] == "stable" and r["truth"]:
            groups[r["cue_id"]].append(r)
            if previous and previous["cue_id"] == r["cue_id"]:
                comparisons += 1
                changes += norm(previous["output"]) != norm(r["output"])
            previous = r
        else:
            previous = None
    cue_ids = []
    for r in all_truth:
        if r["cue_id"] and r["truth"] and r["phase"] != "ignore" and r["cue_id"] not in cue_ids:
            cue_ids.append(r["cue_id"])
    subtitles = []
    for i, cue in enumerate(cue_ids):
        selected = [r for r in all_truth if r["cue_id"] == cue]
        subtitles.append(
            SubtitleLine(
                i,
                round(min(r["seconds"] for r in selected) * 1000),
                round(max(r["seconds"] for r in selected) * 1000 + 100),
                selected[0]["truth"],
            )
        )
    matcher = SubtitleMatcher(subtitles)
    correct = wrong = miss = blank_matches = 0
    matched_cues = set()
    for r in rows:
        matcher.clear_cue()
        hit = matcher.match(r["output"])
        if r["phase"] == "stable" and r["truth"]:
            if hit is None:
                miss += 1
            elif norm(subtitles[hit.line_index].text) == norm(r["truth"]):
                correct += 1
                matched_cues.add(r["cue_id"])
            else:
                wrong += 1
        elif r in blanks and hit:
            blank_matches += 1
    latency = sorted(r["ms"] for r in rows)
    reference = sum(len(norm(r["truth"])) for r in stable)
    return {
        "frames": len(rows),
        "stableFrames": len(stable),
        "blankFrames": len(blanks),
        "cues": len(groups),
        "CER": sum(Levenshtein.distance(norm(r["truth"]), norm(r["output"])) for r in stable)
        / reference
        if reference
        else None,
        "stableExact": sum(norm(r["truth"]) == norm(r["output"]) for r in stable) / len(stable)
        if stable
        else None,
        "changeRate": changes / comparisons if comparisons else None,
        "cuesWithCorrectTextMatch": len(matched_cues),
        "textMatchCorrect": correct,
        "textMatchWrong": wrong,
        "textMatchMiss": miss,
        "blankTextMatches": blank_matches,
        "blankOutputRate": sum(bool(r["output"]) for r in blanks) / len(blanks) if blanks else None,
        "p50Ms": statistics.median(latency),
        "p95Ms": latency[math.ceil(len(latency) * 0.95) - 1],
        "maxMs": max(latency),
        "over250Rate": sum(r["ms"] > 250 for r in rows) / len(rows),
        "failures": sum(bool(r["error"]) for r in rows),
        "coreCpuMsPerFrame": core_cpu * 1000 / len(rows),
        "clientCpuMsPerFrame": client_cpu * 1000 / len(rows),
        "wallSeconds": seconds,
    }


async def main(args: argparse.Namespace) -> None:
    args.output.mkdir(parents=True, exist_ok=True)
    assert (
        Path(native_ocr.__file__).resolve()
        == Path(__file__).resolve().parents[1] / "src/meocosub2/native_ocr.py"
    )
    os.environ["MEOWCAL_CORE_EXE"] = str(args.core.resolve())
    os.environ["MEOWCAL_CORE_PROFILE"] = "development"
    os.environ["MEOWCAL_CORE_STORAGE_ROOT"] = str((args.output / "storage").resolve())
    checkout = Path(__file__).resolve().parents[1]
    metadata = json.loads(args.core.with_name("meowcal-core.json").read_text("utf-8"))
    executable_hash = hashlib.sha256(args.core.read_bytes()).hexdigest()
    if executable_hash != metadata["executableSha256"]:
        raise ValueError("Core executable differs from its package metadata")
    metadata = {
        "coreVersion": metadata["coreVersion"],
        "coreArchitecture": metadata["architecture"],
        "coreSha256": executable_hash,
        "revision": subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True, timeout=10
        ).strip(),
        "python": sys.version,
        "hostArchitecture": platform.machine(),
        "sourceHashes": {
            name: hashlib.sha256((checkout / "src/meocosub2" / name).read_bytes()).hexdigest()
            for name in ("capture.py", "native_ocr.py", "core_protocol.py", "matcher.py")
        },
        "corpora": {
            corpus.name: {
                "framesSha256": frame_hash(corpus),
                "labels": {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(corpus.glob("*.csv"))
                },
            }
            for corpus in args.corpus
        },
    }
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2), "utf-8")
    reports = []
    for corpus in args.corpus:
        source = truth(corpus)
        selected = source[:: args.stride]
        language = args.language
        for policy in args.policies:
            native_ocr.shutdown()
            rows = []
            handles = {}

            first = Image.open(corpus / "frames" / selected[0]["imageFile"]).convert("RGB")
            cold = time.perf_counter()
            await read(first, language, policy, args.threads)
            cold_ms = (time.perf_counter() - cold) * 1000
            for _ in range(2):
                await read(first, language, policy, args.threads)
            before = owned_cpu(handles)
            client_start = time.process_time()
            started = time.perf_counter()
            try:
                for record in selected:
                    image = Image.open(corpus / "frames" / record["imageFile"]).convert("RGB")
                    t = time.perf_counter()
                    errors = []
                    text = ""
                    try:
                        text = await read(image, language, policy, args.threads, errors)
                    except Exception as exc:
                        errors.append(type(exc).__name__)
                    elapsed = (time.perf_counter() - t) * 1000
                    owned_cpu(handles)
                    rows.append(
                        {**record, "output": text, "ms": elapsed, "error": ";".join(errors)}
                    )
                summary = summarize(
                    rows,
                    source,
                    time.perf_counter() - started,
                    owned_cpu(handles) - before,
                    time.process_time() - client_start,
                )
                summary.update(
                    policy=policy,
                    corpus=corpus.name,
                    maxThreads=args.threads,
                    coldMs=cold_ms,
                    logicalCpus=os.cpu_count(),
                    platform=platform.machine(),
                    stride=args.stride,
                    language=language,
                )
                name = f"{corpus.name}-{policy}-t{args.threads}"
                (args.output / (name + ".jsonl")).write_text(
                    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8"
                )
                (args.output / (name + ".json")).write_text(json.dumps(summary, indent=2), "utf-8")
                reports.append(summary)
                print(json.dumps(summary), flush=True)
            finally:
                native_ocr.shutdown()
    (args.output / "summary.json").write_text(json.dumps(reports, indent=2), "utf-8")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", type=Path, action="append", required=True)
    p.add_argument("--core", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--language", default="zh-CN")
    p.add_argument(
        "--policies",
        nargs="+",
        choices=["windows", "ppocr-three", "ppocr-raw", "ppocr-height"],
        default=["windows", "ppocr-three", "ppocr-raw", "ppocr-height"],
    )
    p.add_argument("--threads", type=int, choices=[1, 2, 3, 4], default=2)
    p.add_argument("--stride", type=int, default=1)
    args = p.parse_args()
    if os.name != "nt":
        p.error("Native Core OCR benchmarking requires Windows")
    if args.stride < 1:
        p.error("Stride must be positive")
    asyncio.run(main(args))
