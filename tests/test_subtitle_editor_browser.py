"""Exercise the built studio and real editor API with synthetic subtitle files."""

import socket
import threading
import time

import uvicorn
from playwright.sync_api import expect, sync_playwright

from tests.conftest import TEST_TOKEN
from tests.test_subtitle_editor import SOURCE, TARGET, editor_server


def test_subtitle_editor_workflow(tmp_path):
    app = editor_server(tmp_path)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        app._allowed_origins = {f"http://127.0.0.1:{port}"}
        server = uvicorn.Server(uvicorn.Config(app.app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert server.started
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page(viewport={"width": 1280, "height": 900})
                    page.set_default_timeout(7000)
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{port}/?token={TEST_TOKEN}")
                    page.get_by_role("button", name="Edit subtitles", exact=True).click()
                    dialog = page.get_by_role("dialog", name="Review before sync")
                    expect(dialog).to_be_visible()
                    expect(dialog.locator("textarea")).to_be_visible()
                    text = dialog.get_by_label("Subtitle text", exact=True)
                    text.fill("Corrected source 🐱")
                    expect(dialog.get_by_label("Track", exact=True)).to_be_disabled()
                    expect(
                        dialog.get_by_role("button", name="Save & use", exact=True)
                    ).to_be_disabled()
                    text.press("Control+Enter")
                    assert app.controller._state.status == "idle"
                    dialog.get_by_role("button", name="Keep edit", exact=True).click()
                    dialog.get_by_role("button", name="Undo", exact=True).click()
                    expect(text).to_have_value("Hello world")
                    dialog.get_by_role("button", name="Redo", exact=True).click()
                    expect(text).to_have_value("Corrected source 🐱")
                    dialog.get_by_label("Shift (ms)", exact=True).fill("500")
                    dialog.get_by_role("button", name="Preview timing", exact=True).click()
                    dialog.get_by_role("button", name="Preview timing", exact=True).click()
                    expect(dialog.locator(".editor-preview-time").first).to_contain_text(
                        "00:00:01.500"
                    )
                    dialog.get_by_label("Track", exact=True).select_option("1")
                    expect(dialog.get_by_label("Shift (ms)", exact=True)).to_have_value("0")
                    dialog.get_by_label("Track", exact=True).select_option("0")
                    expect(dialog.get_by_label("Shift (ms)", exact=True)).to_have_value("500")
                    expect(dialog.locator(".editor-preview-time").first).to_contain_text(
                        "00:00:01.500"
                    )
                    dialog.get_by_role("button", name="Apply timing", exact=True).click()
                    expect(dialog.get_by_label("Start (ms)", exact=True)).to_have_value("1500")
                    dialog.get_by_label("Track", exact=True).select_option("1")
                    dialog.get_by_label("Method", exact=True).select_option("anchors")
                    dialog.get_by_label("Subtitle time 1 (ms)", exact=True).fill("1000")
                    dialog.get_by_label("Video time 1 (ms)", exact=True).fill("1500")
                    dialog.get_by_label("Subtitle time 2 (ms)", exact=True).fill("3000")
                    dialog.get_by_label("Video time 2 (ms)", exact=True).fill("3500")
                    dialog.get_by_role("button", name="Preview timing", exact=True).click()
                    dialog.get_by_role("button", name="Apply timing", exact=True).click()
                    with page.expect_download() as downloaded:
                        dialog.get_by_role("button", name="Export copy", exact=True).click()
                    download = downloaded.value
                    exported = tmp_path / download.suggested_filename
                    download.save_as(exported)
                    assert "NOTE retained\n猫" in exported.read_text(encoding="utf-8")
                    assert "00:00:01.500 --> 00:00:02.500 align:start" in exported.read_text(
                        encoding="utf-8"
                    )
                    dialog.get_by_role("button", name="Save & use", exact=True).click()
                    expect(dialog).not_to_be_visible()
                    expect(
                        page.get_by_text("Corrected copies saved and ready for sync.", exact=False)
                    ).to_be_visible()
                    runtime = app.controller._prepared_runtime
                    assert (
                        runtime.source_candidates[0].pair.source_lines[0].text
                        == "Corrected source 🐱"
                    )
                    assert runtime.source_candidates[0].pair.source_lines[0].start_ms == 1500
                    assert runtime.target_lines[0].start_ms == 1500
                    assert (tmp_path / "source.srt").read_text(encoding="utf-8") == SOURCE
                    assert (tmp_path / "target.vtt").read_text(encoding="utf-8") == TARGET
                    page.get_by_role("button", name="Edit subtitles", exact=True).click()
                    expect(text).to_have_value("Corrected source 🐱")
                    text.fill("")
                    dialog.get_by_role("button", name="Keep edit", exact=True).click()
                    expect(
                        dialog.get_by_role("button", name="Save & use", exact=True)
                    ).to_be_disabled()
                    expect(
                        dialog.get_by_role("button", name="Export copy", exact=True)
                    ).to_be_disabled()
                    dialog.get_by_role("button", name="Undo", exact=True).click()
                    large = "\n".join(
                        f"{i + 1}\n00:00:01,000 --> 00:00:02,000\nSubtitle {i + 1}\n"
                        for i in range(5000)
                    )
                    dialog.get_by_label("Import replacement", exact=True).set_input_files(
                        {"name": "large.srt", "mimeType": "text/plain", "buffer": large.encode()}
                    )
                    expect(
                        dialog.get_by_text("large.srt · SRT · 5,000 subtitles", exact=True)
                    ).to_be_visible()
                    dialog.get_by_label("Jump to subtitle", exact=True).fill("4999")
                    dialog.get_by_role("button", name="Go", exact=True).click()
                    expect(text).to_have_value("Subtitle 4999")
                    dialog.get_by_label("Shift (ms)", exact=True).fill("250")
                    dialog.get_by_role("button", name="Preview timing", exact=True).click()
                    expect(dialog.locator(".editor-preview-time").first).to_contain_text(
                        "00:00:01.250"
                    )
                    assert dialog.locator("tbody tr").count() <= 30
                    assert dialog.evaluate("node => node.scrollWidth <= node.clientWidth")
                    page.set_viewport_size({"width": 720, "height": 700})
                    assert dialog.evaluate("node => node.scrollWidth <= node.clientWidth")
                    dialog.get_by_role("button", name="Apply timing", exact=True).click()
                    page.screenshot(path=str(tmp_path / "editor.png"))
                    page.on("dialog", lambda popup: popup.dismiss())
                    dialog.get_by_role("button", name="Close subtitle editor").click()
                    expect(dialog).to_be_visible()
                    assert errors == []
                finally:
                    browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()
