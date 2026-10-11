"""#3929 real SQLite migration, D1-style prepared bindings, auth-route tests."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from starlette.requests import Request

from app.history import D1HistoryStore
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
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


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
                "015_claw_run_history_workspace.sql"):
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


class ClawOwnerConversationD1Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = setup_database()
        self.store = D1HistoryStore(D1Sqlite(self.db))

    def tearDown(self):
        self.db.close()

    async def test_real_sql_durable_registration_and_owner_followup_read(self):
        record = canonical()
        self.assertTrue(await self.store.register_owner_conversation_artifact(
            user_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE, artifact=record
        ))
        code, body, headers = await call(self.store)
        self.assertEqual(code, 200)
        self.assertEqual(body["followup"]["status"], "resolved")
        self.assertEqual(body["followup"]["source_artifact_id"], record.artifact_id)
        self.assertEqual(body["followup"]["source_integrity_ref"], record.integrity_ref)
        self.assertEqual(body["followup"]["source_run_ref"], RUN)
        self.assertFalse(body["followup"]["read_grant_issued"])
        self.assertNotIn("private_file_provider_ref", json.dumps(body))
        self.assertEqual(headers["cache-control"], "no-store, max-age=0")
        # Exact same registration is idempotent; no duplicate phantom history.
        self.assertTrue(await self.store.register_owner_conversation_artifact(
            user_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE, artifact=record
        ))
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM claw_conversation_artifact_index").fetchone()[0], 1)

    async def test_run_must_be_completed_and_bound_to_owner_conversation_workspace(self):
        invalid = [
            dict(user_id=FOREIGN, conversation_id=CHAT, workspace_ref=WORKSPACE,
                 artifact=canonical()),
            dict(user_id=OWNER, conversation_id=FOREIGN_CHAT, workspace_ref=WORKSPACE,
                 artifact=canonical()),
            dict(user_id=OWNER, conversation_id=CHAT, workspace_ref=OTHER_WORKSPACE,
                 artifact=canonical()),
            dict(user_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE,
                 artifact=canonical(source_run=RUN2)),
        ]
        for values in invalid:
            with self.subTest(values=values):
                self.assertFalse(
                    await self.store.register_owner_conversation_artifact(**values))
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM claw_conversation_artifact_index").fetchone()[0], 0)

    async def test_revoke_conversation_and_workspace_switch_hide_artifact(self):
        await self.store.register_owner_conversation_artifact(
            user_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE,
            artifact=canonical())
        self.assertEqual((await call(self.store, workspace=OTHER_WORKSPACE))[1][
            "followup"]["status"], "not_available")
        self.assertEqual((await call(self.store, owner=FOREIGN))[0], 404)
        self.db.execute("DELETE FROM claw_conversation_artifact_index")
        self.db.execute("DELETE FROM conversations WHERE id=?", (CHAT,))
        self.assertEqual((await call(self.store))[0], 404)

    async def test_reject_cross_conversation_transfer_and_stale_id(self):
        record = canonical()
        await self.store.register_owner_conversation_artifact(
            user_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE,
            artifact=record)
        self.assertFalse(await self.store.register_owner_conversation_artifact(
            user_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE,
            artifact=canonical(filename="spoof.xlsx"),
        ))
        code, body, _ = await call(self.store, selector="exact",
                                   artifact_id=record.artifact_id,
                                   integrity_ref="f" * 64)
        self.assertEqual(code, 200)
        self.assertEqual(body["followup"]["status"], "not_available")

    async def test_duplicate_filename_requires_exact_id_and_digest(self):
        await self.store.register_owner_conversation_artifact(
            user_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE,
            artifact=canonical())
        # A second, distinct completed run for the same owner/thread/workspace.
        self.db.execute("UPDATE claw_run_history SET status='completed' WHERE run_id=?", (RUN2,))
        other = canonical(artifact_id="artifact_3929_02", source_run=RUN2)
        await self.store.register_owner_conversation_artifact(
            user_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE, artifact=other)
        code, body, _ = await call(self.store)
        self.assertEqual(code, 200)
        self.assertEqual(body["followup"]["status"], "confirmation_required")
        self.assertEqual(len(body["followup"]["choices"]), 2)
        self.assertEqual(body["followup"]["choices"][0]["integrity_ref"], other.integrity_ref)
        _, exact, _ = await call(
            self.store, selector="exact",
            artifact_id=other.artifact_id, integrity_ref=other.integrity_ref)
        self.assertEqual(exact["followup"]["status"], "resolved")

    async def test_non_owner_and_no_auth_and_no_cp_fails_closed(self):
        code, body, _ = await call(self.store, owner=FOREIGN)
        self.assertEqual(code, 404)
        self.assertEqual(body["error"]["code"], "conversation_not_found")
        r = req(self.store)
        with patch("app.claw_conversation_artifact_routes.auth_ready", return_value=False):
            response = await claw_conversation_artifact_followup(r)
        self.assertEqual(response.status_code, 401)
        code, _, _ = await call(self.store, workspace=None)
        self.assertEqual(code, 403)

    async def test_migration_not_applied_503_without_production_mutation(self):
        old_db = setup_database(with_index=False)
        try:
            store = D1HistoryStore(D1Sqlite(old_db))
            code, body, _ = await call(store)
            self.assertEqual(code, 503)
            self.assertEqual(body["error"]["code"], "artifact_index_read_failed")
            names = {row[0] for row in old_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("claw_conversation_artifact_index", names)
        finally:
            old_db.close()

    async def test_real_starlette_auth_cookie_route_and_same_origin_owner_lookup(self):
        from starlette.testclient import TestClient
        from app.app_factory import create_app
        from app.auth import SESSION_COOKIE, create_session_token
        import test_b54_claw_general_p01_routing as base

        self.assertTrue(await self.store.register_owner_conversation_artifact(
            user_id=OWNER, conversation_id=CHAT,
            workspace_ref=WORKSPACE, artifact=canonical(),
        ))
        app = create_app(settings=base._settings(), history_store=self.store)
        async def cp(_request):
            return WORKSPACE
        with patch("app.claw_conversation_artifact_routes._resolve_canonical_tenant", cp):
            with TestClient(app, base_url="https://chat.example.test") as client:
                without_session = client.get(
                    f"/api/claw/conversations/{CHAT}/artifact-followup?kind=xlsx"
                )
                self.assertEqual(without_session.status_code, 401)
                client.cookies.set(
                    SESSION_COOKIE, create_session_token(base._settings(), OWNER),
                    domain="chat.example.test", path="/",
                )
                owned = client.get(
                    f"/api/claw/conversations/{CHAT}/artifact-followup?kind=xlsx"
                )
                self.assertEqual(owned.status_code, 200, owned.text)
                self.assertEqual(owned.json()["followup"]["status"], "resolved")
                self.assertEqual(
                    owned.json()["followup"]["source_artifact_id"],
                    "artifact_3929_01",
                )
                self.assertNotIn("private_file_provider_ref", owned.text)
                foreign = client.get(
                    f"/api/claw/conversations/{FOREIGN_CHAT}/artifact-followup"
                )
                self.assertEqual(foreign.status_code, 404)

    async def test_connection_reopens_same_durable_index_and_run_deletion_cascades(self):
        import tempfile
        self.assertTrue(await self.store.register_owner_conversation_artifact(
            user_id=OWNER, conversation_id=CHAT,
            workspace_ref=WORKSPACE, artifact=canonical(),
        ))
        # SQLite's backup waits on any uncommitted in-memory writer; commit
        # the D1-style shim transaction to emulate persisted Worker writes.
        self.db.commit()
        with tempfile.TemporaryDirectory(prefix="padiem3929-") as directory:
            file_path = Path(directory) / "sqlite_reopened.db"
            copied = sqlite3.connect(file_path)
            try:
                self.db.backup(copied)
            finally:
                copied.close()
            fresh = sqlite3.connect(file_path)
            try:
                fresh.row_factory = sqlite3.Row
                fresh.execute("PRAGMA foreign_keys=ON")
                reopened = D1HistoryStore(D1Sqlite(fresh))
                status, body, _ = await call(reopened)
                self.assertEqual(status, 200)
                self.assertEqual(body["followup"]["status"], "resolved")
                self.assertEqual(body["followup"]["source_run_ref"], RUN)
                fresh.execute("DELETE FROM claw_run_history WHERE run_id=?", (RUN,))
                fresh.commit()
                status, body, _ = await call(reopened)
                self.assertEqual(status, 200)
                self.assertEqual(body["followup"]["status"], "not_available")
                self.assertEqual(fresh.execute(
                    "SELECT count(*) FROM claw_conversation_artifact_index"
                ).fetchone()[0], 0)
            finally:
                fresh.close()

    async def test_selector_rejects_file_path_and_malformed_conversation(self):
        code, body, _ = await call(self.store, selector="filename",
                                   filename="../other.xlsx")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"]["code"], "invalid_artifact_selector")
        code, body, _ = await call(self.store, thread="invalid")
        self.assertEqual(code, 400)
        self.assertEqual(body["error"]["code"], "invalid_conversation_id")


if __name__ == "__main__":
    unittest.main()
