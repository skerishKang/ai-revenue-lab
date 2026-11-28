"""#8968: repeatable before/after headless Chrome captures (3 per phase)."""
from __future__ import annotations

import http.server
import json
from pathlib import Path
import subprocess
import sys
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def capture(phase):
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build-dist")], check=True)
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT / "dist"), **kwargs)
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    observations = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, executable_path=CHROME)
            try:
                base = f"http://127.0.0.1:{server.server_port}/"
                page = browser.new_page(viewport={"width": 820, "height": 1180},
                                        reduced_motion="reduce", device_scale_factor=1)
                page.goto(base + "policy.html", wait_until="load")
                page.evaluate("document.fonts.ready")
                page.locator("#textSizeToggle").click()
                page.locator(".policy-jump a").nth(2).click()
                observations["chip"] = page.evaluate("""() => {
                  const input = document.querySelector('#billSearch');
                  const rect = input.getBoundingClientRect();
                  return {active:document.activeElement===input, hash:location.hash,
                    searchVisible:rect.top>=0 && rect.bottom<=innerHeight,
                    headerClear:rect.top>=document.querySelector('.topbar').getBoundingClientRect().bottom+4,
                    outline:getComputedStyle(input).outlineStyle};
                }""")
                page.screenshot(path=str(OUTPUT / f"policy-chip-820-large-{phase}.png"))
                page.close()

                page = browser.new_page(viewport={"width": 1440, "height": 900},
                                        reduced_motion="reduce", device_scale_factor=1)
                page.goto(base + "policy.html", wait_until="load")
                page.evaluate("document.fonts.ready")
                page.evaluate("document.getElementById('billSearch').scrollIntoView({block:'center'})")
                observations["terms"] = page.locator("#policyBillTerms p").all_text_contents()
                page.screenshot(path=str(OUTPUT / f"policy-terms-1440-light-{phase}.png"))
                page.close()

                page = browser.new_page(viewport={"width": 390, "height": 844},
                                        reduced_motion="reduce", device_scale_factor=1)
                page.goto(base + "media.html", wait_until="load")
                page.evaluate("document.fonts.ready")
                page.locator(".media-tile").nth(1).click()
                page.locator("#mediaLightbox[open]").wait_for()
                page.locator("#lightboxLink").scroll_into_view_if_needed()
                observations["photoLabel"] = page.locator("#lightboxLink").inner_text()
                page.screenshot(path=str(OUTPUT / f"photo-lightbox-390-{phase}.png"))
                page.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print(json.dumps({"phase": phase, "observations": observations}, ensure_ascii=True))


if __name__ == "__main__":
    assert len(sys.argv) == 2 and sys.argv[1] in {"before", "after"}
    capture(sys.argv[1])
