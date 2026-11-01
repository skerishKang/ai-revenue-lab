"""#5882 follow-up (261102): the pending-selection cap counts only live rows.

The cap refusal must not push an internal English sentence onto the screen,
and expired selections must not keep the window blocked: select() already
filters the count on expires_at, and these tests pin both halves -- plus the
closed 409 body the panel maps to its Korean copy.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))

from test_3580_web_xlsx_selection_routes import (  # noqa: E402
    RealSQLiteD1, setup, upload, selected,
)
from test_3580_web_xlsx_sources import OWNER  # noqa: E402
from app.claw_web_xlsx_selection_store import (  # noqa: E402
    D1WebXlsxSelectionStore, WebXlsxSelectionError, _MAX_PENDING,
)

_FAR = "2027-01-01T00:00:00+00:00"


def _source():
    return {
        "document_id": "doc_" + "1" * 32,
        "source_sha256": "a" * 64,
        "original_immutable": True,
        "processing_authorized": False,
        "filename": "견적서.xlsx",
        "size_bytes": 10,
        "expires_at": _FAR,
    }


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    sql = (ROOT / "migrations" / "029_claw_web_xlsx_selection.sql").read_text(encoding="utf-8")
    conn.executescript(sql)
    return conn


def test_the_cap_is_a_protective_bound_not_storage():
    # The value stays 20 by decision (#5573): one 30-minute window of pending
    # selections, matching the bounded panel. The count excludes expired rows.
    assert _MAX_PENDING == 20
    store_source = (ROOT / "app" / "claw_web_xlsx_selection_store.py").read_text(encoding="utf-8")
    assert 'AND expires_at>?' in store_source


@pytest.mark.asyncio
async def test_expired_selections_do_not_consume_the_cap():
    conn = _conn()
    store = D1WebXlsxSelectionStore(RealSQLiteD1(conn))
    base = datetime(2026, 11, 2, 0, 0, 0, tzinfo=timezone.utc)
    for _ in range(_MAX_PENDING):
        await store.select(owner_id="usr_cap", workspace_id="ws_cap",
                           source=_source(), now=base)
    assert conn.execute(
        "SELECT COUNT(*) FROM claw_web_xlsx_selections").fetchone()[0] == _MAX_PENDING

    # Every row is still inside its 30-minute window: the next select refuses.
    with pytest.raises(WebXlsxSelectionError):
        await store.select(owner_id="usr_cap", workspace_id="ws_cap",
                           source=_source(), now=base)

    # Past the window the same owner is free again -- the expired rows are not
    # counted, so the cap can never be held shut by stale pending state.
    later = base + timedelta(minutes=31)
    row = await store.select(owner_id="usr_cap", workspace_id="ws_cap",
                             source=_source(), now=later)
    assert str(row["selection_ref"]).startswith("sel_")
    assert conn.execute(
        "SELECT COUNT(*) FROM claw_web_xlsx_selections").fetchone()[0] == _MAX_PENDING + 1


@pytest.mark.asyncio
async def test_the_http_refusal_body_carries_only_the_closed_code():
    app, settings, _meta, _r2, _storage, conn = setup()
    file = await upload(app, settings)
    for _ in range(_MAX_PENDING):
        response = await selected(app, settings, file["document_id"])
        assert response.status_code == 201, response.text
    refused = await selected(app, settings, file["document_id"])
    assert refused.status_code == 409
    body = refused.json()
    # No message field, no internal English sentence: the panel maps this one
    # closed code to its Korean copy and keeps the machine token off the screen.
    assert body == {"ok": False, "error": {"code": "web_xlsx_selection_refused"}}


def test_the_pending_full_sentence_is_owned_by_locale():
    locale = (ROOT / "static" / "locale.js").read_text(encoding="utf-8")
    assert locale.count('"web-xlsx-pending-full"') == 2
    sources = (ROOT / "static" / "claw-web-xlsx-sources.js").read_text(encoding="utf-8")
    assert '"web-xlsx-pending-full"' in sources
    assert "엑셀 선택 대기가" not in sources


def test_node_copy_contract_runs():
    import shutil
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")
    completed = subprocess_run_node(node)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def subprocess_run_node(node):
    import subprocess
    return subprocess.run(
        [node, str(ROOT / "tests" / "test_web_xlsx_pending_cap_copy_261102.cjs")],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
