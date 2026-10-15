"""#4139: canonical Identity DO SQLite-backed PC consent and session continuity."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from canonical_connector_enrollment_durable import (
    CANONICAL_IDENTITY_DURABLE_OBJECT_REUSED,
    IdentityDurableConnectorEnrollmentRecords,
    PRODUCTION_CONSENT_RPC_EXPOSED,
    SCHEMA_INSTALLED_BY_DEFAULT,
)
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import (
    CanonicalSubjectRef, ControlPlaneContractError, SubjectType,
)
from padiem_control_plane.padiem_connector_enrollment import ConnectorEnrollmentConsent

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
OWNER = "usr_connector_test_owner"
CONSENT_ID = "consent.device.a"
DEVICE = "device.office.1"


class Cursor:
    def __init__(self, rows):
        self._rows = rows

    def toArray(self):
        return self._rows


class Sql:
    def __init__(self, db):
        self._db = db

    def exec(self, statement, *args):
        cursor = self._db.execute(statement, args)
        if cursor.description is not None:
            fields = [col[0] for col in cursor.description]
            return Cursor([dict(zip(fields, row, strict=True)) for row in cursor.fetchall()])
        return Cursor([])


class Storage:
    def __init__(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = Sql(self.db)

    def transactionSync(self, callback):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            result = callback()
            self.db.execute("COMMIT")
            return result
        except Exception:
            self.db.execute("ROLLBACK")
            raise


class CanonicalSessions:
    def __init__(self, session):
        self.records = {session.session_id: session}
        self.queries = []

    def resolve_auth_session(self, *, session_id):
        self.queries.append(session_id)
        if session_id not in self.records:
            raise ControlPlaneContractError("canonical_auth_session_not_found", "not found")
        return self.records[session_id]


def session(state=AuthSessionState.ACTIVE, *, tenant="tenant.connector"):
    return AuthSessionSnapshot(
        session_id="session.connector.1", product_id="b54-padiem-claw",
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=OWNER),
        issued_at=NOW - timedelta(minutes=10),
        expires_at=NOW + timedelta(hours=1),
        state=state, tenant_id=tenant,
    )


def consent(*, consent_id=CONSENT_ID, device_id=DEVICE):
    return ConnectorEnrollmentConsent(
        consent_id=consent_id, owner_subject_id=OWNER,
        account_ref="account.connector", workspace_ref="workspace.connector",
        device_id=device_id, granted_at=NOW - timedelta(minutes=1),
    )


def fixture():
    storage = Storage()
    sessions = CanonicalSessions(session())
    port = IdentityDurableConnectorEnrollmentRecords(
        storage=storage, session_reader=sessions
    )
    return port, storage, sessions


def error_code(action):
    with pytest.raises(ControlPlaneContractError) as exc:
        action()
    return exc.value.code


def test_no_automatic_schema_or_second_identity_store():
    port, storage, _ = fixture()
    assert CANONICAL_IDENTITY_DURABLE_OBJECT_REUSED
    assert SCHEMA_INSTALLED_BY_DEFAULT is False
    assert PRODUCTION_CONSENT_RPC_EXPOSED is False
    assert storage.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    assert error_code(lambda: port.current_consent(consent_id=CONSENT_ID, now=NOW)) == (
        "connector_enrollment_durable_unavailable"
    )


def test_grant_and_server_readback_from_existing_canonical_do_sqlite():
    port, storage, _ = fixture()
    port.install_schema()
    port.persist_preverified_consent(consent=consent(), now=NOW)
    original = port.current_for_device(owner_subject_id=OWNER, device_id=DEVICE, now=NOW)
    assert original == consent()
    assert port.current_for_device(owner_subject_id="usr.other", device_id=DEVICE, now=NOW) is None
    assert port.current_for_device(owner_subject_id=OWNER, device_id="device.other", now=NOW) is None
    assert port.current_consent(consent_id=CONSENT_ID, now=NOW) == original
    assert error_code(lambda: port.persist_preverified_consent(consent=consent(), now=NOW)) == (
        "enrollment_duplicate_device_consent_denied"
    )
    tables = {name for (name,) in storage.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert tables == {
        "canonical_connector_enrollment_consent",
        "canonical_connector_enrollment_session_binding",
    }


def test_withdrawal_is_owner_scoped_and_cannot_resurrect_old_consent():
    port, _, _ = fixture()
    port.install_schema()
    port.persist_preverified_consent(consent=consent(), now=NOW)
    assert error_code(lambda: port.withdraw_preverified_consent(
        consent_id=CONSENT_ID, owner_subject_id="usr.other", now=NOW
    )) == "enrollment_consent_required"
    port.withdraw_preverified_consent(consent_id=CONSENT_ID, owner_subject_id=OWNER, now=NOW)
    assert port.current_for_device(owner_subject_id=OWNER, device_id=DEVICE, now=NOW + timedelta(seconds=1)) is None
    past = port.current_consent(consent_id=CONSENT_ID, now=NOW + timedelta(seconds=1))
    assert past is not None and past.withdrawn_at == NOW
    assert error_code(lambda: port.withdraw_preverified_consent(
        consent_id=CONSENT_ID, owner_subject_id=OWNER, now=NOW + timedelta(seconds=1)
    )) == "enrollment_consent_withdrawn"
    port.persist_preverified_consent(consent=consent(consent_id="consent.device.b"), now=NOW + timedelta(seconds=2))
    assert port.current_for_device(
        owner_subject_id=OWNER, device_id=DEVICE, now=NOW + timedelta(seconds=2)
    ).consent_id == "consent.device.b"
    assert port.current_consent(consent_id=CONSENT_ID, now=NOW).withdrawn_at == NOW


def test_withdrawal_verifies_by_reread_when_changes_cursor_is_empty():
    """The production Durable Object SQLite cursor returned no usable
    `SELECT changes()` row on the withdraw path (observed as
    connector_enrollment_durable_corrupt on a live, otherwise healthy row).
    The withdraw verification must depend only on the proven row-projection
    shape, so an empty changes cursor still commits the withdrawal."""

    class NoChangesSql(Sql):
        def exec(self, statement, *args):
            if statement.lstrip().upper().startswith("SELECT CHANGES()"):
                return Cursor([])
            return super().exec(statement, *args)

    class NoChangesStorage(Storage):
        def __init__(self):
            self.db = sqlite3.connect(":memory:", isolation_level=None)
            self.sql = NoChangesSql(self.db)

    storage = NoChangesStorage()
    sessions = CanonicalSessions(session())
    port = IdentityDurableConnectorEnrollmentRecords(
        storage=storage, session_reader=sessions
    )
    port.install_schema()
    port.persist_preverified_consent(consent=consent(), now=NOW)
    port.withdraw_preverified_consent(consent_id=CONSENT_ID, owner_subject_id=OWNER, now=NOW)
    past = port.current_consent(consent_id=CONSENT_ID, now=NOW + timedelta(seconds=1))
    assert past is not None and past.withdrawn_at == NOW


def test_challenge_session_binding_uses_original_session_not_client_identity():
    port, _, reader = fixture()
    port.install_schema()
    original = session()
    port.bind_challenge(
        challenge_id="challenge.one", session=original,
        expires_at=NOW + timedelta(minutes=5), now=NOW,
    )
    result = port.current_session(challenge_id="challenge.one", now=NOW + timedelta(seconds=3))
    assert result == original
    assert reader.queries == [original.session_id, original.session_id]
    assert port.current_session(challenge_id="challenge.other", now=NOW) is None
    assert port.current_session(challenge_id="challenge.one", now=NOW + timedelta(minutes=5)) is None


@pytest.mark.parametrize("change", [
    "revoked", "expired", "tenant", "deleted", "other_subject",
])
def test_redeem_session_current_authority_required_after_issue(change):
    port, _, reader = fixture()
    port.install_schema()
    port.bind_challenge(
        challenge_id="challenge.one", session=session(),
        expires_at=NOW + timedelta(minutes=5), now=NOW,
    )
    if change == "revoked":
        reader.records["session.connector.1"] = session(AuthSessionState.REVOKED)
    elif change == "expired":
        reader.records["session.connector.1"] = replace(session(), expires_at=NOW)
    elif change == "tenant":
        reader.records["session.connector.1"] = session(tenant="tenant.other")
    elif change == "other_subject":
        reader.records["session.connector.1"] = replace(
            session(),
            subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="usr.other"),
        )
    else:
        reader.records.clear()
    assert port.current_session(challenge_id="challenge.one", now=NOW + timedelta(seconds=1)) is None


def test_binding_does_not_accept_expired_or_untrusted_canonical_snapshot():
    port, _, reader = fixture()
    port.install_schema()
    assert error_code(lambda: port.bind_challenge(
        challenge_id="challenge.one", session=session(AuthSessionState.REVOKED),
        expires_at=NOW + timedelta(minutes=5), now=NOW,
    )) == "canonical_session_inactive"
    assert error_code(lambda: port.bind_challenge(
        challenge_id="challenge.one", session=session(),
        expires_at=NOW + timedelta(hours=2), now=NOW,
    )) == "canonical_session_inactive"
    reader.records["session.connector.1"] = session(tenant="tenant.other")
    assert error_code(lambda: port.bind_challenge(
        challenge_id="challenge.one", session=session(),
        expires_at=NOW + timedelta(minutes=5), now=NOW,
    )) == "canonical_session_scope_mismatch"

def test_actual_s1_server_with_durable_consent_and_original_session_reuse():
    """SQLite-backed current consent/session, REAL S1 Broker pairing authority."""
    from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
    from padiem_control_plane.local_agent_broker_pairing import (
        InMemoryBrokerPairingAuthority, pairing_proof_ref,
    )
    from padiem_control_plane.padiem_connector_enrollment import ConnectorEnrollmentScope
    from padiem_control_plane.padiem_connector_enrollment_server import CanonicalConnectorEnrollmentServer

    port, storage, canonical_reader = fixture()
    port.install_schema()
    port.persist_preverified_consent(consent=consent(), now=NOW)

    class Scope:
        def resolve_scope(self, *, subject_id, tenant_ref, now):
            assert subject_id == OWNER and tenant_ref == "tenant.connector"
            return ConnectorEnrollmentScope(
                owner_subject_id=subject_id,
                account_ref="account.connector", workspace_ref="workspace.connector",
            )

    class ExistingCredentialAuthority:
        def __init__(self):
            self.delivered = []

        def ready(self, *, challenge_id, device_id, now):
            return True

        def deliver_once(self, *, challenge_id, device_id, credential, receipt, now):
            assert receipt.enrollment.challenge_id == challenge_id
            assert receipt.device_id == device_id and credential
            self.delivered.append(credential)
            return True

    broker = InMemoryLocalAgentBrokerAuthority(
        pepper=b"b" * 32, authority_ref="control-plane.local-agent-broker.test.v1",
    )
    pairing = InMemoryBrokerPairingAuthority(
        pepper=b"p" * 32, authority=broker,
    )
    credential_sink = ExistingCredentialAuthority()
    service = CanonicalConnectorEnrollmentServer(
        allowed_product_ids=frozenset({"b54-padiem-claw"}),
        scope_resolver=Scope(), pairing_authority=pairing,
        consent_authority=port, session_authority=port,
        credential_handoff=credential_sink, binding_revoker=broker,
    )
    issued = service.issue(verified_session=session(), device_id=DEVICE, now=NOW)
    assert issued.challenge.challenge_id
    assert storage.db.execute(
        "SELECT count(*) FROM canonical_connector_enrollment_session_binding"
    ).fetchone()[0] == 1
    proof = pairing_proof_ref(
        challenge_id=issued.challenge.challenge_id,
        device_id=DEVICE, pairing_code=issued.pairing_code,
    )
    result = service.redeem(
        challenge_id=issued.challenge.challenge_id,
        device_id=DEVICE, proof_ref=proof, now=NOW + timedelta(seconds=1),
    )
    assert result.safe_dict()["lifecycle"] == "paired_offline"
    assert result.safe_dict()["raw_device_credential"] is False
    assert len(credential_sink.delivered) == 1
    assert len(broker._bindings) == 1
    assert canonical_reader.queries == ["session.connector.1", "session.connector.1"]


def test_actual_s1_durable_withdrawal_at_redeem_refuses_without_binding():
    from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
    from padiem_control_plane.local_agent_broker_pairing import (
        InMemoryBrokerPairingAuthority, pairing_proof_ref,
    )
    from padiem_control_plane.padiem_connector_enrollment import ConnectorEnrollmentScope
    from padiem_control_plane.padiem_connector_enrollment_server import CanonicalConnectorEnrollmentServer

    port, _, _ = fixture()
    port.install_schema()
    port.persist_preverified_consent(consent=consent(), now=NOW)

    class Scope:
        def resolve_scope(self, *, subject_id, tenant_ref, now):
            return ConnectorEnrollmentScope(
                owner_subject_id=subject_id,
                account_ref="account.connector", workspace_ref="workspace.connector",
            )

    class ReadySink:
        def ready(self, *, challenge_id, device_id, now):
            return True

        def deliver_once(self, *, challenge_id, device_id, credential, receipt, now):
            raise AssertionError("revoked consent must never deliver a credential")

    broker = InMemoryLocalAgentBrokerAuthority(
        pepper=b"b" * 32, authority_ref="control-plane.local-agent-broker.test.v1",
    )
    pairing = InMemoryBrokerPairingAuthority(
        pepper=b"p" * 32, authority=broker,
    )
    service = CanonicalConnectorEnrollmentServer(
        allowed_product_ids=frozenset({"b54-padiem-claw"}),
        scope_resolver=Scope(), pairing_authority=pairing,
        consent_authority=port, session_authority=port,
        credential_handoff=ReadySink(), binding_revoker=broker,
    )
    issued = service.issue(verified_session=session(), device_id=DEVICE, now=NOW)
    proof = pairing_proof_ref(
        challenge_id=issued.challenge.challenge_id,
        device_id=DEVICE, pairing_code=issued.pairing_code,
    )
    port.withdraw_preverified_consent(
        consent_id=CONSENT_ID, owner_subject_id=OWNER, now=NOW + timedelta(milliseconds=10)
    )
    assert error_code(lambda: service.redeem(
        challenge_id=issued.challenge.challenge_id,
        device_id=DEVICE, proof_ref=proof, now=NOW + timedelta(seconds=1),
    )) == "enrollment_consent_withdrawn"
    assert not broker._bindings
    assert pairing.pending_challenge_count == 1
