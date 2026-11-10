"""Account-deletion object-storage/file-lane sweeps and reverse subject basis.

The 2026-11-11 internal audit found two gaps this suite pins shut:

1. an account created by direct social login carries a raw ``provider_subject``
   (``history.upsert_google_user``), so the old ``shared:``-marker-only check
   skipped the common-login withdrawal flow and left the common account and
   its sessions alive. The route now resolves the canonical subject from the
   durable reverse sources — the identity shadow projection and the
   account-link cache — and always runs the common flow when one resolves;
2. the withdrawal batch removed the D1 rows referencing private R2 objects
   but never the objects, and the COM2 file lane had no delete path at all.
   Both are now swept per user prefix after the batch, best-effort.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.file_lane import FileLaneClient

from test_account_deletion_261103 import (
    BASE,
    DELETER_EMAIL,
    PASSWORD_RPC_SECRET,
    _bookai_rows,
    _seed_bookai,
    _signed_internal_delete_call,
    build_app,
    call,
    seed_db,
    token_for,
)

SHADOW_SUBJECT = "sub_" + "c" * 32


class RecordingBucket:
    """Sync fake R2 binding (the real one may be sync or awaitable)."""

    def __init__(self):
        self.deleted = []

    def delete(self, key):
        self.deleted.append(key)


class RecordingLaneClient:
    def __init__(self, *, ready=True, fail=False):
        self.ready = ready
        self.fail = fail
        self.purged = []

    async def purge_user(self, user_id):
        self.purged.append(user_id)
        if self.fail:
            raise RuntimeError("synthetic lane failure")


class RecordingTransport:
    def __init__(self):
        self.paths = []

    async def __call__(self, **kwargs):
        self.paths.append(kwargs["path"])
        payload = {"ok": True, "deleted": True}
        if kwargs["path"] == "/internal/account-delete/prepare":
            payload = {"ok": True, "prepared": True, "revoked_sessions": 2}
        from types import SimpleNamespace

        return SimpleNamespace(status_code=200, json=lambda: payload)


def _bind_reverse_subject(db, app, user_id):
    """A social-first account whose common subject only the shadow row names."""
    db.conn.execute(
        "UPDATE users SET provider_subject=? WHERE id=?",
        ("google-oauth2|raw-social-first", user_id),
    )
    # seed_db already projects a shadow row for every account; point it at the
    # social-first account's common subject.
    db.conn.execute(
        "UPDATE control_plane_identity_shadow SET canonical_subject_id=?"
        " WHERE product_user_id=?",
        (SHADOW_SUBJECT, user_id),
    )
    authority = app.state.control_plane_identity_authority
    authority.links = [
        {"product_id": "b62", "product_user_id": user_id, "state": "active"}
    ]
    return authority


def _seed_claw_automation(db, subject):
    now = "2026-11-11T00:00:00Z"
    db.conn.execute(
        "INSERT INTO claw_rules (rule_id, workspace_id, name, schedule_kind,"
        " schedule_expression, schedule_timezone, target_source, output_type,"
        " enabled, notification_channels, created_at, updated_at,"
        " canonical_subject_id) VALUES ('rule-social','tenant_social','n','daily',"
        "'0 9 * * *','UTC','inbox','message',1,'[]',?,?,?)",
        (now, now, subject),
    )
    db.conn.execute(
        "INSERT INTO claw_runs (run_id, workspace_id, rule_id, status,"
        " scheduled_time, started_at) VALUES ('run-social','tenant_social',"
        "'rule-social','PENDING',?,?)",
        (now, now),
    )
    db.conn.execute(
        "INSERT INTO claw_occurrences (occurrence_key, run_id, workspace_id)"
        " VALUES ('occ-social','run-social','tenant_social')"
    )
    db.conn.execute(
        "INSERT INTO claw_proposals (proposal_id, workspace_id, rule_id, channel,"
        " title, summary, created_at) VALUES ('prop-social','tenant_social',"
        "'rule-social','email','t','s',?)",
        (now,),
    )


def _seed_object_keys(db, user_id):
    db.conn.execute(
        "INSERT INTO claw_document_metadata (document_id, tenant_id, object_key,"
        " filename, media_type, byte_length, created_at, expires_at, user_id)"
        " VALUES ('doc_social','tenant_social','workspaces/tenant_social/claw/"
        "web-office/usr_social/ws/doc_social/report.xlsx','report.xlsx',"
        "'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',1,?,?,?)",
        ("2026-11-11T00:00:00Z", "2026-11-12T00:00:00Z", user_id),
    )
    db.conn.execute(
        "INSERT INTO b66_quote_asset (id, user_id, workspace_id, asset_kind,"
        " media_type, object_key, byte_length, sha256, status, created_at,"
        " updated_at) VALUES ('asset-social',?, 'tenant_social','logo',"
        "'image/png','workspaces/tenant_social/b66/assets/logo.png',1,?,"
        "'approved',?,?)",
        (user_id, "a" * 64, "2026-11-11T00:00:00Z", "2026-11-11T00:00:00Z"),
    )
    db.conn.execute(
        "INSERT INTO b66_template_source (id, user_id, workspace_id, media_type,"
        " original_filename, object_key, byte_length, sha256, status, created_at,"
        " updated_at) VALUES ('tmpl-social',?, 'tenant_social',"
        "'text/csv','t.csv','workspaces/tenant_social/b66/templates/t.csv',1,?,"
        "'uploaded',?,?)",
        (user_id, "b" * 64, "2026-11-11T00:00:00Z", "2026-11-11T00:00:00Z"),
    )


def test_social_first_account_resolves_its_common_subject_and_runs_the_auth_flow():
    db, accounts = seed_db()
    uid = accounts["deleter"]
    app, settings = build_app(db)
    authority = _bind_reverse_subject(db, app, uid)
    _seed_claw_automation(db, SHADOW_SUBJECT)
    _seed_bookai(db, SHADOW_SUBJECT, "rec-shadow")
    _seed_object_keys(db, uid)
    transport = RecordingTransport()
    app.state.account_delete_rpc_transport = transport
    lane = RecordingLaneClient()
    app.state.file_lane_client = lane
    bucket = RecordingBucket()
    app.state.workspace_document_store = SimpleBucketStore(bucket)

    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, uid),
        body={"confirm": DELETER_EMAIL},
        origin=BASE,
    )

    assert response.status_code == 200, response.text
    # The whole common-login flow ran: sessions revoked, the last product link
    # removed, the account tombstoned through prepare + complete.
    assert transport.paths == [
        "/internal/account-delete/prepare",
        "/internal/account-delete/complete",
    ]
    assert authority.removed == [("b62", uid, SHADOW_SUBJECT)]
    # The subject-keyed chain and BookAI rows went with the account.
    assert db.conn.execute(
        "SELECT COUNT(*) FROM claw_rules WHERE canonical_subject_id = ?",
        (SHADOW_SUBJECT,),
    ).fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM claw_runs").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM claw_occurrences").fetchone()[0] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM claw_proposals WHERE approved_by IS NULL"
    ).fetchone()[0] == 0
    assert _bookai_rows(db, SHADOW_SUBJECT) == 0
    # The file lane prefix was purged once, after the batch.
    assert lane.purged == [uid]
    collected = set(bucket.deleted)
    assert {
        "workspaces/tenant_social/claw/web-office/usr_social/ws/doc_social/report.xlsx",
        "workspaces/tenant_social/b66/assets/logo.png",
        "workspaces/tenant_social/b66/templates/t.csv",
    } <= collected
    assert db.conn.execute(
        "SELECT COUNT(*) FROM claw_document_metadata WHERE user_id = ?", (uid,)
    ).fetchone()[0] == 0


class SimpleBucketStore:
    """Stands in for the workspace document store the bucket rides on."""

    def __init__(self, bucket):
        self.r2_bucket = bucket


def test_social_first_account_without_any_reverse_basis_deletes_data_without_the_auth_flow():
    db, accounts = seed_db()
    uid = accounts["deleter"]
    app, settings = build_app(db)
    db.conn.execute(
        "UPDATE users SET provider_subject=? WHERE id=?",
        ("google-oauth2|raw-unmapped", uid),
    )
    transport = RecordingTransport()
    app.state.account_delete_rpc_transport = transport
    lane = RecordingLaneClient()
    app.state.file_lane_client = lane

    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, uid),
        body={"confirm": DELETER_EMAIL},
        origin=BASE,
    )

    assert response.status_code == 200, response.text
    assert transport.paths == []
    assert lane.purged == [uid]
    remaining = {row["id"] for row in db.conn.execute("SELECT id FROM users").fetchall()}
    assert uid not in remaining


def test_reverse_resolved_subject_without_authority_links_still_deletes_product_data():
    db, accounts = seed_db()
    uid = accounts["deleter"]
    app, settings = build_app(db)
    db.conn.execute(
        "UPDATE users SET provider_subject=? WHERE id=?",
        ("google-oauth2|raw-stale-link", uid),
    )
    db.conn.execute(
        "UPDATE control_plane_identity_shadow SET canonical_subject_id=?"
        " WHERE product_user_id=?",
        (SHADOW_SUBJECT, uid),
    )
    # Authority holds no active link for this subject: nothing to unlink, and
    # the service-level deletion proceeds with the product data.
    transport = RecordingTransport()
    app.state.account_delete_rpc_transport = transport

    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, uid),
        body={"confirm": DELETER_EMAIL},
        origin=BASE,
    )

    assert response.status_code == 200, response.text
    assert transport.paths == []
    assert response.json()["common_account_deleted"] is False
    remaining = {row["id"] for row in db.conn.execute("SELECT id FROM users").fetchall()}
    assert uid not in remaining


def test_a_failed_batch_never_touches_r2_or_the_lane():
    db, accounts = seed_db()
    uid = accounts["deleter"]
    app, settings = build_app(db)
    _seed_object_keys(db, uid)
    db.conn.execute("DROP TABLE conversations")  # mid-batch failure (messages delete)
    bucket = RecordingBucket()
    app.state.workspace_document_store = SimpleBucketStore(bucket)
    lane = RecordingLaneClient()
    app.state.file_lane_client = lane

    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, uid),
        body={"confirm": DELETER_EMAIL},
        origin=BASE,
    )

    assert response.status_code == 503, response.text
    assert bucket.deleted == []
    assert lane.purged == []
    # The rollback kept the inventory rows: a retry re-collects the keys.
    assert db.conn.execute(
        "SELECT COUNT(*) FROM claw_document_metadata WHERE object_key LIKE"
        " 'workspaces/tenant_social/claw/%' AND user_id = ?",
        (uid,),
    ).fetchone()[0] == 1


def test_a_broken_file_lane_never_fails_the_withdrawal():
    db, accounts = seed_db()
    uid = accounts["deleter"]
    app, settings = build_app(db)
    app.state.file_lane_client = RecordingLaneClient(fail=True)

    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, uid),
        body={"confirm": DELETER_EMAIL},
        origin=BASE,
    )

    assert response.status_code == 200, response.text
    remaining = {row["id"] for row in db.conn.execute("SELECT id FROM users").fetchall()}
    assert uid not in remaining


def test_an_unconfigured_file_lane_is_skipped_entirely():
    db, accounts = seed_db()
    uid = accounts["deleter"]
    app, settings = build_app(db)
    assert isinstance(app.state.file_lane_client, FileLaneClient)
    assert app.state.file_lane_client.ready is False

    response = call(
        app, settings, "POST", "/api/account/delete",
        token=token_for(settings, uid),
        body={"confirm": DELETER_EMAIL},
        origin=BASE,
    )

    assert response.status_code == 200, response.text


def test_the_signed_delete_rpc_runs_the_object_and_lane_sweeps_too():
    db, accounts = seed_db()
    uid = accounts["deleter"]
    app, settings = build_app(db, password_rpc_secret=PASSWORD_RPC_SECRET)
    _seed_object_keys(db, uid)
    db.conn.execute(
        "UPDATE users SET provider_subject=? WHERE id=?",
        ("google-oauth2|raw-rpc", uid),
    )
    bucket = RecordingBucket()
    app.state.workspace_document_store = SimpleBucketStore(bucket)
    lane = RecordingLaneClient()
    app.state.file_lane_client = lane

    response = _signed_internal_delete_call(app, {"product_user_id": uid})

    assert response.status_code == 200, response.text
    assert {
        "workspaces/tenant_social/claw/web-office/usr_social/ws/doc_social/report.xlsx",
        "workspaces/tenant_social/b66/assets/logo.png",
        "workspaces/tenant_social/b66/templates/t.csv",
    } <= set(bucket.deleted)
    assert lane.purged == [uid]

