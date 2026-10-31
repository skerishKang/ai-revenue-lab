from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
STATIC = Path(__file__).resolve().parents[1] / "static"
PATHS = ("/api/pc/pairings", "/api/claw/local-access/connect",
         "/api/claw/local-access/devices", "/api/claw/verified-model-choices")


def test_guest_login_logout_private_reads():
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.exists():
        pytest.skip("Chrome unavailable")
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(STATIC)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    seen = []
    try:
        with sync_api.sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, executable_path=str(chrome))
            page = browser.new_page()
            def route(r):
                req = r.request
                path = req.url.split("?", 1)[0].split(f":{server.server_port}", 1)[-1]
                if path.startswith("/api/"):
                    if path in PATHS:
                        seen.append(path)
                    if path == "/api/auth/status":
                        r.fulfill(json={"ready": True, "authenticated": False, "user": None, "session_state": "guest"})
                    else:
                        r.fulfill(json={"ok": True, "available": False, "links": []})
                elif req.url.startswith(f"http://127.0.0.1:{server.server_port}/"):
                    r.continue_()
                else:
                    r.abort()
            page.route("**/*", route)
            page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="domcontentloaded")
            page.wait_for_timeout(1800)
            assert seen == []
            page.evaluate("""() => window.dispatchEvent(new CustomEvent('padiem:auth-state', {detail:{authenticated:true}}))""")
            page.wait_for_timeout(1000)
            assert set(seen) == set(PATHS), seen
            page.evaluate("""() => window.dispatchEvent(new CustomEvent('padiem:auth-state', {detail:{authenticated:false}}))""")
            seen.clear()
            page.evaluate("""() => {window.dispatchEvent(new Event('padiem:tierchange'));window.dispatchEvent(new Event('padiem:localechange'));window.dispatchEvent(new Event('pageshow'));}""")
            page.wait_for_timeout(500)
            assert seen == []
            browser.close()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
