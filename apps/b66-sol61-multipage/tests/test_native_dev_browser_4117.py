"""Windows-only real Chromium browser test of NOT_CERTIFIED Sol dev gateway."""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(HERE))
from native_dev_gateway import create_dev_server

@pytest.mark.skipif(os.environ.get("B66_SOL61_LOCAL_BROWSER") != "1",
                    reason="Explicit Windows-local browser proof only")
def test_4117_chromium_actual_preview_download_and_drive_byte_proof(tmp_path):
    from playwright.sync_api import sync_playwright

    server, _ = create_dev_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--disable-extensions"])
            try:
                page = browser.new_page(accept_downloads=True)
                origin = f"http://127.0.0.1:{server.server_port}"
                page.goto(origin + "/", wait_until="domcontentloaded")
                assert "로컬" in page.title()
                assert page.locator("#preview").is_hidden()
                page.locator("#render").click()
                page.wait_for_function(
                    "() => !document.querySelector('#download').disabled",
                    timeout=30000)
                assert page.locator("#preview").is_visible()
                assert page.locator("#preview").get_attribute("src").startswith("blob:")
                assert "페이지: 2" in page.locator("#status").inner_text()
                html_sha = page.locator("#status").inner_text().split("SHA-256: ", 1)[1].splitlines()[0]
                with page.expect_download() as captured:
                    page.locator("#download").click()
                output = tmp_path / "actual-sol-browser.pdf"
                captured.value.save_as(output)
                raw = output.read_bytes()
                assert raw.startswith(b"%PDF-")
                assert hashlib.sha256(raw).hexdigest() == html_sha
                page.locator("#drive").click()
                page.wait_for_function(
                    "() => document.querySelector('#status').textContent.includes('실제 Google Drive API 호출 0건')",
                    timeout=5000)
                assert "실제 Google Drive API 호출 0건" in page.locator("#status").inner_text()
                assert html_sha in page.locator("#status").inner_text()
                page.locator("#changes").fill('{"changes":{}}')
                assert page.locator("#preview").is_hidden()
                assert page.locator("#download").is_disabled()
                assert page.locator("#drive").is_disabled()
                assert page.locator("#preview").get_attribute("src") is None
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
