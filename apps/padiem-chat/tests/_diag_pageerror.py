# One-off diagnostic (not committed): catch the page's JS error with its stack.
import http.server
import sys
import threading
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

ROOT = Path(r"D:/클로드/261027/261027-3/ai-revenue-lab/apps/padiem-chat/static")

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)
    def log_message(self, *_a):
        pass

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_address[1]}/index.html"

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    page = b.new_page(viewport={"width": 1280, "height": 900})
    caught = []
    page.on("pageerror", lambda e: caught.append("PAGEERROR\n" + (e.stack or str(e))))
    page.goto(url)
    page.wait_for_timeout(2500)
    before = len(caught)
    page.evaluate("document.documentElement.lang = 'en'")
    page.wait_for_timeout(2500)
    print(f"=== errors before lang switch: {before}, after: {len(caught)} ===")
    b.close()
srv.shutdown()

for line in caught:
    print(line[:2000])
