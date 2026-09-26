#!/usr/bin/env bash
# Usage: run.sh <label>   Writes results/<label>/*.json from the current checkout.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../../.." && pwd)"
python="${PYTHON:-$repo/.venv/bin/python}"
out="$here/results/$1"
mkdir -p "$out"
cd "$here"
"$python" - "$out/env.json" <<'PY'
import json, os, platform, subprocess, sys
import rapidfuzz, pysubs2
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(); chromium = browser.version; browser.close()
json.dump({
    "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "dirty": bool(subprocess.check_output(["git", "status", "--porcelain", "--", "../../../src"], text=True).strip()),
    "python": sys.version.split()[0], "platform": platform.platform(),
    "cpu": next((l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")), ""),
    "cpus": os.cpu_count(), "rapidfuzz": rapidfuzz.__version__, "pysubs2": pysubs2.VERSION, "chromium": chromium,
}, open(sys.argv[1], "w"), indent=1)
PY
"$python" bench_prepare.py --repeat 7 --out "$out/prepare.json"
"$python" bench_live.py --repeat 3 --minutes 10 --out "$out/live.json"
for fonts in live slow blocked hang; do
  if [ "$fonts" = hang ]; then repeat=2; else repeat=7; fi
  "$python" bench_startup.py --repeat "$repeat" --fonts "$fonts" --out "$out/startup-$fonts.json" >/dev/null
done
