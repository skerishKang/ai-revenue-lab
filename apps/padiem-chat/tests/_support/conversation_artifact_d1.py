"""Shared synthetic conversation artifact D1 fixtures (#3929)."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

from starlette.requests import Request

from app.history import D1HistoryStore as D1HistoryStore
from app.claw_conversation_artifact_routes import (
    claw_conversation_artifact_followup,
)
from kagent.artifact_registration import (
    ArtifactLifecycle, ArtifactLocation, register_canonical_artifact,
)


OWNER = "usr_" + "a" * 32
FOREIGN = "usr_" + "b" * 32
CHAT = "chat_" + "c" * 32
FOREIGN_CHAT = "chat_" + "d" * 32
WORKSPACE = "tenant_test_3929"
OTHER_WORKSPACE = "tenant_other_3929"
RUN = "run_" + "e" * 24
RUN2 = "run_" + "f" * 24
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


class D1Statement:
    def __init__(self, connection, sql, values=()):
        self.conn, self.sql, self.values = connection, sql, values

    def bind(self, *values):
        return D1Statement(self.conn, self.sql, values)

    async def first(self):
        row = self.conn.execute(self.sql, self.values).fetchone()
        return dict(row) if row is not None else None

    async def run(self):
        cursor = self.conn.execute(self.sql, self.values)
        return SimpleNamespace(
            results=[dict(row) for row in cursor.fetchall()],
            meta={"changes": cursor.rowcount},
        )


class D1Sqlite:
    def __init__(self, connection):
        self.connection = connection

    def prepare(self, sql):
        return D1Statement(self.connection, sql)


def canonical(*, artifact_id="artifact_3929_01", filename="quote.xlsx",
              source_run=RUN, workspace=WORKSPACE):
    return register_canonical_artifact(
        artifact_id=artifact_id,
        artifact_kind="working.xlsx",
        filename=filename,
        media_type=XLSX,
        size_bytes=120,
        integrity_ref="7" * 64,
        lifecycle=ArtifactLifecycle.DURABLE,
        workspace_ref=workspace,
        run_ref=source_run,
        durable_location=ArtifactLocation("google_drive", "private_file_provider_ref"),
    )


def setup_database(*, with_index=True):
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    for mig in ("001_auth_history.sql", "009_claw_run_history.sql",
                "014_claw_run_history_conversation.sql",
                "015_claw_run_history_workspace.sql",
                "105_conversation_soft_delete.sql"):
        db.executescript((MIGRATIONS / mig).read_text(encoding="utf8"))
    if with_index:
        db.executescript(
            (MIGRATIONS / "026_claw_conversation_artifact_index.sql")
            .read_text(encoding="utf8")
        )
    for owner in (OWNER, FOREIGN):
        db.execute(
            "INSERT INTO users(id,auth_provider,provider_subject,email,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (owner, "google", owner, owner + "@example.com", "2026-10-10", "2026-10-10"),
        )
    for cid, owner in ((CHAT, OWNER), (FOREIGN_CHAT, FOREIGN)):
        db.execute(
            "INSERT INTO conversations(id,user_id,title,created_at,updated_at) "
            "VALUES (?,?,?,?,?)", (cid, owner, "fixture", "2026-10-10", "2026-10-10"),
        )
    for run, status, tenant in ((RUN, "completed", WORKSPACE),
                                (RUN2, "failed", WORKSPACE)):
        db.execute(
            "INSERT INTO claw_run_history "
            "(id,user_id,run_id,channel,action,title,status,created_at,updated_at,"
            "conversation_id,workspace_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("crh_" + run[4:], OWNER, run, "web", "general", "fixture",
             status, "2026-10-10", "2026-10-10", CHAT, tenant),
        )
    db.commit()
    return db


def req(store, *, owner=OWNER, thread=CHAT, kind="xlsx",
        selector="latest", filename=None, artifact_id=None,
        integrity_ref=None):
    query = {k: v for k, v in dict(
        kind=kind, selector=selector, filename=filename,
        artifact_id=artifact_id, integrity_ref=integrity_ref,
    ).items() if v is not None}
    return Request({
        "type": "http", "method": "GET",
        "path": f"/api/claw/conversations/{thread}/artifact-followup",
        "query_string": urlencode(query).encode(),
        "headers": [],
        "path_params": {"conversation_id": thread},
        "app": SimpleNamespace(state=SimpleNamespace(history_store=store)),
        "fixture_owner": owner,
    })


async def call(store, *, owner=OWNER, workspace=WORKSPACE, **kwargs):
    r = req(store, owner=owner, **kwargs)
    with patch("app.claw_conversation_artifact_routes.auth_ready", return_value=True), \
         patch("app.claw_conversation_artifact_routes.current_user_id",
               return_value=owner), \
         patch("app.claw_conversation_artifact_routes._resolve_canonical_tenant",
               return_value=workspace):
        # CP resolver is awaitable in production; async fake is required.
        async def cp(_):
            return workspace
        with patch("app.claw_conversation_artifact_routes._resolve_canonical_tenant", cp):
            response = await claw_conversation_artifact_followup(r)
    return response.status_code, json.loads(response.body.decode()), response.headers
