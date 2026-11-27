"""#7955 ③ 묶음 결과 표기 — 두 파일 중 하나만 실패해도 결과가 갈려 보여야 한다.

현장 증상(2026-11-18): 2개 중 1개만 실패한 묶음이 작업 이력에서 '실패' 하나로
보여, 나머지 하나가 변환됐다는 사실이 화면에서 사라졌다.

판정은 계산 값으로 한다. 서버는 상태별 개수를 세어 보내고, 화면은 그 개수로
'1개 완료 · 1개 실패'를 만든다. 개수가 없는 옛 응답은 세어 보인 척하지 않는다.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import os
import shutil
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover - CI without a browser
    sync_playwright = None

from app.document_convert_com2 import Com2SqliteLedger
from app.document_convert_store import (
    ABANDONED_AFTER_SECONDS,
    JOB_STATUS_DONE,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_REVIEWED,
    JOB_STATUS_WORKING,
    ConvertItemRecord,
    ConvertJobRecord,
    job_outcome_counts,
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
PDFMD_PAGES_JS = STATIC / "util-pdfmd-pages.js"
CHROME_CANDIDATES = [
    os.environ.get("B61_CHROME_PATH"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]
CHROME = next((c for c in CHROME_CANDIDATES if c and Path(c).is_file()), None)
OWNER = "usr_" + "e" * 32
OTHER = "usr_" + "f" * 32


def _item(status: str, *, age_seconds: float = 0.0) -> ConvertItemRecord:
    stamp = (
        datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    ).isoformat().replace("+00:00", "Z")
    return ConvertItemRecord(
        id="dci7955",
        job_id="dcj7955",
        name="묶음.pdf",
        status=status,
        page_count=1,
        character_count=0,
        original_key="originals/one.pdf",
        markdown_key=None,
        report=None,
        error_code=None,
        created_at=stamp,
        updated_at=stamp,
    )


def _job(**kwargs) -> ConvertJobRecord:
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    base = {
        "id": "dcj7955",
        "mode": "fast",
        "status": JOB_STATUS_FAILED,
        "item_count": 2,
        "created_at": stamp,
        "updated_at": stamp,
    }
    base.update(kwargs)
    return ConvertJobRecord(**base)


# --------------------------------------------------------------------------
# 서버: 상태별 개수는 항목自己在 센다
# --------------------------------------------------------------------------


def test_one_done_and_one_failed_count_separately() -> None:
    counts = job_outcome_counts([_item(JOB_STATUS_DONE), _item(JOB_STATUS_FAILED)])

    assert counts == {"done": 1, "working": 0, "failed": 1}


def test_reviewed_counts_as_completed_and_queued_as_running() -> None:
    counts = job_outcome_counts(
        [_item(JOB_STATUS_REVIEWED), _item(JOB_STATUS_QUEUED), _item(JOB_STATUS_WORKING)]
    )

    assert counts == {"done": 1, "working": 2, "failed": 0}


def test_an_abandoned_row_counts_as_a_failure() -> None:
    counts = job_outcome_counts(
        [_item(JOB_STATUS_DONE), _item(JOB_STATUS_WORKING, age_seconds=ABANDONED_AFTER_SECONDS + 60)]
    )

    assert counts == {"done": 1, "working": 0, "failed": 1}


def test_the_rolled_up_status_alone_cannot_express_a_split_batch() -> None:
    """The defect itself: the job state is failed while one item completed."""

    job = _job(outcomes=job_outcome_counts([_item(JOB_STATUS_DONE), _item(JOB_STATUS_FAILED)]))
    payload = job.public_dict()

    assert payload["status"] == JOB_STATUS_FAILED
    assert payload["item_count"] == 2
    assert payload["outcomes"] == {"done": 1, "working": 0, "failed": 1}


def test_a_job_without_counts_does_not_invent_them() -> None:
    assert "outcomes" not in _job().public_dict()


def test_the_com2_ledger_counts_only_the_owners_own_items(tmp_path) -> None:
    ledger = Com2SqliteLedger(tmp_path / "ledger.sqlite3")

    async def complete(user_id: str, item_id: str) -> None:
        await ledger.complete_item(
            user_id, item_id,
            status=JOB_STATUS_DONE, page_count=1, character_count=12,
            markdown_key=f"documents/{user_id}/convert/{item_id}.md",
            report=None, error_code=None,
        )

    async def journey():
        job = await ledger.create_job(OWNER, mode="fast")
        first = await ledger.add_item(OWNER, job.id, name="성공.pdf", page_count=1)
        second = await ledger.add_item(OWNER, job.id, name="실패.pdf", page_count=1)
        await complete(OWNER, first.id)
        await ledger.set_item_status(OWNER, second.id, JOB_STATUS_FAILED)
        stranger = await ledger.create_job(OTHER, mode="fast")
        theirs = await ledger.add_item(OTHER, stranger.id, name="남의것.pdf", page_count=1)
        await complete(OTHER, theirs.id)
        return await ledger.list_jobs(OWNER, limit=50), await ledger.list_jobs(OTHER, limit=50)

    mine, theirs = asyncio.run(journey())

    assert [job.public_dict()["outcomes"] for job in mine] == [
        {"done": 1, "working": 0, "failed": 1}
    ]
    assert [job.public_dict()["outcomes"] for job in theirs] == [
        {"done": 1, "working": 0, "failed": 0}
    ]


def test_the_d1_ledger_counts_a_split_batch_too(tmp_path) -> None:
    """The Cloudflare-shaped ledger answers the same counts as COM2."""

    import sqlite3

    from app.document_convert_store import D1DocumentConvertStore

    migration = ROOT / "migrations" / "066_document_convert_jobs.sql"
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(migration.read_bytes().decode("utf-8"))

    class _Statement:
        def __init__(self, sql: str, params: tuple = ()) -> None:
            self.sql, self.params = sql, params

        def bind(self, *params):
            return _Statement(self.sql, params)

        async def first(self):
            row = conn.execute(self.sql, self.params).fetchone()
            return dict(row) if row else None

        async def all(self):
            return [dict(row) for row in conn.execute(self.sql, self.params).fetchall()]

        async def run(self):
            cursor = conn.execute(self.sql, self.params)
            return {"meta": {"changes": cursor.rowcount}}

    class _Db:
        def prepare(self, sql: str):
            return _Statement(sql)

    store = D1DocumentConvertStore(_Db())

    async def journey():
        job = await store.create_job(OWNER, mode="fast")
        first = await store.add_item(OWNER, job.id, name="성공.pdf", page_count=1)
        second = await store.add_item(OWNER, job.id, name="실패.pdf", page_count=1)
        await store.complete_item(
            OWNER, first.id,
            status=JOB_STATUS_DONE, page_count=1, character_count=12,
            markdown_key="documents/owner/convert/one.md", report=None, error_code=None,
        )
        await store.set_item_status(OWNER, second.id, JOB_STATUS_FAILED)
        return await store.list_jobs(OWNER, limit=50)

    jobs = asyncio.run(journey())

    assert [job.public_dict()["outcomes"] for job in jobs] == [
        {"done": 1, "working": 0, "failed": 1}
    ]


def test_an_empty_batch_carries_no_counts(tmp_path) -> None:
    ledger = Com2SqliteLedger(tmp_path / "ledger.sqlite3")

    async def journey():
        await ledger.create_job(OWNER, mode="fast")
        return await ledger.list_jobs(OWNER, limit=50)

    jobs = asyncio.run(journey())

    assert len(jobs) == 1
    assert "outcomes" not in jobs[0].public_dict()


# --------------------------------------------------------------------------
# 화면: 개수로 문구를 만든다 (원문 단언이 아니라 계산 값 비교)
# --------------------------------------------------------------------------

_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const context = { window: {} };
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), context);
const outcome = context.window.PadiemPdfMdBatchOutcome;
const cases = JSON.parse(process.argv[3]);
console.log(JSON.stringify({
  ok: true,
  rows: cases.map((job) => ({ label: outcome.label(job), status: outcome.status(job) })),
}));
"""


def _run_outcomes(cases: list[dict]) -> list[dict]:
    node = shutil.which("node")
    assert node, "node runtime is required for the batch-outcome harness"
    harness = ROOT / "tests" / "_7955_pdfmd_outcomes.js"
    harness.write_text(_HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            [node, str(harness), str(PDFMD_PAGES_JS), json.dumps(cases)],
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
    assert result.returncode == 0 and stdout, (
        f"harness crashed: stdout={stdout!r} stderr={result.stderr!r}"
    )
    payload = json.loads(stdout.splitlines()[-1])
    assert payload.get("ok"), payload
    return payload["rows"]


def test_a_split_batch_reads_as_counts_not_one_failure() -> None:
    rows = _run_outcomes([
        {"status": "failed", "item_count": 2, "outcomes": {"done": 1, "working": 0, "failed": 1}},
    ])

    assert rows == [{"label": "1개 완료 · 1개 실패", "status": "failed"}]


def test_counts_are_ordered_completed_running_failed() -> None:
    rows = _run_outcomes([
        {"outcomes": {"done": 2, "working": 3, "failed": 1}},
        {"outcomes": {"done": 0, "working": 2, "failed": 0}},
        {"outcomes": {"done": 4, "working": 0, "failed": 0}},
    ])

    assert [row["label"] for row in rows] == [
        "2개 완료 · 3개 바꾸는 중 · 1개 실패",
        "2개 바꾸는 중",
        "4개 완료",
    ]
    assert [row["status"] for row in rows] == ["failed", "working", "done"]


def test_a_batch_without_counts_keeps_the_single_badge() -> None:
    rows = _run_outcomes([
        {"status": "failed", "item_count": 2},
        {"status": "done", "outcomes": {"done": 0, "working": 0, "failed": 0}},
        {"status": "done", "outcomes": None},
    ])

    assert rows == [{"label": "", "status": ""}] * 3


def test_a_non_numeric_count_is_not_printed() -> None:
    rows = _run_outcomes([
        {"outcomes": {"done": "1", "working": None, "failed": -3}},
        {"outcomes": {"done": 1.9, "working": 0, "failed": 0}},
    ])

    assert [row["label"] for row in rows] == ["1개 완료", "1개 완료"]


# --------------------------------------------------------------------------
# 실제 브라우저: 이력 줄의 칩이 개수로 읽히는지 (계산 값 비교)
# --------------------------------------------------------------------------

_BAND_HTML = """<!DOCTYPE html>
<html lang="ko" data-theme="padiem-home"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="./padiem-themes.css">
<link rel="stylesheet" href="./sidebar-utility.css">
<link rel="stylesheet" href="./standalone-views.css">
<link rel="stylesheet" href="./util-menu.css">
<link rel="stylesheet" href="./util-pdfmd-recovery.css">
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
<script src="./util-pdfmd-recovery.js"></script>
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

_STAMP = "2026-11-19T09:00:00Z"
_BAND_JOBS = [
    {"id": "job_split", "mode": "fast", "status": "failed", "item_count": 2,
     "created_at": _STAMP, "updated_at": _STAMP,
     "outcomes": {"done": 1, "working": 0, "failed": 1}},
    {"id": "job_plain", "mode": "fast", "status": "failed", "item_count": 1,
     "created_at": _STAMP, "updated_at": _STAMP},
]


class _BandHandler(http.server.SimpleHTTPRequestHandler):
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
            self._json({"jobs": _BAND_JOBS, "limit": 50, "new_work_enabled": True})
            return
        if path.startswith("/api/"):
            self._json({})
            return
        super().do_GET()

    def do_POST(self):  # noqa: N802
        self._json({"ok": True})


@pytest.fixture()
def band_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _BandHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d/index.html" % server.server_port
    server.shutdown()


@pytest.mark.skipif(sync_playwright is None or not CHROME,
                    reason="playwright or Chrome is not installed")
def test_the_history_row_prints_the_split_result_in_a_real_browser(band_url) -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.route("**/index.html", lambda route: route.fulfill(
                status=200, headers={"content-type": "text/html; charset=utf-8"},
                body=_BAND_HTML))
            page.goto(band_url, wait_until="domcontentloaded")
            page.wait_for_selector(".pdfmd-history-fold summary", state="visible", timeout=8000)
            page.locator(".pdfmd-history-fold summary").click()
            page.locator(".pdfmd-history-item").first.wait_for(state="visible", timeout=8000)
            rows = page.evaluate(
                """() => Array.from(document.querySelectorAll('.pdfmd-history-item')).map(
                     (row) => ({
                       id: row.dataset.jobId,
                       chip: row.querySelector('.pdfmd-status-chip').textContent,
                       state: row.querySelector('.pdfmd-status-chip').dataset.status,
                       aria: row.getAttribute('aria-label'),
                     }))"""
            )
        finally:
            browser.close()

    counted = next(row for row in rows if row["id"] == "job_split")
    plain = next(row for row in rows if row["id"] == "job_plain")

    assert counted["chip"] == "1개 완료 · 1개 실패"
    assert counted["state"] == "failed"
    assert counted["chip"] in counted["aria"]
    # An answer without counts keeps the single badge it always had.
    assert plain["chip"] == "실패"
    assert plain["state"] == "failed"