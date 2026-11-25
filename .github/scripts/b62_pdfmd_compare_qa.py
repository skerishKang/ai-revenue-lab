"""#7834 PDF→MD compare screen: page controls, original page image, states.

The screen is driven against the mock Chat host and every ledger answer is
intercepted, so this run never touches an account, a stored document or a
database. Three things are observed through the DOM the owner sees:

* the page controls move the view: the number field, the Markdown pane's own
  scroll request, and the original page image that is actually loaded
  (``naturalWidth > 0``, and its URL names the page that was asked for);
* a scanned PDF arrives as a failed item with the plain-language reason, and
  never shows the "변환 완료" line or the 검토중 chip;
* an item that never finished arrives as a timed-out failure, not 준비중.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw
from playwright.async_api import async_playwright

BASE_URL = os.environ.get("B62_A11Y_QA_BASE_URL", "http://127.0.0.1:8734").rstrip("/")
OUT_DIR = Path(os.environ.get("B62_A11Y_QA_OUT_DIR", ".tmp/b62-pdfmd-compare-qa"))
API = re.compile(r".*/api/document-conversions.*")

JOB_ID = "dcj78340000000000000000000000000000"
TEXT_ITEM = "dci7834aaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SCAN_ITEM = "dci7834bbbbbbbbbbbbbbbbbbbbbbbbbbbb"
STALE_ITEM = "dci7834cccccccccccccccccccccccccccc"
REVIEWED_JOB = "dcj78340000000000000000000000000a1"
SCAN_JOB = "dcj78340000000000000000000000000b1"
STALE_JOB = "dcj78340000000000000000000000000c1"

SCAN_SENTENCE = "스캔본이라 글자가 없어 지금은 읽을 수 없습니다."
STALE_SENTENCE = "시간이 오래 걸려 변환이 끝나지 않았습니다."
DONE_SENTENCE = "변환 완료 — 원본과 변환본을 비교해 보세요."

MARKDOWN = "\n".join(
    f"<!-- padiem:page {n} -->\n\n## {n}쪽 조항\n\n"
    + "\n".join(f"- {n}쪽 {i}항: 당사자는 본 조항에 동의한다." for i in range(1, 6))
    for n in range(1, 6)
) + "\n"

TEXT_ITEM_BODY = {
    "id": TEXT_ITEM,
    "job_id": REVIEWED_JOB,
    "name": "계약서.pdf",
    "status": "reviewed",
    "page_count": 5,
    "character_count": len(MARKDOWN),
    "has_markdown": True,
    "has_original": True,
    "error_code": None,
    "report": {"pages": [{"number": n, "native_text_present": True} for n in range(1, 6)]},
}

SCAN_ITEM_BODY = {
    "id": SCAN_ITEM,
    "job_id": SCAN_JOB,
    "name": "스캔계약서.pdf",
    "status": "failed",
    "page_count": 5,
    "character_count": 0,
    "has_markdown": False,
    "has_original": True,
    "error_code": "pdf_scanned_no_text",
    "report": None,
}

STALE_ITEM_BODY = {
    "id": STALE_ITEM,
    "job_id": STALE_JOB,
    "name": "오래된작업.pdf",
    "status": "failed",
    "page_count": 0,
    "character_count": 0,
    "has_markdown": False,
    "has_original": True,
    "error_code": "convert_timed_out",
    "report": None,
}


def _page_jpeg(page: int) -> bytes:
    image = Image.new("RGB", (840, 1188), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([20, 20, 820, 1168], outline="black", width=3)
    draw.text((70, 90), f"ORIGINAL PAGE {page}", fill="black")
    for line in range(12):
        draw.text((70, 200 + line * 70), f"p{page} clause {line + 1}", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()


def _jobs() -> list[dict]:
    return [
        {"id": REVIEWED_JOB, "mode": "fast", "status": "reviewed", "item_count": 1,
         "created_at": "2026-11-16T01:00:00Z", "updated_at": "2026-11-16T01:00:00Z",
         "items": [TEXT_ITEM_BODY]},
        {"id": SCAN_JOB, "mode": "fast", "status": "failed", "item_count": 1,
         "created_at": "2026-11-16T00:30:00Z", "updated_at": "2026-11-16T00:30:00Z",
         "items": [SCAN_ITEM_BODY]},
        {"id": STALE_JOB, "mode": "fast", "status": "failed", "item_count": 1,
         "created_at": "2026-11-15T20:00:00Z", "updated_at": "2026-11-15T20:00:00Z",
         "items": [STALE_ITEM_BODY]},
    ]


def _items_by_job(job_id: str) -> list[dict]:
    for job in _jobs():
        if job["id"] == job_id:
            return job["items"]
    return []


async def _route(route) -> None:
    url = urlparse(route.request.url)
    path = url.path
    if path.endswith(".jpeg") and "/original/" in path:
        page = int(path.rsplit("/", 1)[-1].split(".")[0])
        await route.fulfill(status=200, body=_page_jpeg(page),
                            headers={"content-type": "image/jpeg"})
        return
    if path == "/api/document-conversions":
        await route.fulfill(status=200, body=json.dumps({
            "new_work_enabled": True, "limit": 50, "jobs": _jobs(),
        }, ensure_ascii=False), headers={"content-type": "application/json"})
        return
    item_id = path.rsplit("/", 1)[-1]
    if "/markdown" in path:
        await route.fulfill(status=200, body=MARKDOWN,
                            headers={"content-type": "text/markdown; charset=utf-8"})
        return
    if path.endswith("/original"):
        await route.fulfill(status=200, body=b"%PDF-1.4\n",
                            headers={"content-type": "application/pdf"})
        return
    for item in (TEXT_ITEM_BODY, SCAN_ITEM_BODY, STALE_ITEM_BODY):
        if item["id"] == item_id:
            await route.fulfill(status=200, body=json.dumps(
                {"item": item, "job": {"id": item["job_id"], "mode": "fast",
                                       "status": item["status"], "item_count": 1}},
                ensure_ascii=False), headers={"content-type": "application/json"})
            return
    if path.startswith("/api/document-conversions/"):
        job_id = path.rsplit("/", 1)[-1]
        await route.fulfill(status=200, body=json.dumps(
            {"job": {"id": job_id, "mode": "fast", "status": "reviewed", "item_count": 1},
             "items": _items_by_job(job_id)}, ensure_ascii=False),
            headers={"content-type": "application/json"})
        return
    await route.continue_()


async def _expand_history(page) -> None:
    fold = page.locator(".pdfmd-history-fold")
    summary = fold.locator("summary")
    await summary.wait_for(state="visible", timeout=8_000)
    if not await fold.evaluate("(el) => el.open"):
        await summary.click()
    await page.locator(".pdfmd-history-item").first.wait_for(state="visible", timeout=8_000)


async def _open_compare(page) -> None:
    await page.goto(BASE_URL + "/?theme=padiem-glass#util/pdfmd",
                    wait_until="domcontentloaded", timeout=90_000)
    await page.wait_for_timeout(2500)
    await _expand_history(page)
    await page.locator(".pdfmd-history-item").first.click()
    await page.wait_for_timeout(1200)
    await page.locator('button[aria-label$="원본과 변환본 비교"]').first.click()
    await page.locator(".pdfmd-preview").wait_for(state="visible", timeout=8_000)
    await page.wait_for_timeout(1500)


async def _read(page) -> dict:
    return await page.evaluate("""() => {
      const input = document.querySelector('.pdfmd-page-input');
      const img = document.querySelector('.pdfmd-original-page');
      const pane = document.querySelector('.pdfmd-md');
      return {
        input: input ? input.value : null,
        total: (document.querySelector('.pdfmd-page-total') || {}).textContent || '',
        image_src: img ? (img.getAttribute('src') || '') : null,
        image_natural_width: img ? img.naturalWidth : null,
        image_hidden: img ? img.hidden : null,
        pane_scroll_top: pane ? pane.scrollTop : null,
        first_visible_page: (() => {
          if (!pane) return null;
          const top = pane.getBoundingClientRect().top;
          let first = null;
          pane.querySelectorAll('.pdfmd-page').forEach((block) => {
            const box = block.getBoundingClientRect();
            if (first === null && box.bottom - top > 4) first = Number(block.dataset.page);
          });
          return first;
        })(),
        visible_pages: (() => {
          if (!pane) return [];
          const bounds = pane.getBoundingClientRect();
          return [...pane.querySelectorAll('.pdfmd-page')].filter((block) => {
            const box = block.getBoundingClientRect();
            return box.bottom - bounds.top > 4 && box.top - bounds.top < bounds.height - 4;
          }).map((block) => Number(block.dataset.page));
        })(),
        status_lines: Array.from(document.querySelectorAll('.pdfmd-item .pdfmd-stage')).map((n) => n.textContent),
        chips: Array.from(document.querySelectorAll('.pdfmd-item .pdfmd-status-chip')).map((n) => n.textContent),
        item_text: Array.from(document.querySelectorAll('.pdfmd-item')).map((n) => n.textContent).join(' | '),
      };
    }""")


def _check(problems: list[str], label: str, ok: bool, detail) -> None:
    if not ok:
        problems.append(f"{label}: {detail}")


async def _paging(page, problems: list[str], report: dict) -> None:
    seen = []
    state = await _read(page)
    seen.append(state)
    _check(problems, "open page number", state["input"] == "1", state)
    _check(problems, "open page total", state["total"].strip() == "/ 5", state["total"])
    _check(problems, "open original image", (state["image_natural_width"] or 0) > 0, state)
    _check(problems, "open image page", (state["image_src"] or "").endswith("/original/1.jpeg"), state["image_src"])

    for expected in (2, 3, 4, 5):
        await page.locator('.pdfmd-page-controls button[aria-label="다음 페이지"]').click()
        await page.wait_for_timeout(900)
        state = await _read(page)
        seen.append(state)
        _check(problems, f"next to {expected} number", state["input"] == str(expected), state["input"])
        _check(problems, f"next to {expected} image",
               (state["image_src"] or "").endswith(f"/original/{expected}.jpeg")
               and (state["image_natural_width"] or 0) > 0, state)
        _check(problems, f"next to {expected} pane", expected in state["visible_pages"], state)
    _check(problems, "last page keeps its number", seen[-1]["input"] == "5", seen[-1]["input"])

    await page.fill(".pdfmd-page-input", "7")
    await page.press(".pdfmd-page-input", "Enter")
    await page.wait_for_timeout(700)
    state = await _read(page)
    seen.append(state)
    _check(problems, "typed 7 clamps to 5", state["input"] == "5", state["input"])

    await page.fill(".pdfmd-page-input", "2")
    await page.press(".pdfmd-page-input", "Enter")
    await page.wait_for_timeout(900)
    state = await _read(page)
    seen.append(state)
    _check(problems, "typed 2 number", state["input"] == "2", state["input"])
    _check(problems, "typed 2 pane", state["first_visible_page"] == 2 and 2 in state["visible_pages"], state)
    _check(problems, "typed 2 image",
           (state["image_src"] or "").endswith("/original/2.jpeg")
           and (state["image_natural_width"] or 0) > 0, state)

    await page.locator('.pdfmd-page-controls button[aria-label="이전 페이지"]').click()
    await page.wait_for_timeout(900)
    state = await _read(page)
    seen.append(state)
    _check(problems, "previous returns to 1", state["input"] == "1", state["input"])
    _check(problems, "previous image", (state["image_src"] or "").endswith("/original/1.jpeg"), state["image_src"])
    _check(problems, "completed item keeps its done badge",
           "완료" in state["chips"], state["chips"])
    await page.locator(".pdfmd-preview").scroll_into_view_if_needed()
    await page.wait_for_timeout(400)
    await page.locator(".pdfmd-preview").screenshot(path=str(OUT_DIR / "pdfmd-compare.png"))
    report["paging"] = seen


async def _states(page, problems: list[str], report: dict) -> None:
    rows = []
    for index, job_id in enumerate((REVIEWED_JOB, SCAN_JOB, STALE_JOB)):
        await _expand_history(page)
        await page.locator(f'.pdfmd-history-item[data-job-id="{job_id}"]').click()
        await page.wait_for_timeout(1200)
        state = await _read(page)
        rows.append({"job": job_id, "chips": state["chips"], "status_lines": state["status_lines"],
                     "item_text": state["item_text"]})
    report["states"] = rows

    scan = rows[1]
    _check(problems, "scan chip", "실패" in scan["chips"], scan["chips"])
    _check(problems, "scan reason", SCAN_SENTENCE in scan["item_text"], scan["item_text"])
    _check(problems, "scan has no done line",
           not any(DONE_SENTENCE in line for line in scan["status_lines"]), scan["status_lines"])
    _check(problems, "scan has no review chip", "검토중" not in scan["chips"], scan["chips"])

    stale = rows[2]
    _check(problems, "stale chip", "시간 초과" in stale["chips"], stale["chips"])
    _check(problems, "stale reason", STALE_SENTENCE in stale["item_text"], stale["item_text"])
    _check(problems, "stale is not 준비중", "준비중" not in stale["chips"], stale["chips"])


async def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    report: dict = {"base_url": BASE_URL, "problems": problems}
    async with async_playwright() as play:
        browser = await play.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 950})
        await page.route(API, _route)
        try:
            await _open_compare(page)
            await _paging(page, problems, report)
            await _states(page, problems, report)
            await page.screenshot(path=str(OUT_DIR / "pdfmd-compare-states.png"), full_page=True)
        finally:
            await browser.close()
    report["ok"] = not problems
    (OUT_DIR / "pdfmd-compare-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps({"ok": report["ok"], "problems": problems}, ensure_ascii=False, indent=1))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))