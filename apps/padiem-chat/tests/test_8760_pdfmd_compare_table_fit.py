"""#8760: a page-1 table in the PDF->MD compare view stays readable in the pane.

The Markdown pane (변환본) is about 343px wide at 1440 and narrower with the
sidebar open. The page-1 table was drawn at its natural 1,289px width with
``white-space: nowrap`` cells, so the reader had to scroll sideways inside the
whole pane. Squeezing it into the pane width (a previous attempt) broke words
into single characters instead, which is also unreadable.

The table now (a) keeps word units with ``word-break: keep-all`` so no column
breaks a word, (b) is at least the pane width, and (c) when wider than the
pane scrolls sideways inside its own focusable box with a scrollbar that is
always shown, not the whole pane.
At 1440 and 1280 in all three checked themes: no word is broken across lines,
every column is at least 30px wide, and the pane itself never scrolls sideways.

Browser-level because the failure is a layout fact. The page is served from
``static/`` and every ``/api`` call is answered by the test, so no account,
document or database is involved. Set ``PADIEM_8760_BASE_URL`` to measure a
server that is already running (for example a static server on port 4427).
"""
from __future__ import annotations

import io
import json
import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

# Core pytest runners intentionally do not install Playwright. Skip this
# optional browser suite there instead of aborting collection.
try:
    from playwright.sync_api import Page, Route, sync_playwright
except ImportError:
    Page = Route = object  # type: ignore[assignment,misc]
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
CAPTURE_DIR = os.environ.get("PADIEM_8760_CAPTURE_DIR", "")

JOB_ID = "dcj87600000000000000000000000000a1"
ITEM_ID = "dci8760aaaaaaaaaaaaaaaaaaaaaaaaaaaa"

# The page-1 table is deliberately wide: seven columns of ordinary contract
# wording, the shape a 1쪽 summary table takes in a real PDF.
PAGE_ONE_TABLE = "\n".join([
    "| 구분 | 항목 | 내용 | 금액(부가세 포함) | 지급 기한 | 담당 부서 | 비고 |",
    "|---|---|---|---|---|---|---|",
    "| 1 | 용역 대금 | 시스템 구축 및 3개월 운영 지원 | 143,000,000원 | 검수 완료 후 30일 이내 | 사업지원팀 | 선금 30% 별도 |",
    "| 2 | 유지보수비 | 연 단위 정기 점검과 장애 대응 | 26,400,000원 | 매 분기 말일 | 운영팀 | 계약 기간 중 월할 정산 |",
    "| 3 | 지체상금 | 납기 지연 1일당 계약금액의 0.1% | 해당 없음 | 지연 발생 시 | 법무팀 | 상한 10% |",
])

MARKDOWN = (
    "<!-- padiem:page 1 -->\n\n## 1쪽 계약 조건\n\n"
    + PAGE_ONE_TABLE + "\n\n"
    + "\n".join(f"- 1쪽 {i}항: 당사자는 본 조항에 동의한다." for i in range(1, 4)) + "\n"
    + "\n<!-- padiem:page 2 -->\n\n## 2쪽 조항\n\n"
    + "\n".join(f"- 2쪽 {i}항: 당사자는 본 조항에 동의한다." for i in range(1, 4)) + "\n"
)

ITEM_BODY = {
    "id": ITEM_ID,
    "job_id": JOB_ID,
    "name": "계약서.pdf",
    "status": "reviewed",
    "page_count": 2,
    "character_count": len(MARKDOWN),
    "has_markdown": True,
    "has_original": True,
    "error_code": None,
    "report": {"pages": [{"number": n, "native_text_present": True} for n in (1, 2)]},
}

JOB = {
    "id": JOB_ID, "mode": "fast", "status": "reviewed", "item_count": 1,
    "created_at": "2026-11-25T01:00:00Z", "updated_at": "2026-11-25T01:00:00Z",
    "items": [ITEM_BODY],
}

THEMES = ("padiem-glass", "light", "dark")
WIDTHS = (1440, 1280)


class _Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


@pytest.fixture(scope="module")
def base_url():
    external = os.environ.get("PADIEM_8760_BASE_URL", "").rstrip("/")
    if external:
        yield external
        return
    handler = partial(_Handler, directory=str(STATIC))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _page_jpeg(page_number: int) -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (612, 792), "white")
    ImageDraw.Draw(image).text((60, 60), f"ORIGINAL PAGE {page_number}", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()


def _json(route: Route, body: dict) -> None:
    route.fulfill(status=200, body=json.dumps(body, ensure_ascii=False),
                  headers={"content-type": "application/json"})


def _route(route: Route) -> None:
    url = urlparse(route.request.url)
    path = url.path
    if not path.startswith("/api/"):
        route.continue_()
        return
    if path.endswith(".jpeg") and "/original/" in path:
        number = int(path.rsplit("/", 1)[-1].split(".")[0])
        route.fulfill(status=200, body=_page_jpeg(number), headers={"content-type": "image/jpeg"})
        return
    if path == "/api/document-conversions":
        _json(route, {"new_work_enabled": True, "limit": 50, "jobs": [JOB]})
        return
    if path.endswith("/markdown"):
        route.fulfill(status=200, body=MARKDOWN,
                      headers={"content-type": "text/markdown; charset=utf-8"})
        return
    if path.endswith("/original"):
        route.fulfill(status=200, body=b"%PDF-1.4\n", headers={"content-type": "application/pdf"})
        return
    if path == f"/api/document-conversions/items/{ITEM_ID}":
        _json(route, {"item": ITEM_BODY})
        return
    if path == f"/api/document-conversions/{JOB_ID}":
        _json(route, {"job": JOB, "items": [ITEM_BODY]})
        return
    _json(route, {"ok": True, "authenticated": False, "ready": True})


def _open_compare(page: Page, base_url: str, theme: str) -> None:
    page.goto(f"{base_url}/?theme={theme}#util/pdfmd", wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(2000)
    fold = page.locator(".pdfmd-history-fold")
    fold.locator("summary").wait_for(state="visible", timeout=8_000)
    if not fold.evaluate("(el) => el.open"):
        fold.locator("summary").click()
    page.locator(".pdfmd-history-item").first.click()
    page.wait_for_timeout(800)
    page.locator('button[aria-label$="원본과 변환본 비교"]').first.click()
    page.locator(".pdfmd-preview").wait_for(state="visible", timeout=8_000)
    page.locator(".pdfmd-page-table").first.wait_for(state="attached", timeout=8_000)
    page.wait_for_timeout(600)


# Pane scroll, the table's own scroll box, column widths, and whether any
# cell is narrower than its longest word (a word broken across lines).
_MEASURE = r"""() => {
  const pane = document.querySelector('.pdfmd-md');
  const table = pane.querySelector('.pdfmd-page-table');
  const scroll = pane.querySelector('.pdfmd-table-scroll');
  const firstRow = table.querySelector('tr');
  const cols = firstRow ? [...firstRow.children].map(c => c.getBoundingClientRect().width) : [];
  const probe = document.createElement('span');
  probe.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap;';
  document.body.appendChild(probe);
  let broken = null;
  for (const cell of table.querySelectorAll('th, td')) {
    const st = getComputedStyle(cell);
    probe.style.font = st.font;
    let widest = 0;
    for (const word of cell.textContent.trim().split(/\s+/)) {
      probe.textContent = word;
      widest = Math.max(widest, probe.getBoundingClientRect().width);
    }
    const avail = cell.clientWidth - parseFloat(st.paddingLeft) - parseFloat(st.paddingRight);
    if (avail + 0.5 < widest) { broken = {text: cell.textContent, avail: avail, widest: widest}; break; }
  }
  probe.remove();
  return {
    paneScroll: pane.scrollWidth - pane.clientWidth,
    scrollOverflowX: scroll ? getComputedStyle(scroll).overflowX : 'absent',
    scrollTab: scroll ? scroll.tabIndex : null,
    scrollSlack: scroll ? scroll.scrollWidth - scroll.clientWidth : null,
    minCol: cols.length ? Math.min(...cols) : null,
    broken: broken,
  };
}"""


@pytest.mark.skipif(sync_playwright is None, reason="playwright not installed")
@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("theme", THEMES)
def test_page_one_table_readable_in_the_markdown_pane(base_url: str, theme: str, width: int) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": 950})
            page.route("**/*", _route)
            _open_compare(page, base_url, theme)
            m = page.evaluate(_MEASURE)
            if CAPTURE_DIR:
                out = Path(CAPTURE_DIR)
                out.mkdir(parents=True, exist_ok=True)
                page.locator(".pdfmd-preview").screenshot(path=str(out / f"compare-{theme}-{width}.png"))
        finally:
            browser.close()

    assert m["paneScroll"] <= 0.5, f"the pane itself scrolls sideways: {m}"
    assert m["scrollOverflowX"] == "scroll", f"wide table has no always-visible scroll box of its own: {m}"
    assert m["scrollTab"] == 0, f"table scroll box is not keyboard-focusable: {m}"
    assert m["broken"] is None, f"a word is broken across lines: {m}"
    assert m["minCol"] >= 30, f"a column is narrower than 30px: {m}"
