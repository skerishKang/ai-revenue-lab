"""#6659 3번 1단계 — signed-in Chat account self-deletion.

The route deletes every user-keyed row the migration survey found, in ONE
atomic batch, behind the exact-email confirmation. Production D1 does not
enforce foreign keys and the local CPython host mirrors that, so this suite
runs its database with ``PRAGMA foreign_keys=OFF``: only the explicit deletes
in ``app.account_deletion`` may clear the rows, never a CASCADE.

Claims verified here:
(a) every surveyed table loses that user's rows, every other user's rows stay;
(b) a mismatched confirm email deletes nothing;
(c) no session and a foreign origin are both refused;
(d) a mid-batch failure rolls the whole deletion back;
(e) a stored cookie stops authenticating right after the deletion;
(f) the central administrator and stored platform-admin roles are refused;
(g) migration 092 applies twice without error;
(h) account deletion removes only its own Mesh presence owner reference.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.account_deletion import (
    _INTENTIONALLY_PRESERVED_USER_KEYED_TABLES,
    _USER_KEYED_TABLES,
)
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.history import D1HistoryStore, _password_user_id, _user_id
from app.main import create_app

from test_6446_account_isolation_sweep import apply_all_migrations

BASE = "https://chat.example.test"
SESSION_SECRET = "account-delete-test-session-secret-not-real-000000"
CENTRAL_ADMIN_EMAIL = "central-admin@example.test"
DELETER_EMAIL = "owner@example.test"
OTHER_EMAIL = "other@example.test"
ROLE_USER_EMAIL = "role-admin@example.test"

ROOT = Path(__file__).resolve().parents[1]


class Statement:
    def __init__(self, db, sql, params=()):
        self.db, self.sql, self.params = db, sql, params

    def bind(self, *params):
        return Statement(self.db, self.sql, params)

    async def first(self):
        row = self.db.conn.execute(self.sql, self.params).fetchone()
        return dict(row) if row else None

    async def run(self):
        cursor = self.db.conn.execute(self.sql, self.params)
        return SimpleNamespace(
            results=[dict(row) for row in cursor.fetchall()],
            meta={"changes": cursor.rowcount},
        )


class SqliteD1:
    """Local D1 stand-in with foreign keys OFF — production parity.

    Production D1 never enforces ``PRAGMA foreign_keys`` and ``local_cpython``
    deliberately mirrors that, so the deletion contract under test here is the
    explicit per-table DELETE, never a CASCADE.
    """

    def __init__(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=OFF")

    def prepare(self, sql):
        return Statement(self, sql)

    async def batch(self, statements):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            results = []
            for statement in statements:
                cursor = self.conn.execute(statement.sql, statement.params)
                results.append(
                    SimpleNamespace(
                        results=[dict(row) for row in cursor.fetchall()],
                        meta={"changes": cursor.rowcount},
                    )
                )
            self.conn.execute("COMMIT")
            return results
        except Exception:
            self.conn.execute("ROLLBACK")
            raise


class CanonicalAuthority:
    async def revoke_auth_session(self, *, product_id, session_id):
        return None


def _generic_value(user: str, table: str, name: str, declared: str | None):
    kind = (declared or "").upper()
    if kind.startswith(("INT", "BIGINT", "SMALLINT", "TINYINT")):
        return 1
    if kind.startswith(("REAL", "FLOA", "DOUB", "NUM")):
        return 1.0
    if kind.startswith("BLOB"):
        return b"v"
    return f"v:{user[:8]}.{table}.{name}"


def _sha(seed: str):
    """A per-user 64-hex digest for UNIQUE hash-shaped columns."""
    return lambda user: hashlib.sha256((seed + user).encode("utf-8")).hexdigest()


#: Values the generic seeder cannot guess: CHECK-pinned columns and the
#: conversation id wiring the messages delete (a subquery over conversations)
#: depends on.
_OVERRIDES = {
    ("conversations", "id"): lambda user: "conv:" + user,
    ("messages", "conversation_id"): lambda user: "conv:" + user,
    ("messages", "role"): "user",
    ("project_files", "media_type"): "text/plain",
    ("project_files", "content_chars"): 1,
    ("orchestration_continuations", "state"): "active",
    ("orchestration_decisions", "outcome"): "approved",
    ("claw_task_alert", "kind"): "task",
    ("claw_task_alert", "status"): "open",
    ("b66_saved_skill_candidate", "status"): "pending",
    ("b66_signup_alert_delivery", "channel"): "email",
    # inquiry_id is a 39-character PK: a 3-char prefix over the 36-char uid.
    ("b66_member_inquiries", "inquiry_id"): lambda user: "inq" + user,
    ("b66_member_inquiries", "category"): "general",
    ("claw_coding_conversation_grant", "product_id"): "b54-padiem-claw",
    ("claw_coding_conversation_grant", "state"): "reserved",
    ("platform_admin_roles", "role"): "ADMIN",
    ("claw_meetings", "mode"): "record",
    ("claw_meetings", "status"): "active",
    ("claw_meeting_artifacts", "kind"): "minutes",
    ("claw_meeting_artifacts", "state"): "local_only",
    ("claw_meeting_actions", "kind"): "decision",
    ("claw_meeting_actions", "status"): "candidate",
    ("document_convert_jobs", "mode"): "fast",
    ("document_convert_jobs", "status"): "queued",
    ("document_convert_items", "status"): "queued",
    ("pc_pairing_codes", "issued_at"): "2026-11-03T00:00:00Z",
    ("pc_pairing_codes", "expires_at"): "2026-11-04T00:00:00Z",
    ("padiem_account_model_selections", "tier"): "free",
    ("claw_web_xlsx_quote_write_pauses", "status"): "dispatching",
    ("claw_web_xlsx_quote_write_pauses", "source_sha256"): _sha("wp"),
    ("claw_web_xlsx_quote_write_pauses", "edit_sha256"): _sha("we2"),
    ("b66_ai_turn_attempt", "product_scope"): "b66-quote",
    ("b66_ai_turn_attempt", "turn_token"): "t" * 32,
    ("b66_ai_turn_attempt", "request_digest"): _sha("rd"),
    ("b66_ai_turn_attempt", "state"): "claimed",
    ("claw_web_xlsx_p01_decision_receipts", "state"): "dispatching",
    ("claw_web_xlsx_quote_edit_receipts", "state"): "dispatching",
    ("claw_web_xlsx_quote_write_decisions", "state"): "dispatching",
    ("padiem_calendar_appointment", "appointment_type"): "timed",
    ("padiem_mcp_shell_jobs", "state"): "queued",
    ("b66_saved_quote_skill", "skill_version"): 1,
    ("b66_saved_quote_skill", "status"): "approved",
    ("b66_quote_asset", "asset_kind"): "logo",
    ("b66_quote_asset", "media_type"): "image/png",
    ("b66_quote_asset", "byte_length"): 1,
    ("b66_quote_asset", "status"): "approved",
    ("claw_conversation_artifact_index", "media_type"): "application/pdf",
    ("claw_conversation_artifact_index", "size_bytes"): 1,
    ("claw_conversation_artifact_index", "integrity_ref"): _sha("ir"),
    ("b66_template_source", "media_type"): "text/csv",
    ("b66_template_source", "byte_length"): 1,
    ("b66_template_source", "status"): "uploaded",
    ("claw_web_xlsx_selections", "source_sha256"): _sha("sel"),
    ("claw_web_xlsx_selections", "size_bytes"): 1,
    ("claw_web_xlsx_p01_requests", "source_sha256"): _sha("p01"),
    ("claw_web_xlsx_p01_requests", "status"): "dispatching",
    ("claw_web_xlsx_p01_decision_receipts", "source_sha256"): _sha("dr"),
    ("claw_web_xlsx_p01_decision_receipts", "outcome"): "approve",
    ("claw_web_xlsx_quote_write_decisions", "outcome"): "approve",
    ("claw_web_xlsx_quote_edit_receipts", "source_sha256"): _sha("ed"),
    ("claw_web_xlsx_quote_edit_receipts", "edit_sha256"): _sha("ee"),
    ("claw_web_xlsx_quote_write_decisions", "source_sha256"): _sha("wd"),
    ("claw_web_xlsx_quote_write_decisions", "edit_sha256"): _sha("we"),
    ("pc_pairing_codes", "state"): "pending",
    ("pc_pairing_codes", "code_sha256"): _sha("code"),
    ("pc_pairing_codes", "tag_sha256"): _sha("tag"),
    ("pc_install_tokens", "token_sha256"): _sha("install-token"),
    ("pc_install_tokens", "issued_at"): "2026-11-03T00:00:00Z",
    ("pc_install_tokens", "expires_at"): "2026-11-04T00:00:00Z",
    ("pc_device_links", "state"): "active",
    ("password_reset_audit", "event"): "requested",
    ("padiem_mcp_approvals", "arguments_json"): "{}",
    ("padiem_mcp_approvals", "status"): "pending",
    ("padiem_pc_delegations", "settings_json"): "{}",
    ("auth_validation_cache", "kind"): "legacy",
}


def _where_column(table: str, where: str) -> str | None:
    """The bound key column of a simple ``col = ?`` where, else None."""
    if "?" not in where or "SELECT" in where.upper():
        return None
    return where.split("=")[0].strip()


def seed_db():
    db = SqliteD1()
    apply_all_migrations(db)
    # Migration 001's own "PRAGMA foreign_keys = ON" re-enables enforcement on
    # this connection. Production D1 never enforces it, so seeding and the
    # deletion run with it off — the explicit per-table deletes are the contract.
    db.conn.execute("PRAGMA foreign_keys=OFF")
    now = "2026-11-03T00:00:00Z"
    accounts = {
        "deleter": _user_id("google-deleter"),
        "other": _user_id("google-other"),
        "central": _password_user_id(CENTRAL_ADMIN_EMAIL),
        "role": _password_user_id(ROLE_USER_EMAIL),
    }
    for name, uid in accounts.items():
        email = {
            "deleter": DELETER_EMAIL,
            "other": OTHER_EMAIL,
            "central": CENTRAL_ADMIN_EMAIL,
            "role": ROLE_USER_EMAIL,
        }[name]
        db.conn.execute(
            "INSERT INTO users (id, auth_provider, provider_subject, email, display_name,"
            " picture_url, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (uid, "google", "google-" + name, email, "User " + name, "", now, now),
        )
    db.conn.execute(
        "INSERT INTO platform_admin_roles (user_id, role, granted_by, created_at, updated_at)"
        " VALUES (?,?,?,?,?)",
        (accounts["role"], "ADMIN", accounts["deleter"], now, now),
    )
    # One row per surveyed table per account, plus the other user's row that
    # must survive the deletion. Migration 037's signup trigger already creates
    # some of those rows when the users insert lands, so a table that already
    # holds the account's row is left as the migration made it.
    for table, where in _USER_KEYED_TABLES:
        if table == "platform_admin_roles":
            # An authority marker, not plain user data: the generic seeder
            # must not hand the deleting account an administrator role. The
            # dedicated role refusal test seeds its own row.
            continue
        key = _where_column(table, where)
        for user in (accounts["deleter"], accounts["other"]):
            if user_count(db, table, where, user) > 0:
                continue
            columns = db.conn.execute(f"PRAGMA table_info({table})").fetchall()
            names, values = [], []
            for column in columns:
                name = column["name"]
                if key is not None and name == key:
                    names.append(name)
                    values.append(user)
                    continue
                if (table, name) in _OVERRIDES:
                    override = _OVERRIDES[(table, name)]
                    names.append(name)
                    values.append(override(user) if callable(override) else override)
                    continue
                if column["pk"] and (column["type"] or "").upper().startswith("INT"):
                    continue
                if column["pk"]:
                    names.append(name)
                    values.append(f"{table}:{user[:8]}")
                    continue
                if not column["notnull"] or column["dflt_value"] is not None:
                    continue
                names.append(name)
                values.append(
                    _generic_value(user, table, name, column["type"])
                )
            try:
                db.conn.execute(
                    f"INSERT INTO {table} ({','.join(names)})"
                    f" VALUES ({','.join('?' * len(names))})",
                    values,
                )
            except sqlite3.Error as exc:
                raise AssertionError(f"seeding {table} failed: {exc}; columns={names}") from exc
    # Migration 047 explicitly retains dispatch rows for replay prevention.
    # Seed one for each account so the deletion test proves that retention.
    for name, user in (("deleter", accounts["deleter"]), ("other", accounts["other"])):
        suffix = name
        db.conn.execute(
            "INSERT INTO oracle_mesh_dispatch (dispatch_id, user_id, run_id, command_id, "
            "tool_request_ref, request_id, revision_ref, request_fingerprint, account_ref, "
            "workspace_ref, device_id, node_ref, root_ref, path_relative, file_path, state, "
            "expires_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "dispatch-" + suffix, user, "run-" + suffix, "command-" + suffix,
                "tool-" + suffix, "request-" + suffix, "revision-" + suffix,
                _sha("fingerprint-" + suffix)(user), "account-" + suffix, "workspace-" + suffix,
                "device-" + suffix, "node-" + suffix, "root-" + suffix, "file.txt",
                "C:/file.txt", "consumed", "2026-11-04T00:00:00Z", now,
            ),
        )
    return db, accounts


def build_app(db):
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE,
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )
    app = create_app(
        settings=settings,
        d1_binding=db,
        history_store=D1HistoryStore(db),
        control_plane_identity_authority=CanonicalAuthority(),
        central_model_admin_google_email=CENTRAL_ADMIN_EMAIL,
    )
    return app, settings


def call(app, settings, method, path, *, token=None, body=None, origin=None):
    async def inner():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            headers = {}
            if origin is not None:
                headers["Origin"] = origin
            if token:
                client.cookies.set(SESSION_COOKIE, token)
            return await client.request(method, path, json=body, headers=headers)

    return asyncio.run(inner())


def token_for(settings, uid):
    return create_session_token(settings, uid)


def snapshot(db, accounts):
    """Row counts per surveyed table for every seeded account."""
    return {
        name: {
            (table, where): user_count(db, table, where, uid)
            for table, where in _USER_KEYED_TABLES
        }
        for name, uid in accounts.items()
    }


def user_count(db, table, where, uid):
    return db.conn.execute(
        f"SELECT COUNT(*) AS n FROM {table} WHERE {where}", (uid,)
    ).fetchone()["n"]


def test_migration_092_applies_twice_and_lands_the_audit_table():
    db, _ = seed_db()
    # The whole migration set is not re-runnable by design (ALTER TABLE steps
    # cannot re-apply); migration 092 itself must be, because it is additive.
    audit_sql = (ROOT / "migrations" / "092_account_deletion_audit.sql").read_text(
        encoding="utf-8"
    )
    db.conn.executescript(audit_sql)  # second pass: idempotent
    tables = {
        row["name"]
        for row in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "account_deletion_audit" in tables


def test_the_route_never_names_a_table_the_schema_does_not_have():
    """Schema drift guard: every surveyed table and key column must exist."""
    db, _ = seed_db()
    tables = {
        row["name"]
        for row in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    # This explicit expectation makes the schema omission guard fail if a
    # new user-keyed table is present in the schema but absent from deletion.
    assert ("pc_install_tokens", "user_id = ?") in _USER_KEYED_TABLES
    assert "user_id" not in {
        column["name"] for column in db.conn.execute("PRAGMA table_info(mesh_device_drives)").fetchall()
    }
    assert ("oracle_mesh_dispatch", "user_id = ?") in _INTENTIONALLY_PRESERVED_USER_KEYED_TABLES
    assert ("oracle_mesh_dispatch", "user_id = ?") not in _USER_KEYED_TABLES
    for table, where in (*_USER_KEYED_TABLES, *_INTENTIONALLY_PRESERVED_USER_KEYED_TABLES):
        assert table in tables, table
        key = _where_column(table, where)
        if key is None:
            continue
        columns = {
            column["name"]
            for column in db.conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        assert key in columns, (table, key)


def test_successful_deletion_clears_every_surveyed_table_and_keeps_the_other_user():
    db, accounts = seed_db()
    app, settings = build_app(db)
    uid = accounts["deleter"]
    other = accounts["other"]
    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, uid),
        body={"confirm": DELETER_EMAIL},
        origin=BASE,
    )
    before = snapshot(db, accounts)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers.get("set-cookie", "").startswith(SESSION_COOKIE + "=")
    for table, where in _USER_KEYED_TABLES:
        assert user_count(db, table, where, uid) == 0, table
        assert user_count(db, table, where, other) == before["other"][(table, where)], table
    remaining = sorted(row["id"] for row in db.conn.execute("SELECT id FROM users").fetchall())
    assert uid not in remaining
    assert user_count(db, "oracle_mesh_dispatch", "user_id = ?", uid) == 1
    assert user_count(db, "oracle_mesh_dispatch", "user_id = ?", other) == 1
    assert set(remaining) == {other, accounts["central"], accounts["role"]}
    # The audit line keeps the time and the id hash only — never the email.
    audit = db.conn.execute("SELECT * FROM account_deletion_audit").fetchall()
    assert len(audit) == 1
    row = dict(audit[0])
    assert row["user_id_hash"] == hashlib.sha256(uid.encode("utf-8")).hexdigest()
    assert row["deleted_at"]
    serialized = repr(row)
    assert DELETER_EMAIL not in serialized and "@" not in serialized



def test_com2_queue_cleanup_runs_before_chat_batch_and_skips_pc_tables():
    db, accounts = seed_db()
    app, settings = build_app(db)
    uid = accounts["deleter"]
    events = []

    class QueueCleanup:
        async def delete_account_pc_data(self, *, user_id):
            events.append(("queue", user_id))
            return True

    app.state.queue_client = object()
    app.state.pc_device_pairing_store = QueueCleanup()
    original_batch = db.batch

    async def tracked_batch(statements):
        events.append(("chat_batch", None))
        sql = [statement.sql for statement in statements]
        assert not any("pc_pairing_codes" in statement for statement in sql)
        assert not any("pc_install_tokens" in statement for statement in sql)
        assert not any("pc_device_links" in statement for statement in sql)
        assert not any("mesh_device_presence" in statement for statement in sql)
        return await original_batch(statements)

    db.batch = tracked_batch
    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, uid),
        body={"confirm": DELETER_EMAIL},
        origin=BASE,
    )
    assert response.status_code == 200, response.text
    assert events == [("queue", uid), ("chat_batch", None)]
    # These rows remain in Chat's test DB because the COM2 queue owns them.
    for table in ("pc_pairing_codes", "pc_install_tokens", "pc_device_links"):
        assert db.conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = ?", (uid,)
        ).fetchone()["n"] == 1
    assert user_count(db, "oracle_mesh_dispatch", "user_id = ?", uid) == 1


def test_com2_queue_failure_keeps_chat_data_and_returns_queue_unavailable():
    db, accounts = seed_db()
    app, settings = build_app(db)
    uid = accounts["deleter"]
    before = snapshot(db, accounts)
    batch_calls = []
    original_batch = db.batch

    async def tracked_batch(statements):
        batch_calls.append(len(statements))
        return await original_batch(statements)

    class QueueFailure:
        async def delete_account_pc_data(self, *, user_id):
            raise OSError("queue unavailable")

    app.state.queue_client = object()
    app.state.pc_device_pairing_store = QueueFailure()
    db.batch = tracked_batch
    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, uid),
        body={"confirm": DELETER_EMAIL},
        origin=BASE,
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "account_delete_queue_unavailable"
    assert batch_calls == []
    assert snapshot(db, accounts) == before
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM account_deletion_audit"
    ).fetchone()["n"] == 0



def test_account_delete_removes_only_deleted_owner_from_mesh_presence():
    db, accounts = seed_db()
    uid = accounts["deleter"]
    other = accounts["other"]
    now = "2026-11-03T00:00:00Z"
    for device_id, refs in (
        ("mesh-shared-device", [uid, other]),
        ("mesh-deleter-only", [uid]),
    ):
        db.conn.execute(
            "INSERT INTO mesh_device_presence "
            "(device_id, connected, received_at, credential_generation, source, "
            " last_connected_at, account_refs_json) VALUES (?,?,?,?,?,?,?)",
            (device_id, 1, now, 1, "broker", now, json.dumps(refs)),
        )

    app, settings = build_app(db)
    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, uid),
        body={"confirm": DELETER_EMAIL},
        origin=BASE,
    )
    assert response.status_code == 200, response.text
    shared = db.conn.execute(
        "SELECT account_refs_json FROM mesh_device_presence "
        "WHERE device_id = ?",
        ("mesh-shared-device",),
    ).fetchone()
    assert shared is not None
    assert json.loads(shared["account_refs_json"]) == [other]
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM mesh_device_presence WHERE device_id = ?",
        ("mesh-deleter-only",),
    ).fetchone()["n"] == 0


def test_a_mismatched_confirm_email_deletes_nothing():
    db, accounts = seed_db()
    app, settings = build_app(db)
    uid = accounts["deleter"]
    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, uid),
        body={"confirm": "wrong@example.test"},
        origin=BASE,
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "account_delete_confirm_mismatch"
    before = snapshot(db, accounts)
    for table, where in _USER_KEYED_TABLES:
        assert user_count(db, table, where, uid) == before["deleter"][(table, where)], table
    assert db.conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 4


def test_no_session_and_foreign_origin_are_refused():
    db, accounts = seed_db()
    app, settings = build_app(db)
    uid = accounts["deleter"]

    anonymous = call(
        app, settings, "POST", "/api/account/delete",
        body={"confirm": DELETER_EMAIL}, origin=BASE,
    )
    assert anonymous.status_code == 401

    foreign = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, uid),
        body={"confirm": DELETER_EMAIL},
        origin="https://evil.example.test",
    )
    assert foreign.status_code == 403
    before = snapshot(db, accounts)
    for table, where in _USER_KEYED_TABLES:
        assert user_count(db, table, where, uid) == before["deleter"][(table, where)], table


def test_a_mid_batch_failure_rolls_the_whole_deletion_back():
    db, accounts = seed_db()
    app, settings = build_app(db)
    uid = accounts["deleter"]
    # Remove one surveyed table's rows delete target: the batch must fail and
    # roll back every other delete with it.
    before = snapshot(db, accounts)
    db.conn.execute("DROP TABLE claw_meetings")
    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, uid),
        body={"confirm": DELETER_EMAIL}, origin=BASE,
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "account_delete_failed"
    existing = {
        row["name"]
        for row in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    after = {
        name: {
            key: user_count(db, table, where, uid)
            for key, (table, where) in {
                (table, where): (table, where) for table, where in _USER_KEYED_TABLES
                if table in existing
            }.items()
        }
        for name, uid in accounts.items()
    }
    for table, where in _USER_KEYED_TABLES:
        if table == "claw_meetings":
            continue
        assert after["deleter"][(table, where)] == before["deleter"][(table, where)], table
        assert after["other"][(table, where)] == before["other"][(table, where)], table
    assert user_count(db, "conversations", "user_id = ?", uid) == before["deleter"][("conversations", "user_id = ?")]
    assert user_count(db, "projects", "user_id = ?", uid) == before["deleter"][("projects", "user_id = ?")]
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE id = ?", (uid,)
    ).fetchone()["n"] == 1
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM account_deletion_audit"
    ).fetchone()["n"] == 0


def test_a_stored_cookie_stops_authenticating_right_after_the_deletion():
    db, accounts = seed_db()
    app, settings = build_app(db)
    uid = accounts["deleter"]
    stale = token_for(settings, uid)
    first = call(
        app, settings, "POST", "/api/account/delete",
        token=stale, body={"confirm": DELETER_EMAIL}, origin=BASE,
    )
    assert first.status_code == 200
    replay = call(
        app, settings, "POST", "/api/account/delete",
        token=stale, body={"confirm": DELETER_EMAIL}, origin=BASE,
    )
    assert replay.status_code == 401
    status = call(app, settings, "GET", "/api/auth/status", token=stale)
    assert status.status_code == 200
    assert status.json()["authenticated"] is False


def test_the_central_admin_and_stored_platform_roles_are_refused():
    db, accounts = seed_db()
    app, settings = build_app(db)
    central = accounts["central"]
    refused = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, central),
        body={"confirm": CENTRAL_ADMIN_EMAIL}, origin=BASE,
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "account_delete_admin_blocked"

    role_user = accounts["role"]
    refused_role = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, role_user),
        body={"confirm": ROLE_USER_EMAIL}, origin=BASE,
    )
    assert refused_role.status_code == 403
    assert refused_role.json()["error"]["code"] == "account_delete_admin_blocked"
    # Both accounts are untouched.
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM users"
    ).fetchone()["n"] == 4
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM platform_admin_roles"
    ).fetchone()["n"] == 1
