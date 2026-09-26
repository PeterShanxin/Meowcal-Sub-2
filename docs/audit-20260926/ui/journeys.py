"""Walk the studio's core journeys against `demo_server.py` and screenshot them.

    python docs/audit-20260926/ui/journeys.py <journey> <viewport> <out-dir> <token> [--port 8765]

Journeys: pick (title, source and target to a prepared session), series (the
same by keyboard through a series), empty (a search that finds nothing and one
that fails), setup (no credential), first-launch (a zero-size saved region).
Each prints PASS or FAIL for the outcome a viewer needs from it; the server
should be restarted between journeys, because a prepared session outlives the
page.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "laptop": {"width": 1280, "height": 720},
    "mobile": {"width": 390, "height": 844},
}


def check(name: str, ok: bool) -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}")


def in_view(page: Page, locator) -> bool:
    box = locator.bounding_box()
    size = page.viewport_size
    return bool(
        box
        and box["x"] >= 0
        and box["y"] >= 0
        and box["x"] + box["width"] <= size["width"]
        and box["y"] + box["height"] <= size["height"]
    )


def search(page: Page, title: str):
    box = page.locator('input[data-palette="true"]')
    box.fill(title)
    box.press("Enter")
    page.wait_for_timeout(1800)
    return box


def pick(page: Page, shot) -> None:
    search(page, "Paper")
    shot("results")
    page.get_by_text("Paper Lanterns").first.click()
    page.get_by_text("Paper.Lanterns.2021.WEB-DL.1080p.en.srt").click()
    page.wait_for_timeout(1500)
    shot("target-step")
    page.get_by_text("Paper.Lanterns.2021.WEB-DL.1080p.chs.zh.srt").click()
    page.wait_for_timeout(3000)
    shot("prepared")
    start = page.get_by_role("button", name="Start OCR and sync")
    check("start button inside the window", in_view(page, start))
    edit = page.get_by_role("button", name="Edit subtitles", exact=True)
    edit.evaluate("node => node.scrollIntoView({block: 'end'})")
    page.wait_for_timeout(300)
    shot("prepared-scrolled")
    check("edit subtitles reachable", in_view(page, edit))


def series(page: Page, shot) -> None:
    box = search(page, "Harbor")
    for key in ("ArrowDown", "Enter", "ArrowDown"):
        box.press(key)
        page.wait_for_timeout(250)
    shot("series-open-cursor")
    for key in ("Enter", "ArrowDown", "Enter"):
        box.press(key)
        page.wait_for_timeout(400)
    page.wait_for_timeout(600)
    shot("episode-picked")
    check(
        "keyboard picked a Harbor Lights episode",
        page.get_by_text("Harbor.Lights.S01E01").count() > 0,
    )


def empty(page: Page, shot) -> None:
    search(page, "nothing here")
    shot("no-results")
    check("empty search says nothing was found", page.get_by_text("No titles found").count() > 0)
    search(page, "offline")
    shot("provider-error")
    check(
        "provider failure offers a retry", page.get_by_role("button", name="Try again").count() > 0
    )


def setup(page: Page, shot) -> None:
    shot("landing")
    check(
        "setup card inside the window",
        in_view(page, page.get_by_role("button", name="Open Settings", exact=True)),
    )


def first_launch(page: Page, shot) -> None:
    shot("landing")
    page.get_by_role("button", name="Open command palette").click()
    page.wait_for_timeout(700)
    shot("palette-requested")
    check("palette opens from first launch", page.locator('input[data-palette="true"]').count() > 0)


JOURNEYS = {"pick": pick, "series": series, "empty": empty, "setup": setup}
JOURNEYS["first-launch"] = first_launch


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture a Studio demo journey.")
    parser.add_argument("journey", choices=JOURNEYS)
    parser.add_argument("viewport", choices=VIEWPORTS)
    parser.add_argument("out")
    parser.add_argument("token")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    journey, viewport, out, token = args.journey, args.viewport, args.out, args.token
    Path(out).mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport=VIEWPORTS[viewport])
        page.route(
            "https://fonts.googleapis.com/**",
            lambda route: route.fulfill(status=200, content_type="text/css", body=""),
        )
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"http://127.0.0.1:{args.port}/?token={token}")
        page.wait_for_timeout(1500)

        def shot(step: str) -> None:
            page.screenshot(path=f"{out}/{viewport}-{journey}-{step}.png")

        JOURNEYS[journey](page, shot)
        check("no page errors", not errors)
        browser.close()


if __name__ == "__main__":
    main()
