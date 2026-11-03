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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.account_deletion import (
    _IDENTITY_SCRUBBED_USER_KEYED_TABLES,
    _USER_KEYED_TABLES,
    prune_expired_account_deletion_audit,
)
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.history import D1HistoryStore, _password_user_id, _user_id
from app.main import create_app
from app.pc_device_pairing_store import D1PcPairingStore

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
    def __init__(self):
        self.links = []
        self.removed = []
        self.revoked = []
        self.fail_remove = False

    async def revoke_auth_session(self, *, product_id, session_id):
        self.revoked.append((product_id, session_id))
        return None

    async def list_active_product_links_for_subject(self, *, canonical_subject_id):
        return [dict(link) for link in self.links]

    async def remove_product_link(
        self, *, product_id, product_user_id, canonical_subject_id,
        account_deletion_operation_id=None,
    ):
        if self.fail_remove:
            raise RuntimeError('synthetic authority failure')
        match = next((link for link in self.links
                      if link['product_id'] == product_id and link['product_user_id'] == product_user_id), None)
        if match is None:
            return {'removed': False, 'common_account_deleted': not self.links}
        self.links.remove(match)
        self.removed.append((product_id, product_user_id, canonical_subject_id))
        return {
            'removed': True,
            'remaining_links': len(self.links),
            'common_account_deleted': len(self.links) == 0,
            'revoked_sessions': 1,
            'already_deleted': False,
        }


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
    # Migration 047 explicitly retains dispatch rows for replay prevention,
    # and the deletion now keeps the row while removing the account from it.
    # Seed one for each account so the tests prove both halves.
    for name, user in (("deleter", accounts["deleter"]), ("other", accounts["other"])):
        suffix = name
        db.conn.execute(
            "INSERT INTO oracle_mesh_dispatch (dispatch_id, user_id, run_id, command_id, "
            "tool_request_ref, request_id, revision_ref, request_fingerprint, account_ref, "
            "workspace_ref, device_id, node_ref, root_ref, path_relative, file_path, kind, "
            "command_text, state, expires_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "dispatch-" + suffix, user, "run-" + suffix, "command-" + suffix,
                "tool-" + suffix, "request-" + suffix, "revision-" + suffix,
                _sha("fingerprint-" + suffix)(user), "account-" + suffix, "workspace-" + suffix,
                "device-" + suffix, "node-" + suffix, "root-" + suffix, "file.txt",
                "C:/file.txt", "command", "echo hello",
                "consumed", "2026-11-04T00:00:00Z", now,
            ),
        )
    return db, accounts


def build_app(db, *, authority=None, rpc_transport=None):
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE,
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
        lovetree_account_delete_url="https://lovetree.example/internal/account/delete",
        account_delete_rpc_secret="chat-test-shared-account-delete-secret-value-000",
    )
    async def default_rpc_transport(**kwargs):
        payload = {"ok": True, "deleted": True}
        if kwargs["path"] == "/internal/account-delete/prepare":
            payload = {"ok": True, "prepared": True, "revoked_sessions": 2}
        return SimpleNamespace(status_code=200, json=lambda: payload)
    app = create_app(
        settings=settings,
        d1_binding=db,
        history_store=D1HistoryStore(db),
        control_plane_identity_authority=authority or CanonicalAuthority(),
        central_model_admin_google_email=CENTRAL_ADMIN_EMAIL,
        account_delete_rpc_transport=rpc_transport or default_rpc_transport,
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
    compact_sql = (ROOT / "migrations" / "097_account_deletion_audit_hash_time_only.sql").read_text(
        encoding="utf-8"
    )
    db.conn.executescript(compact_sql)
    columns = [
        row["name"]
        for row in db.conn.execute("PRAGMA table_info(account_deletion_audit)").fetchall()
    ]
    assert columns == ["user_id_hash", "deleted_at"]
    db.conn.executescript(compact_sql)
    assert [
        row["name"]
        for row in db.conn.execute("PRAGMA table_info(account_deletion_audit)").fetchall()
    ] == ["user_id_hash", "deleted_at"]


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
    # The MCP job receipt is a hash column on the existing audit table, so the
    # established account-keyed deletion removes it with the rest of the audit.
    assert ("padiem_mcp_audit", "user_id = ?") in _USER_KEYED_TABLES
    assert "user_id" not in {
        column["name"] for column in db.conn.execute("PRAGMA table_info(mesh_device_drives)").fetchall()
    }
    assert ("oracle_mesh_dispatch", "user_id = ?") in _IDENTITY_SCRUBBED_USER_KEYED_TABLES
    assert ("oracle_mesh_dispatch", "user_id = ?") not in _USER_KEYED_TABLES
    for table, where in (*_USER_KEYED_TABLES, *_IDENTITY_SCRUBBED_USER_KEYED_TABLES):
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
    audit_columns = {
        row["name"] for row in db.conn.execute("PRAGMA table_info(padiem_mcp_audit)").fetchall()
    }
    assert "job_receipt_sha256" in audit_columns
    db.conn.execute(
        "INSERT INTO padiem_mcp_audit "
        "(id,user_id,token_id,device_id,tool_name,request_digest,status,created_at,job_receipt_sha256) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("mcp-event-job-receipt", uid, "mcp-token-hash", "device-hash",
         "pc_shell_start", "a" * 64, "running", "2026-11-03T00:00:00Z", "b" * 64),
    )
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
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM padiem_mcp_audit WHERE user_id = ?", (uid,)
    ).fetchone()["n"] == 0
    remaining = sorted(row["id"] for row in db.conn.execute("SELECT id FROM users").fetchall())
    assert uid not in remaining
    # Replay-prevention rows stay — one per account — but the deleting
    # account's row no longer names the account or the PC work behind it.
    assert user_count(db, "oracle_mesh_dispatch", "user_id = ?", uid) == 0
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM oracle_mesh_dispatch"
    ).fetchone()["n"] == 2
    _assert_dispatch_scrubbed(
        _dispatch(db, "dispatch-deleter"),
        run_id="run-deleter",
        fingerprint=_sha("fingerprint-deleter")(uid),
        state="consumed",
    )
    other_dispatch = _dispatch(db, "dispatch-other")
    assert other_dispatch["user_id"] == other
    assert other_dispatch["account_ref"] == "account-other"
    assert other_dispatch["command_text"] == "echo hello"
    assert set(remaining) == {other, accounts["central"], accounts["role"]}
    # The audit line keeps the time and the id hash only — never the email.
    audit = db.conn.execute("SELECT * FROM account_deletion_audit").fetchall()
    assert len(audit) == 1
    columns = [item["name"] for item in db.conn.execute("PRAGMA table_info(account_deletion_audit)").fetchall()]
    assert columns == ["user_id_hash", "deleted_at"]
    row = dict(audit[0])
    assert row["user_id_hash"] == hashlib.sha256(uid.encode("utf-8")).hexdigest()
    assert row["deleted_at"]
    serialized = repr(row)
    assert DELETER_EMAIL not in serialized and "@" not in serialized



# ---------------------------------------------------------------------------
# (j) Replay-prevention dispatch rows stay, without the account in them.
# ---------------------------------------------------------------------------


def _dispatch(db, dispatch_id):
    row = db.conn.execute(
        "SELECT * FROM oracle_mesh_dispatch WHERE dispatch_id = ?", (dispatch_id,)
    ).fetchone()
    return dict(row) if row is not None else None


def _assert_dispatch_scrubbed(row, *, run_id, fingerprint, state):
    """One random token replaces every identifier; paths and body are gone."""
    assert row is not None
    assert row["user_id"].startswith("deleted:")
    assert row["account_ref"] == row["user_id"]
    assert row["workspace_ref"] == row["user_id"]
    assert row["device_id"] == row["user_id"]
    assert row["node_ref"] == row["user_id"]
    assert row["root_ref"] == row["user_id"]
    assert row["binding_ref"] == row["user_id"]
    assert row["path_relative"] == "deleted"
    assert row["file_path"] == "deleted"
    assert row["evidence_ref"] is None
    assert row["command_text"] is None
    # The replay-prevention keys are byte-for-byte untouched.
    assert row["run_id"] == run_id
    assert row["request_fingerprint"] == fingerprint
    assert row["state"] == state


_PENDING_DISPATCH_INSERT = (
    "INSERT INTO oracle_mesh_dispatch (dispatch_id, user_id, run_id, command_id, "
    "tool_request_ref, request_id, revision_ref, request_fingerprint, account_ref, "
    "workspace_ref, device_id, node_ref, root_ref, path_relative, file_path, kind, "
    "command_text, nonce_sha256, state, expires_at, created_at) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


def _seed_pending_dispatch(db, user, *, dispatch_id, run_id, nonce=None):
    db.conn.execute(
        _PENDING_DISPATCH_INSERT,
        (
            dispatch_id, user, run_id, "command-" + run_id, "tool-" + run_id,
            "request-" + run_id, "revision-" + run_id, _sha(run_id)(user),
            "account:seed", "workspace:seed", "device:seed", "node:seed",
            "root:seed", "notes.md", "C:/Users/seed/notes.md", "command",
            "dir C:/Users/seed", nonce, "pending", "2026-11-05T00:00:00Z",
            "2026-11-03T00:00:00Z",
        ),
    )


def test_the_queue_cleanup_makes_dispatch_rows_anonymous_and_keeps_replay_prevention():
    db, accounts = seed_db()
    uid = accounts["deleter"]
    assert asyncio.run(
        D1PcPairingStore(db).delete_account_pc_data(user_id=uid)
    ) is True
    row = _dispatch(db, "dispatch-deleter")
    _assert_dispatch_scrubbed(
        row,
        run_id="run-deleter",
        fingerprint=_sha("fingerprint-deleter")(uid),
        state="consumed",
    )
    # The other account's row is untouched, command body included.
    other_row = _dispatch(db, "dispatch-other")
    assert other_row["user_id"] == accounts["other"]
    assert other_row["account_ref"] == "account-other"
    assert other_row["command_text"] == "echo hello"
    assert other_row["file_path"] == "C:/file.txt"
    # Replay prevention survives: the same run cannot be staged again under the
    # scrubbed identity, because 047's run-scope index still holds the row.
    with pytest.raises(sqlite3.IntegrityError):
        _seed_pending_dispatch(
            db, row["user_id"], dispatch_id="dispatch-replay", run_id="run-deleter"
        )


def test_a_deleted_accounts_queued_command_never_runs_and_a_claimed_one_still_lands():
    db, accounts = seed_db()
    uid = accounts["deleter"]
    _seed_pending_dispatch(db, uid, dispatch_id="dispatch-queued", run_id="run-queued")
    _seed_pending_dispatch(
        db, uid, dispatch_id="dispatch-claimed", run_id="run-claimed", nonce="a" * 64
    )
    assert asyncio.run(
        D1PcPairingStore(db).delete_account_pc_data(user_id=uid)
    ) is True

    queued = _dispatch(db, "dispatch-queued")
    # Never seen by an executor: it must not be handed out for an account that
    # no longer exists, so it leaves the pending set entirely.
    assert queued["state"] == "failed"
    assert queued["termination"] == "cancelled"
    _assert_dispatch_scrubbed(
        queued,
        run_id="run-queued",
        fingerprint=_sha("run-queued")(uid),
        state="failed",
    )

    claimed = _dispatch(db, "dispatch-claimed")
    # Already handed out: the result can still land through the existing nonce
    # gate, so the state stays pending and only the termination says stop.
    assert claimed["state"] == "pending"
    assert claimed["termination"] == "cancelled"
    assert claimed["nonce_sha256"] == "a" * 64
    _assert_dispatch_scrubbed(
        claimed,
        run_id="run-claimed",
        fingerprint=_sha("run-claimed")(uid),
        state="pending",
    )
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM oracle_mesh_dispatch WHERE state = 'pending'"
    ).fetchone()["n"] == 1


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
    # Dispatch rows belong to the queue DB on COM2, so the Chat batch leaves
    # them to the queue cleanup; this row still names the account here.
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


# ---------------------------------------------------------------------------
# (k) BookAI records follow the account (2026-11-03). The mapping is the
# common-login subject: durable in users.provider_subject for shared logins,
# transient in auth_account_link_cache for a session that resolved it.
# ---------------------------------------------------------------------------

BOOKAI_SUBJECT = "sub_" + "a" * 32
OTHER_BOOKAI_SUBJECT = "sub_" + "b" * 32


def _seed_bookai(db, subject, record_id):
    db.conn.execute(
        "INSERT INTO bookai_records (subject, record_id, book_id, locator, kind,"
        " payload, updated_at, deleted) VALUES (?,?,?,?,?,?,?,?)",
        (subject, record_id, "book-1", "loc:1", "progress", '{"chapter":1}', 1762000000000, 0),
    )


def _bookai_rows(db, subject):
    return db.conn.execute(
        "SELECT COUNT(*) AS n FROM bookai_records WHERE subject = ?", (subject,)
    ).fetchone()["n"]


def test_a_shared_login_account_takes_its_bookai_records_with_it():
    db, accounts = seed_db()
    uid = accounts["deleter"]
    db.conn.execute(
        "UPDATE users SET provider_subject = ? WHERE id = ?",
        ("shared:" + BOOKAI_SUBJECT, uid),
    )
    _seed_bookai(db, BOOKAI_SUBJECT, "rec-1")
    _seed_bookai(db, BOOKAI_SUBJECT, "rec-2")
    _seed_bookai(db, OTHER_BOOKAI_SUBJECT, "rec-other")
    app, settings = build_app(db)
    app.state.control_plane_identity_authority.links = [
        {"product_id": "b62", "product_user_id": uid, "state": "active"}
    ]

    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, uid),
        body={"confirm": DELETER_EMAIL},
        origin=BASE,
    )

    assert response.status_code == 200, response.text
    assert _bookai_rows(db, BOOKAI_SUBJECT) == 0
    assert _bookai_rows(db, OTHER_BOOKAI_SUBJECT) == 1
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE id = ?", (uid,)
    ).fetchone()["n"] == 0


def test_the_link_cache_mapping_is_read_before_revocation():
    db, accounts = seed_db()
    uid = accounts["deleter"]
    # No shared marker on the users row: only the transient link cache names the
    # subject, and the session revocation is what deletes that row.
    db.conn.execute(
        "INSERT INTO auth_account_link_cache (owner_id, product_user_id, valid_until)"
        " VALUES (?,?,?)",
        (BOOKAI_SUBJECT, uid, 4102444800.0),
    )
    _seed_bookai(db, BOOKAI_SUBJECT, "rec-cache")
    app, settings = build_app(db)

    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, uid),
        body={"confirm": DELETER_EMAIL},
        origin=BASE,
    )

    assert response.status_code == 200, response.text
    assert _bookai_rows(db, BOOKAI_SUBJECT) == 0
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM auth_account_link_cache WHERE product_user_id = ?", (uid,)
    ).fetchone()["n"] == 0


def test_a_google_only_account_leaves_unattributable_bookai_records():
    db, accounts = seed_db()
    uid = accounts["deleter"]
    _seed_bookai(db, BOOKAI_SUBJECT, "rec-unmapped")
    app, settings = build_app(db)

    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, uid),
        body={"confirm": DELETER_EMAIL},
        origin=BASE,
    )

    assert response.status_code == 200, response.text
    # Nothing ties this subject to the account, so it is not deleted on a guess.
    assert _bookai_rows(db, BOOKAI_SUBJECT) == 1


def test_bookai_subjects_accept_only_canonical_subjects():
    from app.account_deletion import bookai_subjects

    assert bookai_subjects("shared:" + BOOKAI_SUBJECT) == (BOOKAI_SUBJECT,)
    assert bookai_subjects("google-abc123") == ()
    assert bookai_subjects(None) == ()
    assert bookai_subjects("shared:not-a-subject") == ()
    assert bookai_subjects(None, ["not-a-subject", "", BOOKAI_SUBJECT]) == (BOOKAI_SUBJECT,)
    assert bookai_subjects("shared:" + BOOKAI_SUBJECT, [BOOKAI_SUBJECT]) == (BOOKAI_SUBJECT,)

def test_the_link_read_reports_absence_but_never_swallows_a_failure():
    import asyncio

    from app.account_deletion import _account_link_subjects, bookai_subjects

    db, accounts = seed_db()
    uid = accounts["deleter"]
    db.conn.execute(
        "INSERT INTO auth_account_link_cache (owner_id, product_user_id, valid_until)"
        " VALUES (?,?,?)",
        (BOOKAI_SUBJECT, uid, 4102444800.0),
    )
    owners = asyncio.run(_account_link_subjects(db, uid))
    assert BOOKAI_SUBJECT in owners
    # The shared seeder also writes a generic owner id for this table. The
    # subject filter drops it, so it can never become a delete target.
    assert bookai_subjects(None, owners) == (BOOKAI_SUBJECT,)

    # A host behind on migration 088 has no link table: that is absence.
    db.conn.execute("DROP TABLE auth_account_link_cache")
    assert asyncio.run(_account_link_subjects(db, uid)) == []

    class Broken:
        def prepare(self, _sql):
            raise RuntimeError("storage fault")

        async def read(self):
            return await _account_link_subjects(self, uid)

    # Anything else is a real failure and must reach the caller.
    try:
        asyncio.run(Broken().read())
    except RuntimeError:
        pass
    else:  # pragma: no cover - the failure path is the point
        raise AssertionError("a storage fault was reported as an absence")


def _bind_shared_links(db, app, user_id, *, include_lovetree):
    subject = "sub_shared_delete"
    db.conn.execute("UPDATE users SET provider_subject=? WHERE id=?", ("shared:" + subject, user_id))
    authority = app.state.control_plane_identity_authority
    authority.links = [
        {"product_id": "b62", "product_user_id": user_id, "state": "active"}
    ]
    if include_lovetree:
        authority.links.append({
            "product_id": "lovetree-4-0",
            "product_user_id": "usr_lovetree_shared",
            "state": "active",
        })
    return subject, authority


def test_shared_chat_unlink_keeps_lovetree_and_does_not_prepare_auth_while_another_link_remains():
    db, accounts = seed_db()
    app, settings = build_app(db)
    user_id = accounts["deleter"]
    _, authority = _bind_shared_links(db, app, user_id, include_lovetree=True)
    rpc_paths = []
    async def transport(**kwargs):
        rpc_paths.append(kwargs["path"])
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "prepared": True, "revoked_sessions": 0})

    app.state.account_delete_rpc_transport = transport
    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, user_id), body={"confirm": DELETER_EMAIL}, origin=BASE,
    )
    assert response.status_code == 200
    assert response.json()["common_account_deleted"] is False
    assert [link["product_id"] for link in authority.links] == ["lovetree-4-0"]
    assert rpc_paths == []


def test_last_chat_link_prepares_auth_then_deletes_common_account_and_hash_only_audit():
    db, accounts = seed_db()
    app, settings = build_app(db)
    user_id = accounts["deleter"]
    subject, authority = _bind_shared_links(db, app, user_id, include_lovetree=False)
    rpc_paths = []
    async def transport(**kwargs):
        rpc_paths.append(kwargs["path"])
        payload = (
            {"ok": True, "prepared": True, "revoked_sessions": 2}
            if kwargs["path"] == "/internal/account-delete/prepare"
            else {"ok": True, "deleted": True}
        )
        return SimpleNamespace(status_code=200, json=lambda: payload)

    app.state.account_delete_rpc_transport = transport
    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, user_id), body={"confirm": DELETER_EMAIL}, origin=BASE,
    )
    assert response.status_code == 200
    assert response.json()["common_account_deleted"] is True
    assert authority.links == []
    assert rpc_paths == ["/internal/account-delete/prepare", "/internal/account-delete/complete"]
    assert authority.removed == [("b62", user_id, subject)]
    columns = [row["name"] for row in db.conn.execute("PRAGMA table_info(account_deletion_audit)").fetchall()]
    assert columns == ["user_id_hash", "deleted_at"]
    audit = db.conn.execute("SELECT user_id_hash,deleted_at FROM account_deletion_audit").fetchone()
    assert audit["user_id_hash"] == hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    assert audit["deleted_at"]


def test_full_shared_delete_calls_lovetree_before_chat_and_auth_before_the_last_link():
    db, accounts = seed_db()
    app, settings = build_app(db)
    user_id = accounts["deleter"]
    _, authority = _bind_shared_links(db, app, user_id, include_lovetree=True)
    rpc_paths = []
    async def transport(**kwargs):
        rpc_paths.append(kwargs["path"])
        payload = {"ok": True, "deleted": True}
        if kwargs["path"] == "/internal/account-delete/prepare":
            payload = {"ok": True, "prepared": True, "revoked_sessions": 2}
        return SimpleNamespace(status_code=200, json=lambda: payload)

    app.state.account_delete_rpc_transport = transport
    response = call(
        app, settings, "POST", "/api/account/shared-delete",
        token=token_for(settings, user_id), body={"confirm": DELETER_EMAIL}, origin=BASE,
    )
    assert response.status_code == 200
    assert response.json()["common_account_deleted"] is True
    assert authority.links == []
    assert rpc_paths == [
        "/internal/account/delete",
        "/internal/account-delete/prepare",
        "/internal/account-delete/complete",
    ]


def test_failure_before_chat_deletion_keeps_all_service_links_and_chat_rows():
    db, accounts = seed_db()
    app, settings = build_app(db)
    user_id = accounts["deleter"]
    _bind_shared_links(db, app, user_id, include_lovetree=True)
    async def transport(**kwargs):
        return SimpleNamespace(status_code=503, json=lambda: {"ok": False})

    app.state.account_delete_rpc_transport = transport
    response = call(
        app, settings, "POST", "/api/account/shared-delete",
        token=token_for(settings, user_id), body={"confirm": DELETER_EMAIL}, origin=BASE,
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "shared_account_service_unavailable"
    assert db.conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone() is not None
    assert len(app.state.control_plane_identity_authority.links) == 2


def test_cp_unlink_failure_keeps_common_account_link_after_local_chat_data_deletion():
    db, accounts = seed_db()
    app, settings = build_app(db)
    user_id = accounts["deleter"]
    _, authority = _bind_shared_links(db, app, user_id, include_lovetree=False)
    authority.fail_remove = True
    rpc_paths = []
    async def transport(**kwargs):
        rpc_paths.append(kwargs["path"])
        if kwargs["path"] == "/internal/account-delete/prepare":
            payload = {"ok": True, "prepared": True, "revoked_sessions": 1}
        else:
            payload = {"ok": True, "aborted": True}
        return SimpleNamespace(status_code=200, json=lambda: payload)

    app.state.account_delete_rpc_transport = transport
    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, user_id), body={"confirm": DELETER_EMAIL}, origin=BASE,
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "shared_account_unlink_failed"
    assert len(authority.links) == 1
    assert rpc_paths == ["/internal/account-delete/prepare", "/internal/account-delete/abort"]
    assert db.conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone() is None


def test_account_deletion_audit_retention_prunes_after_365_days():
    db = SqliteD1()
    db.conn.execute(
        "CREATE TABLE account_deletion_audit (user_id_hash TEXT PRIMARY KEY, deleted_at TEXT NOT NULL)"
    )
    now = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
    expired = (now - timedelta(days=365)).isoformat()
    recent = (now - timedelta(days=364)).isoformat()
    db.conn.execute("INSERT INTO account_deletion_audit VALUES (?,?)", ("a" * 64, expired))
    db.conn.execute("INSERT INTO account_deletion_audit VALUES (?,?)", ("b" * 64, recent))

    removed = asyncio.run(prune_expired_account_deletion_audit(db, now=now))

    assert removed == 1
    rows = db.conn.execute("SELECT user_id_hash,deleted_at FROM account_deletion_audit").fetchall()
    assert len(rows) == 1
    assert rows[0]["user_id_hash"] == "b" * 64


def test_account_help_describes_both_deletion_paths_and_keeps_brand_wording_guard():
    app_root = Path(__file__).resolve().parents[1]
    help_text = (app_root / "static" / "help.html").read_text(encoding="utf-8")
    section = help_text.split('id="account"', 1)[1].split('id="faq"', 1)[0]
    html = (app_root / "static" / "index.html").read_text(encoding="utf-8")
    script = (app_root / "static" / "app.js").read_text(encoding="utf-8")

    assert "이 서비스에서 탈퇴" in section
    assert "모든 서비스에서 탈퇴" in section
    assert "마지막 연결" in section
    assert "세션" in section
    assert "CGI 쇼핑몰" in section
    assert "PADIEM" not in help_text
    assert 'id="accountSharedDeleteOpen"' in html
    assert 'id="accountSharedDeleteConfirm"' in html
    assert '"/api/account/shared-delete"' in script
