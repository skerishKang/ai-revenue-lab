"""Library subtitle painted contrast regression (#8686 follow-up)."""
from __future__ import annotations
import io
import math
import re
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image
from _support import contrast_repair_source as source
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

STATIC = Path(__file__).resolve().parents[1] / "static"
VIEWPORTS = ((1440, 950), (390, 844))
TEXT_BOX = r'''() => {
  const el = document.querySelector('#librarySubtitle');
  const style = getComputedStyle(el);
  const range = document.createRange();
  range.selectNodeContents(el);
  const rectangles = Array.from(range.getClientRects()).filter(r => r.width > 0 && r.height > 0);
  return {
    color: style.color,
    opacity: parseFloat(style.opacity || '1'),
    box: [Math.min(...rectangles.map(r => r.left)),
          Math.min(...rectangles.map(r => r.top)),
          Math.max(...rectangles.map(r => r.right)),
          Math.max(...rectangles.map(r => r.bottom))],
    shown: rectangles.length > 0 && style.visibility !== 'hidden'
  };
}'''
FETCH_STUB = r'''(() => {
  const original = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = String(typeof input === "string" ? input : input.url || "");
    if (!url.includes("/api/")) return original(input, init);
    const auth = url.includes("/api/auth/status");
    const body = auth ? {
      ready: true, authenticated: true, user: {email: "qa@padiem.local", name: "QA"},
      session_state: "active", shared_login_enabled: false, shared_session_present: false,
      status_reachable: true, history_ready: true, project_files_ready: true,
      model_requires_session: false
    } : {ok: false};
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: auth ? 200 : 404, headers: {"content-type": "application/json"}
    }));
  };
})()'''

class _StaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

@pytest.fixture(scope="module")
def site():
    handler = partial(_StaticHandler, directory=str(STATIC))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/index.html"
    finally:
        server.shutdown()
        thread.join(timeout=5)

def _painted_ratio(page):
    bounds = page.evaluate(TEXT_BOX)
    assert bounds["shown"], "library subtitle was not rendered"
    css_color = tuple(float(x) for x in re.findall(r"[\d.]+", bounds["color"]))
    ink = css_color[:3] + ((css_color[3] if len(css_color) > 3 else 1) * bounds["opacity"],)
    hidden = page.add_style_tag(content=(
        "*,*::before,*::after{color:transparent!important;"
        "-webkit-text-fill-color:transparent!important;"
        "text-shadow:none!important;caret-color:transparent!important;"
        "transition:none!important}"
    ))
    page.wait_for_timeout(150)
    picture = Image.open(io.BytesIO(page.screenshot(animations="disabled"))).convert("RGB")
    hidden.evaluate("el => el.remove()")
    left, top, right, bottom = bounds["box"]
    crop = picture.crop((max(0, int(left)), max(0, int(top)),
                         min(picture.width, math.ceil(right)), min(picture.height, math.ceil(bottom))))
    assert crop.width > 0 and crop.height > 0
    return min(source.contrast(ink, rgb + (1.0,)) for rgb in set(crop.getdata()))

@pytest.mark.skipif(sync_playwright is None, reason="playwright not installed")
def test_library_subtitle_contrast(site):
    rule = source.rule_declarations("library.css", ".library-subtitle")
    assert rule.get("color") == "var(--standalone-tagline-text)"
    assert rule.get("opacity", "1") == "1"
    observations = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for theme in source.THEMES:
                for width, height in VIEWPORTS:
                    page = browser.new_page(viewport={"width": width, "height": height},
                                            reduced_motion="reduce")
                    page.route("**/*", lambda route: route.continue_()
                               if "127.0.0.1" in route.request.url else route.abort())
                    page.add_init_script(FETCH_STUB)
                    page.goto(site + "?theme=" + theme, wait_until="load")
                    page.wait_for_timeout(1600)
                    assert page.evaluate("document.documentElement.dataset.theme") == theme
                    page.evaluate("document.getElementById('filesNavButton').click()")
                    page.wait_for_timeout(900)
                    observations.append((theme, width, _painted_ratio(page)))
                    page.close()
        finally:
            browser.close()
    assert len(observations) == 10
    assert all(ratio >= 4.5 for _, _, ratio in observations), observations
