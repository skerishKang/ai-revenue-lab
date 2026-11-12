"""#7557: account deletion leaves nothing behind — R2 objects, Google grants, counters.

Before the fix a withdrawal answered ``ok: true`` while these survived:

* R2 objects whose keys no metadata row named — long message originals and PC
  screenshots (``claw-model-context/v1/<conversation>/``), chat attachments
  (``chat-attachments/<user>/``), project originals, document-conversion
  outputs, certified B66 bundles and the MCP browser-continuity object;
* every Google connector grant of the account's workspace (refresh token rows,
  sealed, and never revoked at Google);
* ``live_usage_buckets`` (a re-signup inherited the old usage) and
  ``padiem_android_auth_handoffs``;
* anything a failed object delete skipped — failures were swallowed.

The flow runs through the real HTTP route on the shared deletion harness. The
object store is a real disk store in a temporary directory, and the Google
OAuth authority behind the fake RPC binding is the real Control Plane purge
runtime over its real store; only the sealer and Google's revoke endpoint are
fakes. Nothing here reaches R2 or Google.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

from app.calendar_session_authority import CalendarSession
from app.connector_workspace_truth import CloudflareGoogleOAuthWorkspaceTruth
from app.local_r2 import LocalDiskR2

from test_account_deletion_261103 import (
    BASE,
    DELETER_EMAIL,
    CanonicalAuthority,
    build_app,
    call,
    seed_db,
    snapshot,
    token_for,
)

CP_ROOT = Path(__file__).resolve().parents[3] / "packages" / "padiem-control-plane"
NOW = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)
WORKSPACE = "workspace.deleter.1"
OTHER_WORKSPACE = "workspace.other.1"


# ---------------------------------------------------------------------------
# Google: the real Control Plane purge behind a fake RPC binding.
# ---------------------------------------------------------------------------


class _Sealer:
    async def unseal_text(self, *, envelope, context):
        return "refresh-" + context.record_ref


class _GoogleRevoke:
    """Google's revoke endpoint. ``down`` > 0 fails that many calls first."""

    def __init__(self, down: int = 0):
        self.tokens: list[str] = []
        self.down = down

    async def revoke_token(self, *, token):
        self.tokens.append(token)
        if self.down > 0:
            self.down -= 1
            raise RuntimeError("google unavailable")
        return "revoked"


class _Cursor:
    def __init__(self, rows):
        self._rows, self.rowsWritten = rows, 0

    def toArray(self):
        return list(self._rows)


class _DurableObjectStorage:
    """The Durable Object SQLite surface the OAuth store needs, over sqlite3."""

    def __init__(self):
        import sqlite3

        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        storage = self

        class _Sql:
            def exec(self, statement, *args):
                cursor = storage.connection.execute(statement, args)
                rows = []
                if statement.lstrip().upper().startswith("SELECT"):
                    columns = [item[0] for item in cursor.description or ()]
                    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
                return _Cursor(rows)

        self.sql = _Sql()

    def transactionSync(self, operation):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            result = operation()
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return result

    def scalar(self, statement, *args):
        return self.connection.execute(statement, args).fetchone()[0]


class GoogleAuthority:
    """The state Worker as Chat sees it: one RPC method over a real store."""

    def __init__(self, revoke: _GoogleRevoke):
        if str(CP_ROOT) not in sys.path:
            sys.path.insert(0, str(CP_ROOT))
        from google_oauth_durable_store import (
            GMAIL_READONLY_SCOPE,
            GOOGLE_DRIVE_READONLY_SCOPE,
            DurableGoogleOAuthCredential,
        )
        from google_oauth_persisted_store import CloudflareDurableGoogleOAuthStore
        from google_oauth_workspace_purge import GoogleOAuthWorkspacePurgeRuntime

        self.storage = _DurableObjectStorage()
        self.store = CloudflareDurableGoogleOAuthStore(self.storage)
        for binding, workspace, connector, scopes in (
            ("bind.gmail", WORKSPACE, "gmail", (GMAIL_READONLY_SCOPE,)),
            ("bind.drive", WORKSPACE, "google-drive", (GOOGLE_DRIVE_READONLY_SCOPE,)),
            ("bind.other", OTHER_WORKSPACE, "gmail", (GMAIL_READONLY_SCOPE,)),
        ):
            self.store.save_credential(DurableGoogleOAuthCredential(
                binding_ref=binding, connector_id=connector, actor_ref="actor.1",
                account_ref="account.1", workspace_ref=workspace, scopes=scopes,
                sealed_refresh_token="sealed:v1:" + "C" * 32,
                issued_at=NOW - timedelta(days=1),
            ))
        # The Drive grant was disconnected earlier: revoked_at only, token kept.
        self.store.revoke_credential(binding_ref="bind.drive", revoked_at=NOW - timedelta(hours=1))
        self.revoke = revoke
        self.runtime = GoogleOAuthWorkspacePurgeRuntime(
            store=self.store, sealer=_Sealer(), revoke_port=revoke, clock=lambda: NOW,
        )
        self.calls: list[dict] = []

    async def purge_workspace_credentials(self, payload):
        self.calls.append(dict(payload))
        if set(payload) != {"workspace_ref"}:
            return {"ok": False, "error": {"code": "invalid", "message": "x"}}
        return {"ok": True, **await self.runtime.purge(workspace_ref=payload["workspace_ref"])}

    def rows(self, workspace: str) -> int:
        return self.storage.scalar(
            "SELECT COUNT(*) FROM google_oauth_refresh_credential WHERE workspace_ref = ?", workspace)


class WorkspaceAuthority(CanonicalAuthority):
    def __init__(self, workspace: str | None = WORKSPACE, fail: bool = False):
        super().__init__()
        self.workspace, self.fail = workspace, fail

    async def resolve_connector_workspace(self, *, session_id):
        assert session_id == "sess_deleter"
        if self.fail:
            raise RuntimeError("identity authority down")
        return self.workspace


# ---------------------------------------------------------------------------
# R2: a real disk store, plus one that fails a chosen number of deletes.
# ---------------------------------------------------------------------------


class FlakyDiskR2(LocalDiskR2):
    def __init__(self, root, *, failures: int = 0):
        super().__init__(root)
        self.failures = failures

    def delete(self, key):
        if self.failures > 0:
            self.failures -= 1
            raise OSError("object store unavailable")
        return super().delete(key)


def _seed_objects(bucket: LocalDiskR2, db, uid: str, other: str) -> dict[str, list[str]]:
    """Objects of every family the account can own, plus the other user's."""
    from app.mcp_browser_context import _key as browser_key

    conversation = db.conn.execute(
        "SELECT id FROM conversations WHERE user_id = ?", (uid,)).fetchone()["id"]
    other_conversation = db.conn.execute(
        "SELECT id FROM conversations WHERE user_id = ?", (other,)).fetchone()["id"]
    saved_skill = db.conn.execute(
        "SELECT id FROM b66_saved_quote_skill WHERE user_id = ?", (uid,)).fetchone()["id"]
    token = db.conn.execute(
        "SELECT id, device_id FROM padiem_mcp_tokens WHERE user_id = ?", (uid,)).fetchone()
    metadata_keys = [
        db.conn.execute(f"SELECT object_key FROM {table} WHERE user_id = ?", (uid,)).fetchone()["object_key"]
        for table in ("claw_document_metadata", "b66_quote_asset", "b66_template_source")
    ]
    mine = [
        *metadata_keys,
        f"claw-model-context/v1/{conversation}/msg_{'a' * 32}.utf8",   # long message original
        f"claw-model-context/v1/{conversation}/mesh_result_1.utf8",    # PC screenshot / result
        f"chat-attachments/{uid}/file_{'b' * 32}/body",
        f"chat-attachments/{uid}/file_{'b' * 32}/meta.json",
        f"projects/{uid}/proj_1/originals/file_1",
        f"documents/{uid}/convert/job_1/item_1.md",
        f"b66/certified-quote-bundles/{saved_skill}/{'c' * 64}/bundle.zip",
        browser_key({"owner_id": uid, "token_id": token["id"], "device_id": token["device_id"]}),
    ]
    theirs = [
        f"claw-model-context/v1/{other_conversation}/msg_{'d' * 32}.utf8",
        f"chat-attachments/{other}/file_{'e' * 32}/body",
        f"projects/{other}/proj_2/originals/file_2",
        f"documents/{other}/convert/job_2/item_2.md",
    ]
    for key in mine + theirs:
        bucket.put(key, b"private bytes")
    return {"mine": mine, "theirs": theirs}


def _existing(bucket: LocalDiskR2, keys) -> list[str]:
    return [key for key in keys if bucket.get(key) is not None]


def _deleter_dirs(root: Path, uid: str) -> list[Path]:
    return [path for path in root.rglob("*") if uid in path.name]


def _session(monkeypatch, *, reason=None):
    from app import calendar_session_authority

    async def resolve(request, *, path, user_id=None):
        assert path == "account_delete"
        if reason is not None:
            return CalendarSession(path=path, reason=reason)
        return CalendarSession(path=path, session_id="sess_deleter", product_id="b62",
                               subject_present=True, reason=None)

    monkeypatch.setattr(calendar_session_authority, "resolve_calendar_session", resolve)


def _app(tmp_path, *, bucket=None, authority=None, revoke=None):
    db, accounts = seed_db()
    authority = authority or WorkspaceAuthority()
    app, settings = build_app(db, authority=authority)
    bucket = bucket or LocalDiskR2(tmp_path / "objects")
    google = GoogleAuthority(revoke or _GoogleRevoke())
    app.state.workspace_document_store = type("Store", (), {"r2_bucket": bucket})()
    app.state.identity_shadow_store = object()
    app.state.google_oauth_workspace_truth = CloudflareGoogleOAuthWorkspaceTruth(google)
    app.state.file_lane_client = None
    objects = _seed_objects(bucket, db, accounts["deleter"], accounts["other"])
    db.conn.execute(
        "INSERT OR IGNORE INTO live_usage_buckets (subject_type, subject_key, bucket_type, bucket_start,"
        " request_count, updated_at) VALUES ('user', ?, 'day', '2026-11-12', 40, '2026-11-12')",
        (accounts["deleter"],))
    return db, accounts, app, settings, bucket, google, objects


def _delete(app, settings, uid):
    return call(app, settings, "POST", "/api/account/delete", token=token_for(settings, uid),
                body={"confirm": DELETER_EMAIL}, origin=BASE)


def _pending(db) -> int:
    row = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE name = 'account_deletion_cleanup_pending'").fetchone()
    if row is None:
        return 0
    return db.conn.execute("SELECT COUNT(*) AS n FROM account_deletion_cleanup_pending").fetchone()["n"]


# ---------------------------------------------------------------------------
# 1. Nothing of the account is left in any store.
# ---------------------------------------------------------------------------


def test_after_deletion_no_store_holds_the_accounts_data(tmp_path, monkeypatch):
    _session(monkeypatch)
    db, accounts, app, settings, bucket, google, objects = _app(tmp_path)
    uid = accounts["deleter"]
    assert _existing(bucket, objects["mine"]) == objects["mine"]

    response = _delete(app, settings, uid)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body.get("cleanup") == {"complete": True, "pending": 0}
    assert "message" not in body
    # R2: every family of the account is gone, the other user's objects stay.
    assert _existing(bucket, objects["mine"]) == []
    assert _existing(bucket, objects["theirs"]) == objects["theirs"]
    assert _deleter_dirs(bucket.root, uid) == []
    # Google: both grants of the workspace were revoked at Google — including
    # the one an earlier disconnect only marked — and their rows are gone.
    assert google.calls == [{"workspace_ref": WORKSPACE}]
    assert sorted(google.revoke.tokens) == ["refresh-bind.drive", "refresh-bind.gmail"]
    assert google.rows(WORKSPACE) == 0
    assert google.rows(OTHER_WORKSPACE) == 1
    # Counters: a re-signup of the same identity starts from zero.
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM live_usage_buckets WHERE subject_key = ?", (uid,)
    ).fetchone()["n"] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM padiem_android_auth_handoffs WHERE pending_user_id = ?", (uid,)
    ).fetchone()["n"] == 0
    assert _pending(db) == 0


def test_the_internal_deletion_rpc_cleans_the_same_stores(tmp_path, monkeypatch):
    from test_account_deletion_261103 import PASSWORD_RPC_SECRET, _signed_internal_delete_call  # noqa: F401

    _session(monkeypatch)
    db, accounts, _app_unused, _settings, bucket, google, objects = _app(tmp_path)
    app, settings = build_app(db, authority=WorkspaceAuthority(), password_rpc_secret=PASSWORD_RPC_SECRET)
    app.state.workspace_document_store = type("Store", (), {"r2_bucket": bucket})()
    app.state.identity_shadow_store = object()
    app.state.google_oauth_workspace_truth = CloudflareGoogleOAuthWorkspaceTruth(google)
    app.state.file_lane_client = None
    response = _signed_internal_delete_call(app, {"product_user_id": accounts["deleter"]})
    assert response.status_code == 200, response.text
    # The signed caller's answer shape is unchanged.
    assert response.json() == {"ok": True, "deleted": True, "already_deleted": False}
    assert _existing(bucket, objects["mine"]) == []
    assert google.rows(WORKSPACE) == 0 and len(google.revoke.tokens) == 2
    assert _pending(db) == 0


# ---------------------------------------------------------------------------
# 2. A failure mid-way is reported, kept, and finished by the retry.
# ---------------------------------------------------------------------------


def test_external_failures_are_reported_and_a_retry_finishes_the_deletion(tmp_path, monkeypatch):
    _session(monkeypatch)
    bucket = FlakyDiskR2(tmp_path / "objects", failures=3)
    revoke = _GoogleRevoke(down=1)
    db, accounts, app, settings, bucket, google, objects = _app(
        tmp_path, bucket=bucket, revoke=revoke)
    uid = accounts["deleter"]

    response = _delete(app, settings, uid)

    # The account is gone and stays gone: the response does not hide the rest.
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cleanup"]["complete"] is False and body["cleanup"]["pending"] >= 2
    assert "자동으로 다시 시도" in body["message"]
    assert db.conn.execute("SELECT COUNT(*) AS n FROM users WHERE id = ?", (uid,)).fetchone()["n"] == 0
    assert _pending(db) == body["cleanup"]["pending"]
    # The Google row that stayed can no longer be used.
    assert google.storage.scalar(
        "SELECT COUNT(*) FROM google_oauth_refresh_credential"
        " WHERE workspace_ref = ? AND revoked_at IS NULL", WORKSPACE) == 0
    assert google.rows(WORKSPACE) == 1
    # Nothing in the pending rows names a person beyond the paths to erase.
    attempts = db.conn.execute(
        "SELECT MIN(attempts) AS lo FROM account_deletion_cleanup_pending").fetchone()["lo"]
    assert attempts == 1

    # The retry (the daily pass runs exactly this) finishes where it stopped.
    from app.account_cleanup_pending import CleanupPorts, drain

    result = asyncio.run(drain(db, CleanupPorts(
        bucket=bucket, google=app.state.google_oauth_workspace_truth,
        file_lane_absent_is_done=True)))
    assert result["pending"] == 0 and result["failed"] == 0
    assert _existing(bucket, objects["mine"]) == []
    assert _existing(bucket, objects["theirs"]) == objects["theirs"]
    assert google.rows(WORKSPACE) == 0
    assert revoke.tokens.count("refresh-bind.gmail") + revoke.tokens.count("refresh-bind.drive") == 3
    assert _pending(db) == 0
    # Running it again changes nothing.
    assert asyncio.run(drain(db, CleanupPorts(bucket=bucket)))["pending"] == 0


def test_the_daily_purge_run_retries_leftover_object_deletions(tmp_path, monkeypatch):
    _session(monkeypatch)
    objects_dir = tmp_path / "objects"
    bucket = FlakyDiskR2(objects_dir, failures=1000)
    db, accounts, app, settings, bucket, google, objects = _app(tmp_path, bucket=bucket)
    response = _delete(app, settings, accounts["deleter"])
    assert response.status_code == 200 and response.json()["cleanup"]["complete"] is False
    left = _pending(db)
    assert left > 0

    from app.expired_purge import _drain_account_cleanup

    # The timer has the object store but no Google or file-lane settings here.
    outcome = asyncio.run(_drain_account_cleanup(db, {}, objects_dir, dry_run=False))
    assert outcome["pending"] == 0, outcome
    assert _existing(LocalDiskR2(objects_dir), objects["mine"]) == []


# ---------------------------------------------------------------------------
# 3. When the inventory cannot be read, nothing is deleted and a retry works.
# ---------------------------------------------------------------------------


def test_an_unreachable_identity_authority_deletes_nothing(tmp_path, monkeypatch):
    _session(monkeypatch)
    db, accounts, app, settings, bucket, google, objects = _app(
        tmp_path, authority=WorkspaceAuthority(fail=True))
    before = snapshot(db, accounts)
    response = _delete(app, settings, accounts["deleter"])
    assert response.status_code == 503
    assert "아무것도 지워지지 않았습니다" in response.json()["error"]["message"]
    assert snapshot(db, accounts) == before
    assert _existing(bucket, objects["mine"]) == objects["mine"]
    assert google.rows(WORKSPACE) == 2 and google.revoke.tokens == []
    assert _pending(db) == 0


def test_a_session_authority_that_cannot_answer_deletes_nothing(tmp_path, monkeypatch):
    _session(monkeypatch, reason="truth_unavailable")
    db, accounts, app, settings, bucket, google, objects = _app(tmp_path)
    before = snapshot(db, accounts)
    response = _delete(app, settings, accounts["deleter"])
    assert response.status_code == 503
    assert snapshot(db, accounts) == before
    assert google.rows(WORKSPACE) == 2


def test_an_account_without_a_canonical_session_still_deletes_its_objects(tmp_path, monkeypatch):
    _session(monkeypatch, reason="session_inactive")
    db, accounts, app, settings, bucket, google, objects = _app(tmp_path)
    response = _delete(app, settings, accounts["deleter"])
    assert response.status_code == 200, response.text
    assert response.json()["cleanup"] == {"complete": True, "pending": 0}
    assert _existing(bucket, objects["mine"]) == []
    # No session means no workspace this account could have connected through.
    assert google.calls == []


# ---------------------------------------------------------------------------
# 4. The local object store lists and tidies prefixes like the R2 binding.
# ---------------------------------------------------------------------------


def test_local_store_lists_by_prefix_and_removes_empty_account_directories(tmp_path):
    bucket = LocalDiskR2(tmp_path)
    for index in range(3):
        bucket.put(f"chat-attachments/usr_a/file_{index}/body", b"x")
    bucket.put("chat-attachments/usr_ab/file_9/body", b"x")
    bucket.put("owner:usr_a/doc", b"x")
    page = bucket.list({"prefix": "chat-attachments/usr_a/", "limit": 2})
    assert [item.key for item in page.objects] == [
        "chat-attachments/usr_a/file_0/body", "chat-attachments/usr_a/file_1/body"]
    assert page.truncated is True
    rest = bucket.list({"prefix": "chat-attachments/usr_a/", "cursor": page.cursor})
    assert [item.key for item in rest.objects] == ["chat-attachments/usr_a/file_2/body"]
    assert rest.truncated is False
    assert [item.key for item in bucket.list({"prefix": "owner:usr_a/"}).objects] == ["owner:usr_a/doc"]
    for index in range(3):
        bucket.delete(f"chat-attachments/usr_a/file_{index}/body")
    bucket.remove_empty_prefix("chat-attachments/usr_a/")
    assert not (tmp_path / "chat-attachments" / "usr_a").exists()
    assert bucket.get("chat-attachments/usr_ab/file_9/body") is not None
    with pytest.raises(ValueError):
        bucket.remove_empty_prefix("chat-attachments/usr_a")
