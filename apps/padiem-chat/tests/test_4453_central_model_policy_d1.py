"""S2 D1 adapter: transactional CAS, no live dispatch/role inference."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sqlite3
from types import SimpleNamespace
import uuid

import pytest

from app.central_model_policy_d1 import D1CentralModelPolicyStore
from padiem_control_plane.model_assignment_policy import (
    CatalogModel, ModelChange, VerifiedModelAdminGrant,
)
from padiem_control_plane.contracts import ControlPlaneContractError

MIGRATION = Path(__file__).parents[1] / "migrations" / "039_central_model_policy.sql"
NOW = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)
USER = "usr_" + "a" * 32
GOOD = "google/test-model"
BAD = "google/blocked-model"
CATALOG = {
    GOOD: CatalogModel(GOOD, True, True, True, True, frozenset({"chat"})),
    BAD: CatalogModel(BAD, True, False, True, False, frozenset({"chat"})),
}


class Statement:
    def __init__(self, db, sql, params=()):
        self.db, self.sql, self.params = db, sql, params

    def bind(self, *params):
        return Statement(self.db, self.sql, params)

    async def first(self):
        self.db.query_count += 1
        row = self.db.conn.execute(self.sql, self.params).fetchone()
        return dict(row) if row else None

    async def run(self):
        self.db.query_count += 1
        rows = self.db.conn.execute(self.sql, self.params).fetchall()
        return SimpleNamespace(results=[dict(row) for row in rows])


class FakeD1:
    """Behaves like D1: batch must fully commit or fully roll back."""
    def __init__(self, *, migrated=True):
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        if migrated:
            self.conn.executescript(MIGRATION.read_text(encoding="utf8"))
        self.query_count = 0
        self.batches = []

    def prepare(self, sql):
        return Statement(self, sql)

    async def batch(self, statements):
        self.batches.append(len(statements))
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            results = []
            for statement in statements:
                cursor = self.conn.execute(statement.sql, statement.params)
                results.append(SimpleNamespace(results=[dict(row) for row in cursor.fetchall()]))
            self.conn.execute("COMMIT")
            return results
        except Exception:
            self.conn.execute("ROLLBACK")
            raise


def grant(*, product=None, user=USER, workspace="padiem-global", rights=None):
    return VerifiedModelAdminGrant(
        subject_id=user, workspace_id=workspace, product=product,
        permissions=frozenset(rights or {"preview", "apply", "rollback"}),
        issued_at=NOW-timedelta(minutes=1), expires_at=NOW+timedelta(hours=1),
        authority_ref="trusted-server-google-subject",
    )


def commit(store, changes, rev, *, nonce=None, actor=None, workspace="padiem-global", catalog=CATALOG,
           operation="apply", now=NOW):
    return asyncio.run(store.commit(
        grant=actor or grant(workspace=workspace), workspace_id=workspace,
        expected_revision=rev, nonce=nonce or uuid.uuid4().hex,
        operation=operation, changes=tuple(changes), catalog=catalog, now=now,
    ))


def read(store, ws="padiem-global"):
    return asyncio.run(store.snapshot(ws))


def err(code, func):
    with pytest.raises(ControlPlaneContractError) as exc:
        func()
    assert exc.value.code == code


def test_schema_is_safe_empty_only_and_does_not_touch_existing_b66_schema():
    db = FakeD1()
    assert read(D1CentralModelPolicyStore(db)).revision == 0
    assert db.conn.execute("SELECT count(*) FROM central_model_policy_rules").fetchone()[0] == 0
    assert db.conn.execute("SELECT count(*) FROM central_model_policy_audit").fetchone()[0] == 0
    assert db.conn.execute("SELECT count(*) FROM central_model_policy_state").fetchone()[0] == 0
    assert not any(row[0].startswith("b66_") for row in db.conn.execute("SELECT name FROM sqlite_master"))
    assert "DROP TABLE" not in MIGRATION.read_text(encoding="utf8").upper()
    assert "CREATE TRIGGER" not in MIGRATION.read_text(encoding="utf8").upper()


def test_d1_single_batch_adds_central_and_product_grant_then_revision():
    db = FakeD1()
    store = D1CentralModelPolicyStore(db)
    changes = [ModelChange("central", "PLUS", GOOD, "allow"),
               ModelChange("chat", "PLUS", GOOD, "allow")]
    result = commit(store, changes, 0)
    assert result.revision == 1
    assert result.lookup("central", "PLUS", GOOD) == "allow"
    assert result.lookup("chat", "PLUS", GOOD) == "allow"
    assert db.batches == [9]  # INSERT state, UPDATE CAS, nonce, 4 rule writes, history, audit
    assert len(asyncio.run(store.audit("padiem-global"))) == 1
    assert asyncio.run(store.previous_revision("padiem-global", 1)) == result
    assert read(store, "another-workspace").revision == 0


def test_multiple_tiers_models_and_tenants_isolated():
    db = FakeD1()
    store = D1CentralModelPolicyStore(db)
    changed = tuple(ModelChange("central", tier, GOOD, "allow")
                    for tier in ("FREE", "PLUS", "PRO", "MAX"))
    assert commit(store, changed, 0).revision == 1
    assert commit(store, [ModelChange("claw", "MAX", GOOD, "block")], 0,
                  actor=grant(workspace="tenant-b"), workspace="tenant-b").revision == 1
    assert read(store).revision == 1
    assert read(store, "tenant-b").lookup("central", "MAX", GOOD) == "inherit"
    assert read(store, "tenant-b").lookup("claw", "MAX", GOOD) == "block"
    assert len(asyncio.run(store.audit("tenant-b"))) == 1


def test_cas_stale_or_replayed_nonce_fails_without_audit_or_partial_changes():
    db = FakeD1()
    store = D1CentralModelPolicyStore(db)
    nonce = "f" * 32
    assert commit(store, [ModelChange("central", "PLUS", GOOD, "allow")], 0, nonce=nonce).revision == 1
    err("model_policy_receipt_replayed",
        lambda: commit(store, [ModelChange("chat", "PLUS", GOOD, "allow")], 1, nonce=nonce))
    err("model_policy_revision_conflict",
        lambda: commit(store, [ModelChange("chat", "PLUS", GOOD, "allow")], 0))
    assert read(store).revision == 1
    assert read(store).lookup("chat", "PLUS", GOOD) == "inherit"
    assert len(asyncio.run(store.audit("padiem-global"))) == 1
    assert len(db.batches) == 1


def test_sql_atomic_guard_rolls_back_when_revision_changed_after_preflight():
    db = FakeD1()
    store = D1CentralModelPolicyStore(db)
    # Race the preflight: a direct, authorized DB change happens between
    # the store's read and its transactional compare-and-swap.
    original_batch = db.batch

    async def conflicting_batch(statements):
        db.conn.execute(
            "INSERT OR IGNORE INTO central_model_policy_state(workspace_id,revision,updated_at) "
            "VALUES ('padiem-global',0,'race')"
        )
        db.conn.execute(
            "UPDATE central_model_policy_state SET revision=9 WHERE workspace_id='padiem-global'"
        )
        return await original_batch(statements)

    db.batch = conflicting_batch
    with pytest.raises(sqlite3.IntegrityError):
        commit(store, [ModelChange("central", "PLUS", GOOD, "allow")], 0)
    assert read(store).revision == 9
    assert db.conn.execute("SELECT count(*) FROM central_model_policy_rules").fetchone()[0] == 0
    assert db.conn.execute("SELECT count(*) FROM central_model_policy_nonces").fetchone()[0] == 0
    assert db.conn.execute("SELECT count(*) FROM central_model_policy_audit").fetchone()[0] == 0


def test_product_scoped_admin_never_assigns_global_or_other_product():
    db = FakeD1()
    store = D1CentralModelPolicyStore(db)
    product_admin = grant(product="claw")
    assert commit(store, [ModelChange("claw", "PRO", GOOD, "allow")], 0,
                  actor=product_admin).revision == 1
    err("model_admin_scope_forbidden", lambda: commit(
        store, [ModelChange("central", "PRO", GOOD, "allow")], 1,
        actor=product_admin,
    ))
    err("model_admin_scope_forbidden", lambda: commit(
        store, [ModelChange("chat", "PRO", GOOD, "allow")], 1,
        actor=product_admin,
    ))
    assert read(store).revision == 1


def test_unapproved_model_allow_rejected_but_explicit_block_is_allowed():
    db = FakeD1()
    store = D1CentralModelPolicyStore(db)
    err("model_policy_offline_model",
        lambda: commit(store, [ModelChange("central", "PLUS", BAD, "allow")], 0))
    assert commit(store, [ModelChange("central", "PLUS", BAD, "block")], 0).revision == 1


def test_rollback_audited_as_new_revision_and_no_auto_model_activation():
    db = FakeD1()
    store = D1CentralModelPolicyStore(db)
    commit(store, [ModelChange("central", "PLUS", GOOD, "allow")], 0)
    commit(store, [ModelChange("central", "PLUS", GOOD, "block")], 1)
    earlier = asyncio.run(store.previous_revision("padiem-global", 1))
    assert earlier.lookup("central", "PLUS", GOOD) == "allow"
    latest = commit(store, [ModelChange("central", "PLUS", GOOD, "allow")],
                    2, operation="rollback")
    assert latest.revision == 3
    assert latest.lookup("central", "PLUS", GOOD) == "allow"
    history = asyncio.run(store.audit("padiem-global"))
    assert history[0]["operation"] == "rollback"
    assert history[0]["revision"] == 3
    assert db.conn.execute("SELECT count(*) FROM central_model_policy_history").fetchone()[0] == 3


def test_unconfigured_binding_and_unapplied_migration_fail_closed():
    with pytest.raises(ValueError):
        D1CentralModelPolicyStore(None)
    db = FakeD1(migrated=False)
    store = D1CentralModelPolicyStore(db)
    with pytest.raises(sqlite3.OperationalError):
        read(store)
    assert db.conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0


def test_invalid_authority_expired_unknown_model_and_missing_catalog_do_not_write():
    db = FakeD1()
    store = D1CentralModelPolicyStore(db)
    err("model_admin_forbidden", lambda: asyncio.run(store.commit(
        grant="self-claimed browser role", workspace_id="padiem-global",
        expected_revision=0, nonce=uuid.uuid4().hex, operation="apply",
        changes=(ModelChange("central", "PLUS", GOOD, "allow"),),
        catalog=CATALOG, now=NOW,
    )))
    err("model_admin_grant_expired", lambda: commit(
        store, [ModelChange("central", "PLUS", GOOD, "allow")], 0,
        now=NOW+timedelta(days=1),
    ))
    err("model_policy_unknown_model", lambda: commit(
        store, [ModelChange("central", "PLUS", "unknown/model", "allow")], 0,
    ))
    err("model_policy_catalog_unavailable", lambda: commit(
        store, [ModelChange("central", "PLUS", GOOD, "allow")], 0, catalog=None,
    ))
    assert not db.batches


def test_audit_metadata_is_content_blind_no_credentials_or_prompts():
    db = FakeD1()
    store = D1CentralModelPolicyStore(db)
    commit(store, [ModelChange("central", "FREE", GOOD, "block")], 0)
    audit = json.dumps(asyncio.run(store.audit("padiem-global")))
    assert "api_key" not in audit and "prompt" not in audit
    assert "password" not in audit and "Bearer" not in audit
    assert "google/test-model" in audit


# S3: signed global-admin write gateway; no model-dispatch activation.
def test_s3_preview_confirm_d1_audit_rollback_and_replay():
    from app.central_model_policy_write_routes import WORKSPACE
    from app.auth import SESSION_COOKIE, create_session_token
    from app.config import Settings
    from app.main import create_app
    import httpx

    class Admin:
        async def is_global_model_admin(self, *, user_id):
            return True

    class Models:
        async def list_selectable_models(self):
            return [{"model_id": GOOD, "name": "Test model"}]

        async def list_registered_models(self):
            return [
                {"model_id": GOOD, "name": "Test model", "provider_id": "google",
                 "b14_enabled": True, "owner_excluded": False, "capabilities": ["chat"]},
                {"model_id": BAD, "name": "Blocked test", "provider_id": "google",
                 "b14_enabled": False, "owner_excluded": True, "capabilities": ["chat"]},
            ]

    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password",
        public_base_url="https://chat.test",
        session_secret="s3-admin-test-cookie-secret-longer-than-32",
        session_max_age_seconds=3600,
    )
    store = D1CentralModelPolicyStore(FakeD1())
    app = create_app(
        settings=settings, history_store=SimpleNamespace(),
        central_model_admin_authorizer=Admin(),
        central_model_policy_store=store,
        central_model_policy_signing_key="ab" * 32,
    )
    app.state.b14_model_choice_resolver = Models()

    async def req(method, path, *, body=None, user=USER, origin="https://chat.test"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://chat.test"
        ) as client:
            if user is not None:
                client.cookies.set(SESSION_COOKIE, create_session_token(settings, user))
            headers = {"Origin": origin} if origin is not None else {}
            return await client.request(method, path, json=body, headers=headers)

    payload = {"model_id": GOOD, "targets": [
        {"product_id": "central", "tier": "PLUS", "action": "allow"},
        {"product_id": "chat", "tier": "PLUS", "action": "allow"},
    ]}

    async def case():
        assert (await req("GET", "/api/admin/models/me")).json()["write_enabled"] is True
        assert (await req("POST", "/api/admin/models/change-preview",
                          body=payload, user=None)).status_code == 401
        assert (await req("POST", "/api/admin/models/change-preview",
                          body=payload, origin="https://evil.test")).status_code == 403
        preview = await req("POST", "/api/admin/models/change-preview", body=payload)
        assert preview.status_code == 200, preview.text
        data = preview.json()
        assert data["persisted"] is False and data["runtime_enforced"] is False
        assert len(data["diff"]) == 2 and (await store.snapshot(WORKSPACE)).revision == 0
        receipt = data["confirmation_receipt"]
        tampered = receipt[:-1] + ("0" if receipt[-1] != "0" else "1")
        assert (await req("POST", "/api/admin/models/change-apply",
                          body={"confirmation_receipt": tampered})).status_code == 422
        assert (await req("POST", "/api/admin/models/change-apply",
                          body={"confirmation_receipt": receipt},
                          user="usr_" + "b" * 32)).status_code == 422
        applied = await req("POST", "/api/admin/models/change-apply",
                            body={"confirmation_receipt": receipt})
        assert applied.status_code == 200, applied.text
        assert applied.json()["revision"] == 1
        assert applied.json()["runtime_enforced"] is False
        assert len((await store.snapshot(WORKSPACE)).rules) == 2
        assert (await req("POST", "/api/admin/models/change-apply",
                          body={"confirmation_receipt": receipt})).status_code == 409
        audit = await req("GET", "/api/admin/models/audit")
        assert audit.status_code == 200 and len(audit.json()["events"]) == 1
        assert audit.json()["events"][0]["operation"] == "apply"
        bad = {"model_id": BAD, "targets": [
            {"product_id": "chat", "tier": "FREE", "action": "allow"},
        ]}
        assert (await req("POST", "/api/admin/models/change-preview",
                          body=bad)).status_code == 422
        assert (await store.snapshot(WORKSPACE)).revision == 1
        rollback = await req("POST", "/api/admin/models/rollback-preview",
                             body={"target_revision": 0})
        assert rollback.status_code == 200, rollback.text
        done = await req("POST", "/api/admin/models/change-apply", body={
            "confirmation_receipt": rollback.json()["confirmation_receipt"]
        })
        assert done.status_code == 200, done.text
        final = await store.snapshot(WORKSPACE)
        assert final.revision == 2 and not final.rules
        audit = (await req("GET", "/api/admin/models/audit")).json()
        assert [e["operation"] for e in audit["events"]] == ["rollback", "apply"]
        assert (await req("POST", "/api/admin/models/change-apply", body={
            "confirmation_receipt": rollback.json()["confirmation_receipt"]
        })).status_code == 409

    asyncio.run(case())


def test_s3_missing_signer_remains_off():
    from app.auth import SESSION_COOKIE, create_session_token
    from app.config import Settings
    from app.main import create_app
    import httpx

    class Admin:
        async def is_global_model_admin(self, *, user_id):
            return True

    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password",
        public_base_url="https://chat.test",
        session_secret="s3-admin-test-cookie-secret-longer-than-32",
        session_max_age_seconds=3600,
    )
    app = create_app(
        settings=settings, history_store=SimpleNamespace(),
        central_model_admin_authorizer=Admin(),
        central_model_policy_store=D1CentralModelPolicyStore(FakeD1()),
    )

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://chat.test"
        ) as client:
            client.cookies.set(SESSION_COOKIE, create_session_token(settings, USER))
            assert (await client.get("/api/admin/models/me")).json()["write_enabled"] is False
            res = await client.post("/api/admin/models/change-preview",
                                    headers={"Origin": "https://chat.test"},
                                    json={"model_id": GOOD, "targets": []})
            assert res.status_code == 503
    asyncio.run(check())
