"""#4139 private Identity DO owner-consent RPC, default-off and canonical-session tests."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import sqlite3
from types import SimpleNamespace

import pytest

from identity_authority_durable import CloudflareCanonicalIdentityAuthorityStore, decode_identity_lookup_key
from identity_authority_worker import CanonicalIdentityDurableObject
from canonical_connector_enrollment_durable import IdentityDurableConnectorEnrollmentRecords
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, ControlPlaneContractError, SubjectType
from padiem_control_plane.padiem_connector_enrollment import ConnectorEnrollmentConsent

NOW = datetime(2026, 10, 12, 10, tzinfo=timezone.utc)
PRODUCT = "b54-padiem-claw"
SUBJECT = "sub.canonical.owner"
SESSION_ID = "session.owner.canonical"
TENANT = "tenant.owner.canonical"
DEVICE = "device.windows.owner"


class Cursor:
    def __init__(self, rows):
        self.rows = rows
    def toArray(self):
        return self.rows


class Sql:
    def __init__(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
    def exec(self, query, *args):
        cursor = self.db.execute(query, args)
        if cursor.description:
            names = [c[0] for c in cursor.description]
            return Cursor([dict(zip(names, row, strict=True)) for row in cursor.fetchall()])
        return Cursor([])


class Storage:
    def __init__(self):
        self.sql = Sql()
    def transactionSync(self, fn):
        self.sql.db.execute("BEGIN IMMEDIATE")
        try:
            result = fn()
            self.sql.db.execute("COMMIT")
            return result
        except Exception:
            self.sql.db.execute("ROLLBACK")
            raise


class Canonical:
    def __init__(self):
        self.session = AuthSessionSnapshot(
            session_id=SESSION_ID, product_id=PRODUCT,
            subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=SUBJECT),
            issued_at=NOW-timedelta(minutes=2), expires_at=NOW+timedelta(hours=1),
            state=AuthSessionState.ACTIVE, tenant_id=TENANT,
        )
    def resolve_auth_session(self, *, session_id):
        if session_id != SESSION_ID:
            raise ControlPlaneContractError("canonical_auth_session_not_found", "no session")
        return self.session
    def resolve_active_tenant_membership(self, *, tenant_id, canonical_subject_id, now):
        if tenant_id != TENANT or canonical_subject_id != SUBJECT or not self.session.is_active(now=now):
            raise ControlPlaneContractError("canonical_tenant_membership_inactive", "no active membership")
        return SimpleNamespace(role="owner")


def harness(*, enabled=True, scope_approved=True, schema_installed=True):
    storage = Storage()
    canonical = Canonical()
    # Existing canonical Identity DO store creates its pre-existing schema.
    # Test-only local SQLite harness: NOT production migration.
    context_store = __import__("identity_connector_ticket").CanonicalConnectorContextStore(
        storage, random_hex=lambda n: "a"*(n*2)
    )
    context_store.resolve_or_create(auth_session=canonical.session, now=NOW)
    # The code under test reads the same legacy subject's connector context.
    records = IdentityDurableConnectorEnrollmentRecords(storage=storage, session_reader=canonical)
    records.install_schema()
    env = SimpleNamespace(
        CONTROL_PLANE_CONNECTOR_ENROLLMENT_RPC_ENABLED="true" if enabled else "false",
        CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCOPE_APPROVED="true" if scope_approved else "false",
        CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALLED="true" if schema_installed else "false",
        CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALL_ENABLED="false",
    )
    fake = SimpleNamespace(
        env=env, _store=canonical, _storage=storage,
        _connector_enrollment_records=records,
    )
    return fake, records, canonical, storage


def call(method, fake, payload):
    return asyncio.run(getattr(CanonicalIdentityDurableObject, method)(fake, payload))


def grant_payload(**changes):
    value = {
        "session_id": SESSION_ID, "device_id": DEVICE,
        "confirmed": True, "confirmation_version": "pc-enrollment-consent-v1",
    }
    value.update(changes)
    return value


def revoke_payload(consent_id, **changes):
    value = {
        "session_id": SESSION_ID, "consent_id": consent_id,
        "confirmed": True, "confirmation_version": "pc-enrollment-consent-v1",
    }
    value.update(changes)
    return value


def test_consent_rpc_is_default_off_and_closed_fields():
    fake, records, canonical, _ = harness(enabled=False)
    result = call("grant_connector_enrollment_consent", fake, grant_payload())
    assert result["ok"] is False and result["error"]["code"] == "connector_enrollment_rpc_disabled"
    assert records.current_for_device(owner_subject_id=SUBJECT, device_id=DEVICE, now=NOW) is None

    fake.env.CONTROL_PLANE_CONNECTOR_ENROLLMENT_RPC_ENABLED = "true"
    result = call("grant_connector_enrollment_consent", fake, {**grant_payload(), "owner_subject_id": "forged"})
    assert result["ok"] is False and result["error"]["code"] == "invalid_identity_authority_rpc"


@pytest.mark.parametrize("changes", [
    {"confirmed": False},
    {"confirmed": "true"},
    {"confirmation_version": "old"},
])
def test_grant_requires_exact_explicit_confirmation_contract(changes):
    fake, records, _, _ = harness()
    result = call("grant_connector_enrollment_consent", fake, grant_payload(**changes))
    assert result["ok"] is False
    assert result["error"]["code"] == "connector_enrollment_explicit_consent_required"
    assert records.current_for_device(owner_subject_id=SUBJECT, device_id=DEVICE, now=NOW) is None


def test_grant_and_withdraw_are_canonical_owner_scoped_and_idempotently_refused():
    fake, records, canonical, _ = harness()
    grant = call("grant_connector_enrollment_consent", fake, grant_payload())
    assert grant["ok"] is True
    consent = grant["consent"]
    assert consent["device_id"] == DEVICE
    assert consent["dispatch_authorized"] is False and consent["grants_write"] is False
    assert records.current_for_device(owner_subject_id=SUBJECT, device_id=DEVICE, now=NOW) is not None

    # A different user/session cannot grant or revoke this owner's consent.
    canonical.session = AuthSessionSnapshot(
        session_id=SESSION_ID, product_id=PRODUCT,
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="sub.other"),
        issued_at=NOW-timedelta(minutes=2), expires_at=NOW+timedelta(hours=1),
        state=AuthSessionState.ACTIVE, tenant_id=TENANT,
    )
    denied = call("revoke_connector_enrollment_consent", fake, revoke_payload(consent["consent_id"]))
    assert denied["ok"] is False
    assert records.current_consent(consent_id=consent["consent_id"], now=NOW).withdrawn_at is None

    canonical.session = AuthSessionSnapshot(
        session_id=SESSION_ID, product_id=PRODUCT,
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=SUBJECT),
        issued_at=NOW-timedelta(minutes=2), expires_at=NOW+timedelta(hours=1),
        state=AuthSessionState.ACTIVE, tenant_id=TENANT,
    )
    revoked = call("revoke_connector_enrollment_consent", fake, revoke_payload(consent["consent_id"]))
    assert revoked["ok"] is True
    assert revoked["consent"]["dispatch_authorized"] is False
    assert records.current_for_device(owner_subject_id=SUBJECT, device_id=DEVICE, now=NOW) is None
    again = call("revoke_connector_enrollment_consent", fake, revoke_payload(consent["consent_id"]))
    assert again["ok"] is False


def test_invalid_or_inactive_canonical_session_never_grants():
    fake, records, canonical, _ = harness()
    canonical.session = AuthSessionSnapshot(
        session_id=SESSION_ID, product_id=PRODUCT,
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=SUBJECT),
        issued_at=NOW-timedelta(minutes=2), expires_at=NOW+timedelta(hours=1),
        state=AuthSessionState.REVOKED, tenant_id=TENANT,
    )
    result = call("grant_connector_enrollment_consent", fake, grant_payload())
    assert result["ok"] is False
    assert result["error"]["code"] == "connector_enrollment_consent_session_denied"
    assert records.current_for_device(owner_subject_id=SUBJECT, device_id=DEVICE, now=NOW) is None


def test_no_shared_scope_row_never_mints_a_scope_or_consent():
    fake, records, _, storage = harness()
    storage.sql.db.execute("DELETE FROM canonical_connector_context")
    result = call("grant_connector_enrollment_consent", fake, grant_payload())
    assert result["ok"] is False
    assert result["error"]["code"] == "canonical_scope_not_established"
    assert records.current_for_device(owner_subject_id=SUBJECT, device_id=DEVICE, now=NOW) is None


def test_schema_install_rpc_is_separate_and_disabled_by_default():
    fake, _, _, storage = harness(schema_installed=False)
    fake.env.CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALL_ENABLED = "false"
    result = call("install_connector_enrollment_schema", fake, {"migration_id": "connector-enrollment-v1"})
    assert result["ok"] is False and result["error"]["code"] == "connector_enrollment_schema_install_disabled"
    fake.env.CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALL_ENABLED = "true"
    result = call("install_connector_enrollment_schema", fake, {"migration_id": "wrong"})
    assert result["ok"] is False
