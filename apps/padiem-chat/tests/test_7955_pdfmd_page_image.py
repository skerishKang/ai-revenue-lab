"""#7955 ① — compare-view original page rendering with pypdfium2.

The pane was empty on COM2 because the renderer was PyMuPDF, which the host
never installs. This proves the pypdfium2 path end to end with computed values:
pixel sizes from the page geometry, owner-scoped reads, and the fallback when
no renderer is installed.
"""

from __future__ import annotations

import asyncio
import builtins
import http.server
import io
import json
import os
import shutil
import sqlite3
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.document_page_render import (
    JPEG_MAGIC,
    MAX_PAGE_LONG_EDGE_PX,
    PageRenderFailed,
    PageRenderUnavailable,
    bounded_long_edge,
    render_page,
)
from app.main import create_app

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover - CI without a browser
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
MIGRATION = ROOT / "migrations" / "066_document_convert_jobs.sql"
SCAN_PAGES_MIGRATION = ROOT / "migrations" / "116_document_convert_scan_pages.sql"
BASE = "https://chat.example.test"
PDF_MEDIA = "application/pdf"
OWNER = "usr_" + "a" * 32
INTRUDER = "usr_" + "c" * 32
SESSION_SECRET = "phase7955-page-image-session-secret-not-a-real-key-000"
CHROME_CANDIDATES = [
    os.environ.get("B61_CHROME_PATH"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]
CHROME = next((c for c in CHROME_CANDIDATES if c and Path(c).is_file()), None)


@pytest.fixture(autouse=True)
def _legacy_conversion_contract(monkeypatch):
    """These tests exercise the ledger behind the #5710 migration pause."""

    from app import document_convert_routes

    monkeypatch.setattr(document_convert_routes, "PDFMD_NEW_WORK_DISABLED", False)


# --------------------------------------------------------------------------
# 합성 PDF — 고객 파일 없음
# --------------------------------------------------------------------------


def _pdf(texts: list[str], *, width: int = 612, height: int = 792) -> bytes:
    writer = __import__("pypdf").PdfWriter()
    font = __import__("pypdf.generic", fromlist=["DictionaryObject"]).DictionaryObject(
        {
            __import__("pypdf.generic", fromlist=["NameObject"]).NameObject("/Type"):
                __import__("pypdf.generic", fromlist=["NameObject"]).NameObject("/Font"),
            __import__("pypdf.generic", fromlist=["NameObject"]).NameObject("/Subtype"):
                __import__("pypdf.generic", fromlist=["NameObject"]).NameObject("/Type1"),
            __import__("pypdf.generic", fromlist=["NameObject"]).NameObject("/BaseFont"):
                __import__("pypdf.generic", fromlist=["NameObject"]).NameObject("/Helvetica"),
        }
    )
    ref = writer._add_object(font)
    generic = __import__("pypdf.generic", fromlist=["NameObject"])
    for index, text in enumerate(texts):
        page = writer.add_blank_page(width=width, height=height)
        page[generic.NameObject("/Resources")] = generic.DictionaryObject(
            {generic.NameObject("/Font"): generic.DictionaryObject({generic.NameObject("/F1"): ref})}
        )
        stream = f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET".encode("latin-1") if text else b""
        content = generic.DecodedStreamObject()
        content.set_data(stream)
        page[generic.NameObject("/Contents")] = writer._add_object(content)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# --------------------------------------------------------------------------
# 계산 값: 쪽 수·그림 크기
# --------------------------------------------------------------------------


def test_a_page_renders_at_the_requested_long_edge() -> None:
    payload = _pdf(["page one", "page two", "page three"])

    first = render_page(payload, 1, long_edge_px=600)
    last = render_page(payload, 3, long_edge_px=600)

    # 612 x 792 at a 600px long edge -> 464 x 600.
    assert (first.width, first.height) == (464, 600)
    assert (last.width, last.height) == (464, 600)
    assert first.number == 1 and last.number == 3
    assert first.jpeg.startswith(JPEG_MAGIC)
    assert first.jpeg != last.jpeg, "each page must be its own raster"


def test_the_long_edge_is_bounded() -> None:
    payload = _pdf(["bounded"])

    huge = render_page(payload, 1, long_edge_px=99999)
    tiny = render_page(payload, 1, long_edge_px=0)

    assert huge.width <= MAX_PAGE_LONG_EDGE_PX
    assert huge.height <= MAX_PAGE_LONG_EDGE_PX
    assert max(tiny.width, tiny.height) >= 200
    assert bounded_long_edge("nonsense") == 1200
    assert bounded_long_edge(99999) == MAX_PAGE_LONG_EDGE_PX


def test_out_of_range_pages_fail() -> None:
    payload = _pdf(["only one"])

    for number in (0, 2, 999):
        with pytest.raises(PageRenderFailed):
            render_page(payload, number, long_edge_px=600)


def test_a_missing_renderer_is_reported_separately(monkeypatch) -> None:
    real_import = builtins.__import__

    def no_pdfium(name, *args, **kwargs):
        if name == "pypdfium2":
            raise ModuleNotFoundError("No module named 'pypdfium2'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pdfium)
    with pytest.raises(PageRenderUnavailable):
        render_page(_pdf(["x"]), 1)


# --------------------------------------------------------------------------
# HTTP 경계: 소유자·게스트·캐시
# --------------------------------------------------------------------------


class _Statement:
    def __init__(self, db, sql, params=()):
        self.db, self.sql, self.params = db, sql, params

    def bind(self, *params):
        return _Statement(self.db, self.sql, params)

    async def first(self):
        row = self.db.conn.execute(self.sql, self.params).fetchone()
        return dict(row) if row else None

    async def all(self):
        return [dict(row) for row in self.db.conn.execute(self.sql, self.params).fetchall()]

    async def run(self):
        cursor = self.db.conn.execute(self.sql, self.params)
        return {"meta": {"changes": cursor.rowcount}}


class FakeD1:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(MIGRATION.read_bytes().decode("utf-8"))
        self.conn.executescript(SCAN_PAGES_MIGRATION.read_bytes().decode("utf-8"))

    def prepare(self, sql):
        return _Statement(self, sql)


class _Object:
    def __init__(self, payload):
        self.body = payload


class MemoryR2:
    def __init__(self):
        self.objects = {}

    async def put(self, key, body, **kwargs):
        self.objects[key] = bytes(body)

    async def get(self, key):
        payload = self.objects.get(key)
        return None if payload is None else _Object(payload)

    async def delete(self, key):
        self.objects.pop(key, None)


class StubHistory:
    async def get_user(self, user_id):
        return SimpleNamespace(id=user_id)


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=BASE,
        google_client_id="phase7955.apps.googleusercontent.com",
        google_client_secret="unit-test-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
        web_provider="off",
    )


async def _client(*, user_id=OWNER, signed_in=True):
    cfg = _settings()
    app = create_app(cfg, history_store=StubHistory(), d1_binding=FakeD1())
    app.state.workspace_document_store = SimpleNamespace(r2_bucket=MemoryR2())
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE,
        follow_redirects=True, headers={"Origin": BASE},
    )
    if signed_in:
        profile = SimpleNamespace(id=user_id, email=f"{user_id}@example.test")
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(cfg, profile.id, canonical_session_id="session_test_a"),
            domain="chat.example.test", path="/",
        )
    return client, app


async def _open_job(client):
    response = await client.post("/api/document-conversions", json={"mode": "fast"})
    assert response.status_code == 201, response.text
    return response.json()["job"]["id"]


async def _upload(client, job_id, payload, *, name):
    return await client.post(
        f"/api/document-conversions/{job_id}/files",
        content=payload,
        headers={
            "Content-Type": "application/octet-stream",
            "X-Padiem-Filename": quote(name, safe=""),
            "X-Padiem-Media-Type": PDF_MEDIA,
        },
    )


def test_the_route_serves_an_owner_scoped_jpeg() -> None:
    async def journey():
        client, _app = await _client()
        try:
            job_id = await _open_job(client)
            created = await _upload(client, job_id, _pdf(["one", "two"]), name="원본.pdf")
            assert created.status_code == 201, created.text
            item_id = created.json()["items"][0]["id"]
            first = await client.get(f"/api/document-conversions/items/{item_id}/original/1.jpeg")
            second = await client.get(f"/api/document-conversions/items/{item_id}/original/2.jpeg")
            beyond = await client.get(f"/api/document-conversions/items/{item_id}/original/3.jpeg")
            return item_id, first, second, beyond
        finally:
            await client.aclose()

    _item_id, first, second, beyond = asyncio.run(journey())

    assert first.status_code == 200, first.text
    assert first.headers["content-type"] == "image/jpeg"
    assert first.headers["cache-control"] == "private, no-store"
    assert first.content.startswith(JPEG_MAGIC)
    assert second.status_code == 200 and second.content != first.content
    assert beyond.status_code == 404


def test_another_owner_and_a_guest_cannot_read_the_page() -> None:
    async def journey():
        owner, _app = await _client()
        try:
            job_id = await _open_job(owner)
            created = await _upload(owner, job_id, _pdf(["private"]), name="비공개.pdf")
            item_id = created.json()["items"][0]["id"]
        finally:
            await owner.aclose()
        intruder, _ = await _client(user_id=INTRUDER)
        guest, _ = await _client(signed_in=False)
        try:
            other = await intruder.get(f"/api/document-conversions/items/{item_id}/original/1.jpeg")
            anonymous = await guest.get(f"/api/document-conversions/items/{item_id}/original/1.jpeg")
            return other, anonymous
        finally:
            await intruder.aclose()
            await guest.aclose()

    other, anonymous = asyncio.run(journey())

    assert other.status_code == 404
    assert anonymous.status_code in (401, 403)


def test_a_missing_renderer_falls_back_to_a_404(monkeypatch) -> None:
    """No renderer installed -> a failed request, never a broken image."""

    import app.document_page_render as renderer

    def unavailable(*_args, **_kwargs):
        raise PageRenderUnavailable("renderer missing")

    monkeypatch.setattr(renderer, "render_page_jpeg", unavailable)
    import app.document_convert_page_image as route

    monkeypatch.setattr(route, "render_page_jpeg", unavailable)

    async def journey():
        client, _app = await _client()
        try:
            job_id = await _open_job(client)
            created = await _upload(client, job_id, _pdf(["one"]), name="원본.pdf")
            item_id = created.json()["items"][0]["id"]
            return await client.get(f"/api/document-conversions/items/{item_id}/original/1.jpeg")
        finally:
            await client.aclose()

    response = asyncio.run(journey())
    assert response.status_code == 404


# --------------------------------------------------------------------------
# 실제 브라우저: 비교 칸에 그림이 보이고, 못 만들면 안내로 돌아간다
# --------------------------------------------------------------------------

_STAMP = "2026-11-19T09:00:00Z"
_JPEG = render_page(_pdf(["page one"]), 1, long_edge_px=400).jpeg
_BAND_HTML = """<!DOCTYPE html>
<html lang="ko" data-theme="padiem-home"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="./padiem-themes.css">
<link rel="stylesheet" href="./sidebar-utility.css">
<link rel="stylesheet" href="./standalone-views.css">
<link rel="stylesheet" href="./util-menu.css">
<link rel="stylesheet" href="./util-app.css">
<link rel="stylesheet" href="./util-chat-mode.css">
</head><body>
<main class="util-view" id="utilView" style="display:block">
<div class="util-app-root" id="utilAppRoot"></div>
</main>
<script>window.PadiemAuthSession = { get: function () { return { authenticated: true }; } };</script>
<script src="./util-manifest.js"></script>
<script src="./util-chat-mode.js"></script>
<script src="./util-pdfmd-pages.js"></script>
<script src="./util-pdfmd.js"></script>
<script>
  const panel = document.createElement("div");
  panel.id = "utilPdfmdPanel";
  panel.className = "util-panel";
  const body = document.createElement("div");
  body.className = "util-tool-body";
  body.appendChild(panel);
  document.getElementById("utilAppRoot").appendChild(body);
  window.initPdfMdUtility(panel, "open");
</script>
</body></html>"""


class _BandHandler(http.server.SimpleHTTPRequestHandler):
    broken = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *_args):
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
        if path == "/api/pc/pairings":
            self._json({"links": [{"link_id": "l1", "state": "active"}]})
            return
        if path == "/api/document-conversions":
            self._json({"jobs": [{"id": "job_page", "mode": "fast", "status": "done",
                                  "item_count": 1, "created_at": _STAMP,
                                  "updated_at": _STAMP}],
                        "limit": 50, "new_work_enabled": True})
            return
        if path == "/api/document-conversions/job_page":
            self._json({"job": {"id": "job_page", "mode": "fast", "status": "done",
                                "item_count": 1, "created_at": _STAMP, "updated_at": _STAMP},
                        "items": [{"id": "item_page", "name": "원본.pdf",
                                   "status": "done", "page_count": 1,
                                   "character_count": 12, "has_markdown": True,
                                   "has_original": True, "report": None,
                                   "error_code": None}]})
            return
        if path.endswith("/items/item_page/markdown"):
            body = "<!-- padiem:page 1 -->\nAnthropic page text\n".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.endswith(".jpeg"):
            if _BandHandler.broken:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(_JPEG)))
            self.end_headers()
            self.wfile.write(_JPEG)
            return
        if path.startswith("/api/"):
            self._json({})
            return
        super().do_GET()

    def do_POST(self):  # noqa: N802
        self._json({"ok": True})


@pytest.fixture()
def band_url():
    _BandHandler.broken = False
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _BandHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d/index.html" % server.server_port
    server.shutdown()


def _open_compare(page, url):
    page.route("**/index.html", lambda route: route.fulfill(
        status=200, headers={"content-type": "text/html; charset=utf-8"},
        body=_BAND_HTML))
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector(".pdfmd-history-fold summary", state="visible", timeout=8000)
    page.locator(".pdfmd-history-fold summary").click()
    page.locator(".pdfmd-history-item").first.click()
    page.wait_for_selector(".pdfmd-item", state="visible", timeout=8000)
    page.locator(".pdfmd-item-actions button", has_text="비교").first.click()
    page.wait_for_selector(".pdfmd-preview:not([hidden])", state="visible", timeout=8000)


@pytest.mark.skipif(sync_playwright is None or not CHROME,
                    reason="playwright or Chrome is not installed")
def test_the_compare_pane_shows_the_rendered_page(band_url) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            _open_compare(page, band_url)
            page.wait_for_function(
                "() => { const img = document.querySelector('.pdfmd-original-page');"
                "return img && img.complete && img.naturalWidth > 0; }",
                timeout=8000,
            )
            shape = page.evaluate(
                "() => { const img = document.querySelector('.pdfmd-original-page');"
                "return { src: img.getAttribute('src'), w: img.naturalWidth,"
                " h: img.naturalHeight, hidden: img.hidden,"
                " notice: document.querySelector('.pdfmd-pane .pdfmd-warn').hidden }; }"
            )
        finally:
            browser.close()

    assert shape["src"].endswith("/original/1.jpeg")
    assert (shape["w"], shape["h"]) == (310, 400)
    assert shape["hidden"] is False
    assert shape["notice"] is True


@pytest.mark.skipif(sync_playwright is None or not CHROME,
                    reason="playwright or Chrome is not installed")
def test_a_failed_render_shows_the_notice_and_open_button(band_url) -> None:
    _BandHandler.broken = True
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            _open_compare(page, band_url)
            page.wait_for_function(
                "() => { const n = document.querySelector('.pdfmd-pane .pdfmd-warn');"
                "return n && !n.hidden; }",
                timeout=8000,
            )
            fallback = page.evaluate(
                "() => ({ hidden: document.querySelector('.pdfmd-original-page').hidden,"
                " notice: document.querySelector('.pdfmd-pane .pdfmd-warn').textContent,"
                " button: document.querySelector('.pdfmd-pane .pdfmd-btn').textContent })"
            )
        finally:
            browser.close()

    assert fallback["hidden"] is True
    assert fallback["notice"]
    assert fallback["button"] == "원본 PDF 열기"
