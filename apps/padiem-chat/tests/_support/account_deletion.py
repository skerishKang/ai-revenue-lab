"""#8061 23차: shared setup for the account deletion tests."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sqlite3
import time
import uuid
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
from app.local_r2 import LocalDiskR2
from app.config import Settings
from app.history import D1HistoryStore, _password_user_id, _user_id
from app.main import create_app
from app.pc_device_pairing_store import D1PcPairingStore

from _support.account_isolation_sweep import apply_all_migrations


BASE = "https://chat.example.test"

SESSION_SECRET = "account-delete-test-session-secret-not-real-000000"

CENTRAL_ADMIN_EMAIL = "central-admin@example.test"

DELETER_EMAIL = "owner@example.test"

OTHER_EMAIL = "other@example.test"

ROLE_USER_EMAIL = "role-admin@example.test"

ROOT = Path(__file__).resolve().parents[2]

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
    ("document_convert_scan_pages", "kind"): "scan",
    ("document_convert_scan_pages", "status"): "pending",
    ("document_convert_scan_pages", "page_number"): 1,
    ("document_convert_scan_pages", "item_id"): lambda user: "item:" + user,
    ("pc_pairing_codes", "issued_at"): "2026-11-03T00:00:00Z",
    ("pc_pairing_codes", "expires_at"): "2026-11-04T00:00:00Z",
    ("padiem_account_model_selections", "tier"): "free",
    ("claw_web_xlsx_quote_write_pauses", "status"): "dispatching",
    # #7557: usage counters keyed by the account, and one Android handoff.
    ("live_usage_buckets", "subject_type"): "user",
    ("live_usage_buckets", "bucket_type"): "day",
    ("live_usage_buckets", "bucket_start"): "2026-11-12",
    ("padiem_android_auth_handoffs", "status"): "awaiting_confirmation",
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
    ("lovetree_login_handoffs", "product_id"): "lovetree-4-0",
    ("lovetree_login_handoffs", "recipient"): "lovetree-auth-caller",
    ("lovetree_login_handoffs", "state_sha256"): _sha("lt-state"),
    ("lovetree_login_handoffs", "return_origin"): "https://lovetree.example",
    ("lovetree_login_handoffs", "status"): "ready",
    ("lovetree_login_handoffs", "auth_provider"): "google",
    ("lovetree_login_handoffs", "provider_subject"): "shared:seed-subject",
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
    ("pc_helper_maintenance_jobs", "claim_token"): lambda user: "claim:" + user,
    ("pc_helper_maintenance_jobs", "action"): "refresh",
    ("pc_helper_maintenance_jobs", "status"): "queued",
    ("password_reset_audit", "event"): "requested",
    ("padiem_mcp_approvals", "arguments_json"): "{}",
    ("padiem_mcp_approvals", "status"): "pending",
    ("padiem_pc_delegations", "settings_json"): "{}",
    ("auth_validation_cache", "kind"): "legacy",
    ("control_plane_identity_shadow", "session_state"): "active",
    ("claw_execute_receipts", "state"): "pending",
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

def build_app(db, *, authority=None, rpc_transport=None, password_rpc_secret=None):
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE,
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
        lovetree_account_delete_url="https://lovetree.example/internal/account/delete",
        account_delete_rpc_secret="chat-test-shared-account-delete-secret-value-000",
        password_rpc_secret=password_rpc_secret,
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
    return create_session_token(settings, uid, canonical_session_id="session_test_a")

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

def _pending_shared_complete_rows(db):
    return [
        dict(row)
        for row in db.conn.execute(
            "SELECT item_id, kind, target, attempts FROM account_deletion_cleanup_pending"
            " WHERE kind = 'shared_account_complete'"
        ).fetchall()
    ]

PASSWORD_RPC_SECRET = "chat-test-password-rpc-secret-value-000000"

def _signed_internal_delete_call(
    app,
    payload: dict | bytes,
    *,
    secret: str = PASSWORD_RPC_SECRET,
    at: int | None = None,
    service_id: str | None = None,
    proof: str | None = None,
):
    at_val = int(time.time()) if at is None else at
    sid = str(uuid.uuid4()) if service_id is None else service_id
    raw_body = (
        payload
        if isinstance(payload, bytes)
        else json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signed = b"\n".join(
        (b"v2", b"POST", b"/internal/account-delete", str(at_val).encode("ascii"), sid.encode("utf-8"), raw_body)
    )
    computed = "v2=" + hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    headers = {
        "content-type": "application/json",
        "x-padiem-service-at": str(at_val),
        "x-padiem-service-id": sid,
        "x-padiem-service-proof": computed if proof is None else proof,
    }

    async def inner():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            return await client.post("/internal/account-delete", content=raw_body, headers=headers)

    return asyncio.run(inner())
