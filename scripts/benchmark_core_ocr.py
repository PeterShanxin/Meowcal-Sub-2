"""Compare complete Sub 2 OCR policies on synthetic frames in isolated processes.

Requires the baseline checkout's winocr dependency and installed Windows languages.
Capture and UI scheduling are outside this benchmark; preprocessing, all OCR passes,
transport, and result selection are timed. No private screen content is collected.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def summarize(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {
        "count": len(samples),
        "p50Ms": statistics.median(samples),
        "p95Ms": ordered[math.ceil(len(samples) * 0.95) - 1],
        "maxMs": max(samples),
        "over250Rate": sum(value > 250 for value in samples) / len(samples),
    }


def compare(baseline: dict, candidate: dict) -> dict:
    """Absolute budgets protect short reads; relative budgets scale with slow ones."""
    limits = {
        "p50Ms": baseline["p50Ms"] + max(10, baseline["p50Ms"] * 0.15),
        "p95Ms": baseline["p95Ms"] + max(15, baseline["p95Ms"] * 0.20),
        "over250Rate": baseline["over250Rate"] + 0.01,
    }
    return {
        "limits": limits,
        "passed": all(candidate[key] <= limit for key, limit in limits.items()),
    }


def fixtures(directory: Path) -> list[dict]:
    directory.mkdir(parents=True, exist_ok=True)
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    cases = [
        (
            "latin",
            960,
            160,
            "en-US",
            "Meowcal Core reads this subtitle",
            "arial.ttf",
            "white",
            "black",
        ),
        (
            "large",
            1920,
            320,
            "en-US",
            "Meowcal Core reads this subtitle",
            "arial.ttf",
            "white",
            "black",
        ),
        (
            "color",
            960,
            160,
            "en-US",
            "Meowcal Core reads this subtitle",
            "arial.ttf",
            "yellow",
            "navy",
        ),
        ("chinese", 960, 160, "zh-Hans", "今天我们一起看电影", "msyh.ttc", "white", "black"),
        ("blank", 960, 160, "en-US", "", "arial.ttf", "white", "black"),
    ]
    result = []
    for name, width, height, language, text, font, foreground, background in cases:
        image = Image.new("RGB", (width, height), background)
        if text:
            ImageDraw.Draw(image).text(
                (30, height // 3),
                text,
                fill=foreground,
                font=ImageFont.truetype(str(fonts / font), 48),
            )
        path = directory / f"{name}.png"
        image.save(path)
        pixels = image.convert("RGBA").tobytes("raw", "BGRA")
        (directory / f"{name}.bgra").write_bytes(pixels)
        result.append(
            {
                "name": name,
                "width": width,
                "height": height,
                "language": language,
                "path": str(path.resolve()),
                "bgraSha256": hashlib.sha256(pixels).hexdigest(),
            }
        )
    (directory / "fixtures.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


async def worker(args: argparse.Namespace) -> None:
    from meocosub2 import capture

    actual = Path(capture.__file__).resolve()
    if actual != args.checkout.resolve() / "src/meocosub2/capture.py":
        raise RuntimeError(f"Wrong package imported: {actual}")
    image = Image.open(args.image).convert("RGB")
    samples, answers, warmup_samples, warmup_answers = [], [], [], []
    first_ms = 0.0
    cpu_start = time.process_time()
    try:
        for index in range(args.warmup + args.runs):
            start = time.perf_counter()
            answer = await capture.ocr_image(image, args.language)
            elapsed = (time.perf_counter() - start) * 1000
            if index == 0:
                first_ms = elapsed
            if index >= args.warmup:
                samples.append(elapsed)
                answers.append(answer)
            else:
                warmup_samples.append(elapsed)
                warmup_answers.append(answer)
            if args.interval_ms:
                await asyncio.sleep(max(0, (args.interval_ms - elapsed) / 1000))
        record = {
            "firstCallMs": first_ms,
            "samplesMs": samples,
            "answers": answers,
            "warmupSamplesMs": warmup_samples,
            "warmupAnswers": warmup_answers,
            "clientCpuSeconds": time.process_time() - cpu_start,
            **summarize(samples),
        }
    finally:
        if args.variant == "candidate":
            from meocosub2 import native_ocr

            owned = native_ocr._client._process if native_ocr._client else None
            native_ocr.shutdown()
            if owned is not None and owned.poll() is None:
                raise RuntimeError("Owned Core survived shutdown")
    print(json.dumps(record, ensure_ascii=True))


def revision(checkout: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        text=True,
        timeout=10,
    ).strip()


def run(args: argparse.Namespace) -> bool:
    args.output.mkdir(parents=True, exist_ok=True)
    cases = fixtures(args.output / "fixtures")
    if args.cases:
        cases = [case for case in cases if case["name"] in args.cases]
    rows = []
    for case in cases:
        for variant in ("baseline", "candidate", "candidate", "baseline"):
            checkout = args.baseline if variant == "baseline" else args.candidate
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONPATH": str(checkout.resolve() / "src"),
                    "MEOWCAL_CORE_EXE": str(args.core.resolve()),
                    "MEOWCAL_CORE_PROFILE": "development",
                    "MEOWCAL_CORE_STORAGE_ROOT": str((args.output / "storage").resolve()),
                }
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--worker",
                    "--variant",
                    variant,
                    "--checkout",
                    str(checkout),
                    "--image",
                    case["path"],
                    "--language",
                    case["language"],
                    "--runs",
                    str(args.runs),
                    "--warmup",
                    str(args.warmup),
                    "--interval-ms",
                    str(args.interval_ms),
                ],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=300,
            )
            if completed.returncode:
                raise RuntimeError(f"{case['name']} {variant}: {completed.stderr}")
            row = {"case": case["name"], "variant": variant, **json.loads(completed.stdout)}
            rows.append(row)
            print(
                json.dumps(
                    {
                        key: value
                        for key, value in row.items()
                        if key not in {"samplesMs", "answers", "warmupSamplesMs", "warmupAnswers"}
                    }
                ),
                flush=True,
            )
            (args.output / "samples.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    comparisons = []
    for case in cases:
        groups = {
            variant: [
                row for row in rows if row["case"] == case["name"] and row["variant"] == variant
            ]
            for variant in ("baseline", "candidate")
        }
        stats = {
            variant: summarize([value for row in group for value in row["samplesMs"]])
            for variant, group in groups.items()
        }
        answers = {
            variant: {answer for row in group for answer in row["warmupAnswers"] + row["answers"]}
            for variant, group in groups.items()
        }
        comparison = compare(stats["baseline"], stats["candidate"])
        # All warm reads must agree within and across variants; empty is allowed
        # only for the explicit blank fixture.
        equivalent = answers["baseline"] == answers["candidate"] and len(answers["baseline"]) == 1
        meaningful = case["name"] == "blank" or answers["baseline"] != {""}
        comparisons.append(
            {
                "case": case["name"],
                **stats,
                **comparison,
                "equivalent": equivalent,
                "meaningful": meaningful,
            }
        )
    result = {
        "host": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version,
        "baselineRevision": revision(args.baseline),
        "candidateRevision": revision(args.candidate),
        "coreSha256": hashlib.sha256(args.core.read_bytes()).hexdigest(),
        "runsPerBlock": args.runs,
        "warmup": args.warmup,
        "intervalMs": args.interval_ms,
        "fixtures": cases,
        "comparisons": comparisons,
        "passed": all(
            row["passed"] and row["equivalent"] and row["meaningful"] for row in comparisons
        ),
    }
    (args.output / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result["passed"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--variant", choices=("baseline", "candidate"))
    parser.add_argument("--checkout", type=Path)
    parser.add_argument("--image", type=Path)
    parser.add_argument("--language", default="en-US")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--core", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output/ocr-benchmark"))
    parser.add_argument(
        "--cases", nargs="+", choices=("latin", "large", "color", "chinese", "blank")
    )
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--interval-ms", type=int, default=0, help="0 for saturation; 250 for 4 Hz")
    args = parser.parse_args()
    if args.runs < 1 or args.warmup < 1 or args.interval_ms < 0:
        parser.error("runs and warmup must be positive; interval must be nonnegative")
    if args.worker:
        asyncio.run(worker(args))
    else:
        if not args.baseline or not args.core:
            parser.error("--baseline and --core are required")
        sys.exit(0 if run(args) else 1)


if __name__ == "__main__":
    main()
