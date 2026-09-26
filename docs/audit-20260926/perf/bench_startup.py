"""Studio navigation: backend spawn, search input DOM insertion and first paint.

Cold: a fresh `python -m meocosub2.cli serve` and a fresh browser context each
run. Warm (live CDN only): the same backend, a new page in a context whose
HTTP cache already holds the hashed bundle. Routed CDN modes disable Chromium
HTTP caching; their second visit is labeled repeat_navigation, not warm.
Headless Chromium stands in for WebView2, so the numbers describe the served
page and the backend, not native shell painting.

Page timings are taken inside the page (`performance.now()`, i.e. from
navigation start), so a slow Playwright route handler cannot inflate them.
The font CDN is reached through the container's proxy; its CA has to be in
Chromium's NSS store (`certutil -A -t C,, -i agent-proxy-ca.crt`) or every
"live" font request fails TLS instead of loading.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[3]
ORIGIN = "http://127.0.0.1:8765"
READY = f"{ORIGIN}/static/selector.js"
PALETTE_TIMEOUT_MS = 20_000
FONT_WAIT_MS = 8_000

METRICS_JS = """
() => {
  const nav = performance.getEntriesByType('navigation')[0];
  const paint = Object.fromEntries(performance.getEntriesByType('paint').map(p => [p.name, p.startTime]));
  const res = performance.getEntriesByType('resource');
  return {
    palette_ready_ms: window.__paletteAt ?? null,
    fonts_loaded_ms: window.__fontsAt ?? null,
    font_css_media: [...document.querySelectorAll('link[href*="fonts.googleapis"]')].map(l => l.media).join(),
    ttfb: nav.responseStart - nav.requestStart,
    dcl: nav.domContentLoadedEventEnd,
    load: nav.loadEventEnd,
    fcp: paint['first-contentful-paint'] ?? null,
    lcp: window.__lcp ?? null,
    longTasks: window.__longTasks ?? [],
    transferred: res.reduce((a, r) => a + (r.transferSize || 0), 0),
    requests: res.map(r => ({name: r.name.replace(location.origin, ''), ms: Math.round(r.duration), bytes: r.transferSize})),
  };
}
"""
OBSERVERS_JS = """
window.__longTasks = [];
new PerformanceObserver(l => l.getEntries().forEach(e => window.__longTasks.push(Math.round(e.duration)))).observe({type: 'longtask', buffered: true});
new PerformanceObserver(l => { const e = l.getEntries(); window.__lcp = e[e.length - 1].startTime; }).observe({type: 'largest-contentful-paint', buffered: true});
new MutationObserver((_, observer) => {
  if (document.querySelector('input[data-palette="true"]')) { window.__paletteAt = performance.now(); observer.disconnect(); }
}).observe(document, {childList: true, subtree: true});
document.fonts.addEventListener('loadingdone', () => {
  if (window.__fontsAt === undefined && [...document.fonts].some(f => f.family === 'Inter' && f.status === 'loaded')) window.__fontsAt = performance.now();
});
"""


def _wait_ready(deadline_s: float) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < deadline_s:
        try:
            with urllib.request.urlopen(READY, timeout=1) as response:
                if response.status == 200:
                    return time.perf_counter() - started
        except OSError:
            time.sleep(0.02)
    raise TimeoutError("backend did not start")


def _token(appdata: str) -> str:
    runtime = Path(appdata) / "meowcal-sub-2" / "runtime.json"
    for _ in range(200):
        try:
            return json.loads(runtime.read_text(encoding="utf-8"))["token"]
        except (OSError, ValueError, KeyError):
            # Not written yet, or caught mid-write.
            time.sleep(0.02)
    raise RuntimeError("no runtime token")


FONT_HOSTS = ("https://fonts.googleapis.com/**", "https://fonts.gstatic.com/**")


def _route_fonts(context, mode: str) -> None:
    """Simulate the font CDN: `live` leaves it alone, `slow` holds the stylesheet
    request 1.5 s, `blocked` fails it at once, `hang` never answers (a filtered
    network). Font files are left alone in `slow` so the delay stays 1.5 s."""
    if mode == "live":
        return

    def handler(route):
        if mode == "blocked":
            route.abort()
        elif mode == "slow":
            time.sleep(1.5)
            route.continue_()
        # hang: leave the request pending

    for host in FONT_HOSTS if mode != "slow" else FONT_HOSTS[:1]:
        context.route(host, handler)


def _visit(context, url: str) -> dict:
    page = context.new_page()
    page.add_init_script(OBSERVERS_JS)
    page.goto(url, wait_until="commit")
    try:
        page.wait_for_selector('input[data-palette="true"]', timeout=PALETTE_TIMEOUT_MS)
    except PlaywrightTimeout:
        # Recorded at the cap rather than dropped: "never became usable" is the result.
        page.close()
        return {"palette_ready_ms": float(PALETTE_TIMEOUT_MS), "timed_out": True}
    # `load` waits on every stylesheet, so it never fires while the font CDN hangs.
    with contextlib.suppress(PlaywrightTimeout):
        page.wait_for_load_state("load", timeout=FONT_WAIT_MS)
    # Give the web fonts a bounded chance to arrive, to see when the text swaps.
    with contextlib.suppress(PlaywrightTimeout):
        page.wait_for_function("window.__fontsAt !== undefined", timeout=FONT_WAIT_MS)
    metrics = page.evaluate(METRICS_JS)
    page.close()
    return metrics


def run(repeat: int, fonts: str) -> list[dict]:
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for attempt in range(repeat):
            with tempfile.TemporaryDirectory(prefix="meowcal-bench-") as appdata:
                # A configured provider, as in scripts/run_dashboard_smoke.py, so the
                # studio opens on the search palette rather than onboarding.
                config_dir = Path(appdata) / "meowcal-sub-2"
                config_dir.mkdir(parents=True)
                (config_dir / "config.toml").write_text(
                    '[subtitle_sources.subdl]\nenabled = true\napi_key = "bench-key"\n',
                    encoding="utf-8",
                )
                env = {**os.environ, "APPDATA": appdata, "PYTHONUTF8": "1"}
                spawned = time.perf_counter()
                process = subprocess.Popen(
                    [sys.executable, "-m", "meocosub2.cli", "serve"],
                    cwd=REPO,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                try:
                    backend_ready_ms = _wait_ready(30) * 1000
                    url = f"{ORIGIN}/?token={_token(appdata)}"
                    context = browser.new_context()
                    _route_fonts(context, fonts)
                    navigating = time.perf_counter()
                    cold = _visit(context, url)
                    # Approximate: navigation starts as goto is issued.
                    cold["spawn_to_palette_ms"] = round(
                        (navigating - spawned) * 1000 + cold["palette_ready_ms"], 1
                    )
                    second_visit = _visit(context, url)
                    context.close()
                finally:
                    process.terminate()
                    process.wait(timeout=10)
                results.append(
                    {
                        "attempt": attempt,
                        "backend_ready_ms": round(backend_ready_ms, 1),
                        "cold": cold,
                        ("warm" if fonts == "live" else "repeat_navigation"): second_visit,
                    }
                )
                print(
                    json.dumps(results[-1]["cold"] | {"backend_ready_ms": backend_ready_ms}),
                    file=sys.stderr,
                )
        browser.close()
    return results


def summarize(results: list[dict]) -> dict:
    def med(values):
        return round(statistics.median(values), 1)

    out = {"backend_ready_ms": med([r["backend_ready_ms"] for r in results])}
    for kind in ("cold", "warm" if "warm" in results[0] else "repeat_navigation"):
        rows = [r[kind] for r in results]
        out[kind] = {
            key: med(values)
            for key in (
                "ttfb",
                "fcp",
                "lcp",
                "dcl",
                "palette_ready_ms",
                "fonts_loaded_ms",
                "transferred",
            )
            if (values := [row[key] for row in rows if row.get(key) is not None])
        }
        out[kind]["timed_out"] = sum(bool(row.get("timed_out")) for row in rows)
        out[kind]["long_tasks_max_ms"] = max(
            max(row.get("longTasks", []), default=0) for row in rows
        )
    out["cold"]["spawn_to_palette_ms"] = med([r["cold"]["spawn_to_palette_ms"] for r in results])
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=7)
    parser.add_argument("--fonts", choices=("live", "slow", "blocked", "hang"), default="live")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    results = run(args.repeat, args.fonts)
    summary = {
        "fonts": args.fonts,
        "http_cache_enabled": args.fonts == "live",
        **summarize(results),
    }
    print(json.dumps(summary, indent=1))
    if args.out:
        args.out.write_text(
            json.dumps({"summary": summary, "runs": results}, indent=1), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
