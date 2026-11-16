"""#7834 PDF→MD compare view: paging, the original page, and honest states.

Three production complaints were reproduced locally on a five-page PDF:

1. The page controls did not move the view. Two independent causes:
   * the page number was read back out of the Markdown pane's scroll
     position, and the last page of a document cannot be scrolled to the
     top — so the pane reported the page before it and the number it printed
     overwrote the number the owner had just asked for;
   * the original pane was a same-origin ``<iframe>`` of the PDF. It was
     empty because the browser refused the frame and because an inline PDF
     viewer is not something a page can count on.
   The pane now shows one server-rendered image of the page being compared,
   and a page chosen by a control is not overruled by scroll geometry.
2. A scanned PDF reached the review state and showed "변환 완료 — 원본과
   변환본을 비교해 보세요" over a comparison with no words. A PDF whose pages
   carry no text layer is now recorded as a failure, with the reason, and the
   job rolls up to failed through the same path every other failure uses.
3. An unfinished job stayed 준비중 forever. A row that never reached a
   terminal state within ``ABANDONED_AFTER_SECONDS`` is read as a timed-out
   failure. The judgement happens on read, so no stored row is rewritten and
   no migration is involved.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_5568_document_convert_routes import (
    build_client,
    open_job,
    pdf_bytes,
    run_item,
    upload,
    wait_item_terminal,
)

from app.document_convert_store import (
    ABANDONED_AFTER_SECONDS,
    ABANDONED_ERROR_CODE,
    ConvertItemRecord,
    ConvertJobRecord,
    abandoned_row,
)

ROOT = Path(__file__).resolve().parents[1]
PDFMD_JS = ROOT / "static/util-pdfmd.js"
PDFMD_PAGES_JS = ROOT / "static/util-pdfmd-pages.js"
UTIL_MENU_CSS = ROOT / "static/util-menu.css"
JPEG_MAGIC = b"\xff\xd8\xff"


# --------------------------------------------------------------------------
# page controls: the unit half of "5쪽 페이지 이동" (the browser half is
# .github/scripts/b62_pdfmd_compare_qa.py)
# --------------------------------------------------------------------------

_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");

const pagesSource = fs.readFileSync(process.argv[2], "utf8");
const moduleSource = fs.readFileSync(process.argv[3], "utf8");
const context = { window: {} };
vm.runInNewContext(pagesSource, context);
vm.runInNewContext(moduleSource, context);
const map = context.window.PadiemPdfMdPageMap;

const tops = [
  { page: 1, top: 0 },
  { page: 2, top: 443 },
  { page: 3, top: 879 },
  { page: 4, top: 1330 },
  { page: 5, top: 1624 },
];
// The last page of a five-page document, once the pane is scrolled as far as
// it goes: page five starts 138px below the top edge and cannot be lifted.
const clamped = [
  { page: 1, top: -1624 },
  { page: 2, top: -1181 },
  { page: 3, top: -745 },
  { page: 4, top: -294 },
  { page: 5, top: 138 },
];

console.log(JSON.stringify({
  ok: true,
  targets: [1, 2, 5, 7, 0, "", "3.4", "5"].map((value) => map.pageTarget(value, 5)),
  scrolled: [0, 443, 879, 1330].map((top) => map.pageForScroll(tops, top, 24, false)),
  clampedMiddle: map.pageForScroll(clamped, 0, 24, false),
  clampedEnd: map.pageForScroll(clamped, 0, 24, true),
  emptyRows: map.pageForScroll([], 0, 24, true),
}));
"""


def _run_page_map() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the util-pdfmd page-control harness"
    harness = ROOT / "tests" / "_7834_pdfmd_page_map.js"
    harness.write_text(_HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness), str(PDFMD_PAGES_JS), str(PDFMD_JS)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ},
            timeout=60,
            cwd=str(ROOT),
        )
    finally:
        harness.unlink(missing_ok=True)
    stdout = result.stdout.strip()
    assert result.returncode == 0 and stdout, f"harness crashed: stdout={stdout!r} stderr={result.stderr!r}"
    payload = json.loads(stdout.splitlines()[-1])
    assert payload.get("ok"), payload
    return payload


def test_page_controls_clamp_to_the_document() -> None:
    payload = _run_page_map()
    assert payload["targets"] == [1, 2, 5, 5, 1, 1, 3, 5]


def test_a_scrolled_page_is_the_page_whose_top_passed_the_pane_top() -> None:
    payload = _run_page_map()
    assert payload["scrolled"] == [1, 2, 3, 4]
    # The clamped reading of the last page is the page before it — the exact
    # value that used to overwrite the number the owner asked for.
    assert payload["clampedMiddle"] == 4
    # At the end of the pane the answer is the last page, so the number and the
    # original page image stay on the page that was actually reached.
    assert payload["clampedEnd"] == 5
    assert payload["emptyRows"] is None


def test_a_control_choice_outranks_the_scroll_position() -> None:
    source = PDFMD_JS.read_text(encoding="utf-8")
    # The controls pass `fromControl`, which opens the guard window.
    assert 'setPreviewPage(previewPageNumber - 1, true, true)' in source
    assert 'setPreviewPage(previewPageNumber + 1, true, true)' in source
    assert 'setPreviewPage(pageInput.value, true, true)' in source
    assert "previewPageUntil = Date.now() + PREVIEW_PAGE_GUARD_MS;" in source
    # The scroll listener refuses to read a page back while that window is open.
    assert "if (Date.now() < previewPageUntil) return;" in source
    # Typing a page is not interrupted by the pane moving under it.
    assert "if (document.activeElement === pageInput) return;" in source
    # Enter commits the typed page; `change` alone waits for a blur.
    assert 'if (event.key !== "Enter") return;' in source


def test_the_original_pane_shows_a_rendered_page_image() -> None:
    pages = PDFMD_PAGES_JS.read_text(encoding="utf-8")
    assert 'image.className = "pdfmd-original-page";' in pages
    assert 'itemUrl(item, "/original/" + number + ".jpeg")' in pages
    assert 'itemUrl(item, "/original?display=inline")' in pages
    assert "if (image.getAttribute(\"src\") === target) return;" in pages
    # A page that cannot be rendered says so instead of showing a broken image.
    assert "이 쪽의 원본을 그림으로 표시하지 못했습니다." in pages
    # No pane, anywhere, frames the PDF: that is what the browser refused.
    module = PDFMD_JS.read_text(encoding="utf-8")
    assert "iframe" not in pages.lower()
    assert "iframe" not in module.lower()
    assert "window.PadiemPdfMdOriginalPane.create(el)" in module
    css = UTIL_MENU_CSS.read_text(encoding="utf-8")
    assert ".pdfmd-original-page {" in css
    assert "object-fit: contain;" in css
    assert ".pdfmd-iframe" not in css


def test_a_failed_item_never_claims_completion() -> None:
    source = PDFMD_JS.read_text(encoding="utf-8")
    assert "pdf_scanned_no_text: SCAN_MESSAGE," in source
    assert "convert_timed_out: " in source
    # The stage lines describe work in progress and a result to review; a
    # failure has its own sentence and no completion line.
    stage_line = source[source.index("const STAGE_LINES = {"):]
    stage_line = stage_line[: stage_line.index("};")]
    assert "failed:" not in stage_line


# --------------------------------------------------------------------------
# the routes: a scan is a failure, a text PDF still reaches review
# --------------------------------------------------------------------------


@pytest.fixture()
def legacy_conversion(monkeypatch):
    """Upload and run stay testable behind the migration pause flag."""

    from app import document_convert_routes

    monkeypatch.setattr(document_convert_routes, "PDFMD_NEW_WORK_DISABLED", False)


@pytest.mark.asyncio
async def test_a_scanned_pdf_is_recorded_as_a_failure_with_its_reason(legacy_conversion) -> None:
    client, _app = await build_client()
    try:
        job_id = await open_job(client)
        created = await upload(client, job_id, pdf_bytes(texts=[""]), name="스캔.pdf")
        assert created.status_code == 201, created.text
        item = created.json()["items"][0]
        assert (await run_item(client, item["id"])).status_code == 202
        ran = await wait_item_terminal(client, item["id"])
        assert ran["status"] == "failed"
        assert ran["error_code"] == "pdf_scanned_no_text"
        assert ran["has_markdown"] is False
        # The page count survives the failure, so the card can say "(1쪽) 실패".
        assert ran["page_count"] == 1

        job = (await client.get(f"/api/document-conversions/{job_id}")).json()
        assert job["job"]["status"] == "failed"
        # Nothing was stored, so there is no result to compare against.
        assert (await client.get(
            f"/api/document-conversions/items/{item['id']}/markdown"
        )).status_code == 404
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_a_text_pdf_still_reaches_review(legacy_conversion) -> None:
    client, _app = await build_client()
    try:
        job_id = await open_job(client)
        payload = pdf_bytes(texts=[f"Contract page {n}" for n in range(1, 6)])
        created = await upload(client, job_id, payload, name="계약서.pdf")
        assert created.status_code == 201, created.text
        item = created.json()["items"][0]
        assert (await run_item(client, item["id"])).status_code == 202
        ran = await wait_item_terminal(client, item["id"])
        assert ran["status"] == "reviewed"
        assert ran["error_code"] is None
        assert ran["page_count"] == 5
        assert ran["has_markdown"] is True

        job = (await client.get(f"/api/document-conversions/{job_id}")).json()
        assert job["job"]["status"] == "reviewed"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_every_page_of_the_original_can_be_rendered_for_comparison(legacy_conversion) -> None:
    client, _app = await build_client()
    try:
        job_id = await open_job(client)
        payload = pdf_bytes(texts=[f"Contract page {n}" for n in range(1, 6)])
        created = await upload(client, job_id, payload, name="계약서.pdf")
        item = created.json()["items"][0]
        assert (await run_item(client, item["id"])).status_code == 202
        await wait_item_terminal(client, item["id"])

        sizes = []
        for page in range(1, 6):
            response = await client.get(
                f"/api/document-conversions/items/{item['id']}/original/{page}.jpeg"
            )
            assert response.status_code == 200, response.text
            assert response.headers["content-type"] == "image/jpeg"
            assert response.headers["cache-control"] == "private, no-store"
            assert response.content.startswith(JPEG_MAGIC)
            sizes.append(len(response.content))
        assert len(set(sizes)) > 1, "each page must be its own image"

        for page in (0, 6, 999):
            response = await client.get(
                f"/api/document-conversions/items/{item['id']}/original/{page}.jpeg"
            )
            assert response.status_code == 404
    finally:
        await client.aclose()


# --------------------------------------------------------------------------
# an unfinished row is read as a timed-out failure (read time, no rewrite)
# --------------------------------------------------------------------------


def _item(status: str, age_seconds: float) -> ConvertItemRecord:
    stamp = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat().replace("+00:00", "Z")
    return ConvertItemRecord(
        id="dci7834",
        job_id="dcj7834",
        name="오래된작업.pdf",
        status=status,
        page_count=3,
        character_count=0,
        original_key="originals/old.pdf",
        markdown_key=None,
        report=None,
        error_code=None,
        created_at=stamp,
        updated_at=stamp,
    )


def test_the_abandoned_window_is_the_documented_one() -> None:
    assert ABANDONED_AFTER_SECONDS == 3600.0
    assert abandoned_row("queued", (datetime.now(timezone.utc) - timedelta(seconds=3599)).isoformat()) is False
    assert abandoned_row("working", (datetime.now(timezone.utc) - timedelta(seconds=3601)).isoformat()) is True
    # A finished row is never re-judged, and an unreadable stamp keeps the row's
    # own answer instead of inventing one.
    assert abandoned_row("reviewed", "2020-01-01T00:00:00Z") is False
    assert abandoned_row("queued", "not a timestamp") is False


def test_an_old_unfinished_item_is_presented_as_a_timed_out_failure() -> None:
    stale = _item("queued", ABANDONED_AFTER_SECONDS + 60)
    presented = stale.public_dict()
    assert presented["status"] == "failed"
    assert presented["error_code"] == ABANDONED_ERROR_CODE
    # Presentation only: the stored row keeps its own state, so nothing is
    # rewritten on a read and the next run request still knows the truth.
    assert stale.status == "queued"
    assert stale.error_code is None

    fresh = _item("working", 30)
    assert fresh.public_dict()["status"] == "working"
    assert fresh.public_dict()["error_code"] is None


def test_an_old_unfinished_job_is_presented_as_a_timed_out_failure() -> None:
    stamp = (datetime.now(timezone.utc) - timedelta(seconds=ABANDONED_AFTER_SECONDS + 60))
    stale = ConvertJobRecord(
        id="dcj7834",
        mode="fast",
        status="queued",
        item_count=1,
        created_at=stamp.isoformat(),
        updated_at=stamp.isoformat(),
    )
    assert stale.public_dict()["status"] == "failed"
    assert stale.status == "queued"