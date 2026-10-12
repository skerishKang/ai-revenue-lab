"""#4139 CENTRAL server seam — real S1 Broker authority, synthetic records only."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import (
    CanonicalSubjectRef, ControlPlaneContractError, SubjectType,
)
from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_pairing import (
    InMemoryBrokerPairingAuthority, pairing_proof_ref,
)
from padiem_control_plane.padiem_connector_enrollment import (
    ConnectorEnrollmentConsent, ConnectorEnrollmentScope,
)
from padiem_control_plane.padiem_connector_enrollment_server import (
    CanonicalConnectorEnrollmentServer,
    PRODUCTION_ACTIVATION,
    SERVER_ENROLLMENT_HTTP_BOUND,
)

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
USER = "usr_connector_owner_1"
DEVICE = "device.office-pc"
WORKSPACE = "workspace_connector_1"
ACCOUNT = "account_connector_1"
PRODUCT = "b54-padiem-claw"


class Scope:
    def resolve_scope(self, *, subject_id, tenant_ref, now):
        del tenant_ref, now
        return ConnectorEnrollmentScope(
            owner_subject_id=subject_id, account_ref=ACCOUNT, workspace_ref=WORKSPACE
        )


class Consents:
    def __init__(self):
        c = ConnectorEnrollmentConsent(
            consent_id="consent_connector_1",
            owner_subject_id=USER, account_ref=ACCOUNT, workspace_ref=WORKSPACE,
            device_id=DEVICE, granted_at=NOW - timedelta(minutes=1),
        )
        self.records = {c.consent_id: c}
        self.calls = []

    def current_for_device(self, *, owner_subject_id, device_id, now):
        self.calls.append(("device", now))
        for c in self.records.values():
            if c.owner_subject_id == owner_subject_id and c.device_id == device_id:
                return c
        return None

    def current_consent(self, *, consent_id, now):
        self.calls.append(("liveness", now))
        return self.records.get(consent_id)

    def withdraw(self):
        current = self.records["consent_connector_1"]
        self.records[current.consent_id] = replace(
            current, withdrawn_at=NOW + timedelta(microseconds=1)
        )


class Sessions:
    def __init__(self):
        self.records = {}
        self.fail = False

    def bind_challenge(self, *, challenge_id, session, expires_at, now):
        del now
        if self.fail:
            raise RuntimeError("offline")
        self.records[challenge_id] = (session, expires_at)

    def current_session(self, *, challenge_id, now):
        row = self.records.get(challenge_id)
        if row is None or now >= row[1]:
            return None
        return row[0]


class Handoff:
    def __init__(self):
        self.enabled = True
        self.delivered = []

    def ready(self, *, challenge_id, device_id, now):
        del challenge_id, device_id, now
        return self.enabled

    def deliver_once(self, *, challenge_id, device_id, credential, receipt, now):
        del now
        assert credential and isinstance(credential, bytes)
        assert receipt.device_id == device_id
        assert receipt.enrollment.challenge_id == challenge_id
        self.delivered.append((device_id, credential))
        return True


def session(**changes):
    args = dict(
        session_id="session_connector_1", product_id=PRODUCT,
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=USER),
        issued_at=NOW - timedelta(minutes=5), expires_at=NOW + timedelta(hours=1),
        tenant_id="tenant_padiem_1", state=AuthSessionState.ACTIVE,
    )
    args.update(changes)
    return AuthSessionSnapshot(**args)


def make_server(*, missing=None):
    broker = InMemoryLocalAgentBrokerAuthority(
        pepper=b"b" * 32, authority_ref="control-plane.local-agent-broker.test.v1"
    )
    pairing = InMemoryBrokerPairingAuthority(
        pepper=b"p" * 32, authority=broker,
    )
    consents = Consents()
    sessions = Sessions()
    handoff = Handoff()
    ports = dict(
        allowed_product_ids=frozenset({PRODUCT}),
        scope_resolver=Scope(), pairing_authority=pairing,
        consent_authority=consents, session_authority=sessions,
        credential_handoff=handoff,
    )
    if missing:
        ports[missing] = None
    return CanonicalConnectorEnrollmentServer(**ports), broker, pairing, consents, sessions, handoff


def issue_and_proof(srv):
    issued = srv.issue(verified_session=session(), device_id=DEVICE, now=NOW)
    proof = pairing_proof_ref(
        challenge_id=issued.challenge.challenge_id, device_id=DEVICE,
        pairing_code=issued.pairing_code,
    )
    return issued, proof


@pytest.mark.parametrize("missing", [
    "scope_resolver", "pairing_authority", "consent_authority",
    "session_authority", "credential_handoff",
])
def test_no_server_authority_means_no_challenge_minted(missing):
    srv, broker, pairing, *_ = make_server(missing=missing)
    with pytest.raises(ControlPlaneContractError) as exc:
        srv.issue(verified_session=session(), device_id=DEVICE, now=NOW)
    assert exc.value.code == "enrollment_server_dependency_unavailable"
    assert pairing.pending_challenge_count == 0
    assert not broker._bindings


def test_issue_requires_server_verified_canonical_session_and_per_pc_consent():
    srv, broker, pairing, consents, _, _ = make_server()
    with pytest.raises(ControlPlaneContractError) as exc:
        srv.issue(verified_session=None, device_id=DEVICE, now=NOW)
    assert exc.value.code == "canonical_session_required"
    with pytest.raises(ControlPlaneContractError) as exc:
        srv.issue(verified_session=session(), device_id="device.other", now=NOW)
    assert exc.value.code == "enrollment_consent_required"
    assert not broker._bindings
    assert pairing.pending_challenge_count == 0
    assert consents.calls


def test_success_requires_s1_scoped_redemption_and_existing_credential_handoff():
    srv, broker, pairing, consents, _, sink = make_server()
    issued, proof = issue_and_proof(srv)
    assert pairing.pending_challenge_count == 1
    # A generic possession proof must NOT bypass the S1 server-bound consent.
    with pytest.raises(ControlPlaneContractError) as bypass:
        pairing.redeem(
            challenge_id=issued.challenge.challenge_id, device_id=DEVICE,
            proof_ref=proof, now=NOW + timedelta(seconds=1)
        )
    assert bypass.value.code == "enrollment_bound_challenge_requires_scoped_redemption"
    assert not broker._bindings
    result = srv.redeem(
        challenge_id=issued.challenge.challenge_id, device_id=DEVICE,
        proof_ref=proof, now=NOW + timedelta(seconds=1),
    )
    assert result.device_id == DEVICE and result.binding_ref
    assert len(broker._bindings) == 1
    assert len(sink.delivered) == 1 and sink.delivered[0][0] == DEVICE
    safe = result.safe_dict()
    assert safe["raw_device_credential"] is False
    assert safe["lifecycle"] == "paired_offline"
    assert "credential" not in safe and "credential_b64" not in safe
    assert sum(t == "liveness" for t, _ in consents.calls) >= 3


def test_handoff_unready_refuses_before_consuming_challenge_or_binding():
    srv, broker, pairing, _, _, sink = make_server()
    issued, proof = issue_and_proof(srv)
    sink.enabled = False
    with pytest.raises(ControlPlaneContractError) as exc:
        srv.redeem(
            challenge_id=issued.challenge.challenge_id, device_id=DEVICE,
            proof_ref=proof, now=NOW + timedelta(seconds=1),
        )
    assert exc.value.code == "enrollment_server_dependency_unavailable"
    assert not broker._bindings
    assert pairing.pending_challenge_count == 1


def test_withdrawal_after_issue_fails_closed_without_binding():
    srv, broker, pairing, store, _, sink = make_server()
    issued, proof = issue_and_proof(srv)
    store.withdraw()
    with pytest.raises(ControlPlaneContractError) as exc:
        srv.redeem(
            challenge_id=issued.challenge.challenge_id, device_id=DEVICE,
            proof_ref=proof, now=NOW + timedelta(seconds=1),
        )
    assert exc.value.code == "enrollment_consent_withdrawn"
    assert not broker._bindings
    assert pairing.pending_challenge_count == 1
    assert sink.delivered == []


def test_session_revoked_after_issue_blocks_scoped_redeem():
    srv, broker, pairing, _, sessions, sink = make_server()
    issued, proof = issue_and_proof(srv)
    sessions.records[issued.challenge.challenge_id] = (
        session(state=AuthSessionState.REVOKED), issued.expires_at
    )
    with pytest.raises(ControlPlaneContractError) as exc:
        srv.redeem(
            challenge_id=issued.challenge.challenge_id, device_id=DEVICE,
            proof_ref=proof, now=NOW + timedelta(seconds=1),
        )
    assert exc.value.code == "canonical_session_inactive"
    assert not broker._bindings and not sink.delivered


def test_wrong_device_and_original_session_record_missing_fail_closed():
    srv, broker, pairing, _, sessions, _ = make_server()
    issued, proof = issue_and_proof(srv)
    with pytest.raises(ControlPlaneContractError) as exc:
        srv.redeem(
            challenge_id=issued.challenge.challenge_id, device_id="device.other",
            proof_ref=proof, now=NOW + timedelta(seconds=1),
        )
    assert exc.value.code == "enrollment_device_or_owner_mismatch"
    sessions.records.clear()
    with pytest.raises(ControlPlaneContractError) as exc:
        srv.redeem(
            challenge_id=issued.challenge.challenge_id, device_id=DEVICE,
            proof_ref=proof, now=NOW + timedelta(seconds=1),
        )
    assert exc.value.code == "canonical_session_required"
    assert not broker._bindings
    assert pairing.pending_challenge_count == 1


def test_issuance_session_record_failure_does_not_leak_one_time_code():
    srv, broker, pairing, _, sessions, sink = make_server()
    sessions.fail = True
    with pytest.raises(ControlPlaneContractError) as exc:
        srv.issue(verified_session=session(), device_id=DEVICE, now=NOW)
    assert exc.value.code == "enrollment_server_dependency_unavailable"
    # An orphan challenge is deny-only because no canonical session was stored.
    assert pairing.pending_challenge_count == 1
    assert not broker._bindings and not sink.delivered


def test_invalid_clock_or_proof_ref_and_production_gate():
    srv, broker, _, _, _, _ = make_server()
    with pytest.raises(ControlPlaneContractError):
        srv.issue(verified_session=session(), device_id=DEVICE, now=datetime(2026, 10, 12))
    with pytest.raises(ControlPlaneContractError):
        srv.redeem(challenge_id="bad space", device_id=DEVICE, proof_ref="bad", now=NOW)
    assert SERVER_ENROLLMENT_HTTP_BOUND is False
    assert PRODUCTION_ACTIVATION is False
    assert not broker._bindings
