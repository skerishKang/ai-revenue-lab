"""Shared real SQLite-backed web XLSX selection fixtures (#3580)."""
from __future__ import annotations

import base64
from pathlib import Path
import sqlite3

from _support.web_xlsx_sources import harness, request, workbook, OWNER
from app.claw_web_xlsx_selection_store import D1WebXlsxSelectionStore

ENDPOINT = "/api/claw/office/web-selections"


class RealSQLiteD1:
    def __init__(self, conn):
        self.conn = conn

    def prepare(self, query):
        return D1Statement(self.conn, query)


class D1Statement:
    def __init__(self, conn, query):
        self.conn, self.query, self.args = conn, query, ()
    def bind(self, *args):
        self.args = args
        return self
    async def run(self):
        self.conn.execute(self.query, self.args)
        return {}
    async def first(self):
        row = self.conn.execute(self.query, self.args).fetchone()
        return dict(row) if row else None
    async def all(self):
        return [dict(row) for row in self.conn.execute(self.query, self.args).fetchall()]


def setup():
    app, settings, metadata, r2, source = harness()
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    sql = (Path(__file__).resolve().parents[2] / "migrations"
           / "029_claw_web_xlsx_selection.sql").read_text(encoding="utf-8")
    conn.executescript(sql)
    app.state.claw_web_xlsx_selection_store = D1WebXlsxSelectionStore(RealSQLiteD1(conn))
    return app, settings, metadata, r2, source, conn


async def upload(app, settings, name="safe.xlsx"):
    resp = await request(app, settings, method="POST",
                         payload={"name": name, "base64": base64.b64encode(workbook()).decode()})
    assert resp.status_code == 201, resp.text
    return resp.json()["file"]


async def selected(app, settings, document_id, *, owner=OWNER, data=None):
    return await request(
        app, settings, path=ENDPOINT, method="POST", owner=owner,
        payload=data if data is not None else {"document_id": document_id},
    )

