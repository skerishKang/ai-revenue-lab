"""#6460 S1 — the captured screen renders in the conversation at both widths.

The route test proves one owner-scoped capture is dispatched; this proves the
existing display module upgrades that message into a real image, keeps it
inside the column and adds no undersized control. The JPEG is produced by the
browser itself (canvas), so no fixture binary is checked in and no real PC is
touched.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover - CI without a browser
    sync_playwright = None

STATIC = Path(__file__).resolve().parents[1] / "static"
DISPATCH = "dsp_" + "a" * 32
TARGET_FLOOR = 44.0
TEXT_FLOOR = 14.0
VIEWPORTS = ((1440, 900), (390, 844))


def _jpeg(page) -> bytes:
    data_url = page.evaluate(
        """() => {
          const canvas = document.createElement("canvas");
          canvas.width = 800; canvas.height = 600;
          const ctx = canvas.getContext("2d");
          ctx.fillStyle = "#203040"; ctx.fillRect(0, 0, 800, 600);
          ctx.fillStyle = "#ffffff"; ctx.font = "48px sans-serif";
          ctx.fillText("screen", 48, 120);
          return canvas.toDataURL("image/jpeg", 0.8);
        }"""
    )
    return base64.b64decode(data_url.split(",", 1)[1])


class Mock(http.server.SimpleHTTPRequestHandler):
    jpeg = b""
    digest = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/api/auth/status":
            self._json({"ready": True, "authenticated": True,
                        "user": {"id": "usr_qa", "name": "의원"}})
            return
        if path == "/api/claw/connector/mesh-results/" + DISPATCH:
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(Mock.jpeg)))
            self.send_header("x-oracle-mesh-content-sha256", Mock.digest)
            self.end_headers()
            self.wfile.write(Mock.jpeg)
            return
        if path.startswith("/api/"):
            self._json({})
            return
        super().do_GET()


@pytest.fixture(scope="module")
def chat_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Mock)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d/index.html" % server.server_port
    server.shutdown()
    thread.join(timeout=5)


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_the_capture_renders_inside_the_conversation(chat_url, width, height):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            page.goto(chat_url, wait_until="domcontentloaded")
            Mock.jpeg = _jpeg(page)
            Mock.digest = hashlib.sha256(Mock.jpeg).hexdigest()
            page.evaluate(
                """(args) => {
                  // The list and the conversation are the product's own; they
                  // are revealed the way any landed answer reveals them.
                  const list = document.getElementById("messageList");
                  list.hidden = false;
                  document.getElementById("emptyState").hidden = true;
                  const article = document.createElement("article");
                  article.className = "assistant-message";
                  const content = document.createElement("div");
                  content.className = "assistant-content";
                  const p = document.createElement("p");
                  p.textContent = "화면 캡처 원문: GET /api/claw/connector/mesh-results/"
                    + args.id + " SHA-256: " + args.sha;
                  content.appendChild(p);
                  article.appendChild(content);
                  list.appendChild(article);
                }""",
                {"id": DISPATCH, "sha": Mock.digest},
            )
            image = page.locator("img.mesh-capture-image")
            image.wait_for(timeout=10000)
            page.wait_for_timeout(300)
            value = page.evaluate(
                """(cfg) => {
                  const img = document.querySelector("img.mesh-capture-image");
                  const box = img.getBoundingClientRect();
                  // Only the conversation column: the capture must not add an
                  // undersized control of its own beside the answer.
                  const column = document.querySelector(".conversation") || document.body;
                  const small = [...column.querySelectorAll(
                    "a[href], button, input:not([type=hidden]), select, textarea, summary,"
                    + " [role=\\"button\\"]")]
                    .filter((el) => el.getBoundingClientRect().width > 0)
                    .filter((el) => {
                      const r = el.getBoundingClientRect();
                      return Math.round(r.width) < cfg.floor || Math.round(r.height) < cfg.floor;
                    })
                    .map((el) => el.id || el.className || el.tagName);
                  const content = document.querySelector(".assistant-content");
                  const font = content ? parseFloat(getComputedStyle(content).fontSize) : null;
                  return {
                    decoded: img.naturalWidth > 0 && img.naturalHeight > 0,
                    right: Math.round(box.right), left: Math.round(box.left),
                    width: Math.round(box.width), vw: innerWidth,
                    overflow: document.documentElement.scrollWidth - innerWidth,
                    font, small,
                  };
                }""",
                {"floor": TARGET_FLOOR},
            )
        finally:
            browser.close()
    assert value["decoded"], "the capture did not decode into a real image"
    assert value["left"] >= -1 and value["right"] <= value["vw"] + 1, value
    assert value["overflow"] <= 0, value
    assert value["font"] is not None and value["font"] >= TEXT_FLOOR, value
    assert not value["small"], "an undersized control appeared with the capture: %s" % value["small"]
