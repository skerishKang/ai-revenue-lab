"""#4139 S1 — PADIEM Connector server-side enrollment contract tests.

Scope of this suite: the **new** server-side seam only. The canonical pairing
authority, the canonical Broker binding/rotation/revocation authority, the
canonical auth-session contract and the product PC access contract already have
their own suites, so those are *reused* here rather than re-tested:

  S1-01  a verified canonical PADIEM session + active consent is enrollment-eligible
  S1-02  no canonical session -> refused (canonical_session_required)
  S1-03  revoked or expired session -> refused (canonical_session_inactive)
  S1-04  a non-USER canonical subject -> refused (canonical_subject_not_user)
  S1-05  a session without a canonical tenant -> refused (canonical_tenant_required)
  S1-06  a session from an unreviewed product -> refused; no second product registry
  S1-07  a scope resolved for another owner is refused (enrollment_scope_owner_mismatch)
  S1-08  an unconfigured/broken scope resolver fails closed, never guesses a scope
  S1-09  a product-scoped scope is refused (one PC id is shared by every product)
  S1-10  enrollment consent is mandatory and must be the canonical consent record
  S1-11  a withdrawn consent refuses enrollment
  S1-12  consent for another user or another workspace is refused
  S1-13  the issued challenge is scoped to the server-derived account/workspace
  S1-14  an ineligible account cannot mint a challenge (bounded reason, no text echo)
  S1-15  full path: issue -> redeem -> the PC authenticates against the canonical Broker
  S1-16  a wrong device-ownership proof is refused, and upstream text is not echoed
  S1-17  a challenge is single-use (enrollment_duplicate_redeem_denied)
  S1-18  a second product enrolling the SAME PC is refused as a duplicate binding
  S1-19  the same owner may enroll a genuinely different PC (per-device proof)
  S1-20  a session revoked between issue and redeem refuses the redemption
  S1-21  a consent withdrawn between issue and redeem refuses the redemption
  S1-22  redeeming another account's challenge cannot bind this account's identity
  S1-23  the receipt returns the device credential exactly once, never in safe_dict
  S1-24  enrollment mints no execution approval and never authorizes dispatch
  S1-25  no second login system / device DB / pairing / credential authority exists
  S1-26  the refusal mapping and code/reference grammar still match their canonical sources
  S1-27  unsupported Connector auth methods are recorded as dependencies, not invented
  S1-28  the #4429 product default stays OFF and the boundary projection is unchanged
  S1-29  the canonical issuance rate bound surfaces as a bounded enrollment reason
  S1-30  only verified canonical facts are handed to the scope resolver
  S1-31  an unconfigured pairing authority is a bounded refusal

CENTRAL security review follow-up (BLOCKED_CONSENT_CHALLENGE_BINDING):

  S1-32  consent A issue -> consent B redeem is refused (no swap), 0 bindings created
  S1-33  consent A withdrawn -> B issued -> the old A challenge refuses with B and with A
  S1-34  one consent cannot enroll a second computer (issue and redeem both refuse)
  S1-35  two computers each need their own explicit enrollment consent
  S1-36  a fabricated / foreign challenge receipt is never accepted as proof
  S1-37  the binding is verified BEFORE any mutating redemption or consumption
  S1-38  consent liveness is default-deny until the declared authority is wired
  S1-39  the binding lives in the canonical pairing authority, never in a client receipt
  S1-40  a challenge issued without an enrollment binding cannot be redeemed as one
  S1-41  another canonical owner cannot redeem this challenge (owner mismatch)
  S1-42  another account/workspace scope cannot redeem this challenge (scope mismatch)
  S1-43  the new refusals and declarations stay parity-checked with the canonical sources
  S1-44  no new authority/store is introduced by the follow-up either
  S1-45  neither the one-time code nor the credential ever appears in a projection
"""

from __future__ import annotations

import inspect
from pathlib import Path
import re
from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane import padiem_connector_enrollment as enrollment_module
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)
from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_auth import authenticate_local_agent_binding
from padiem_control_plane.local_agent_broker_pairing import (
    PAIRING_CODE_HEX_CHARS,
    PAIRING_PROOF_TRANSCRIPT,
    PROOF_REF_RE,
    _SAFE_REF_RE as CANONICAL_SAFE_REF_RE,
    BrokerPairingEnrollmentBinding,
    InMemoryBrokerPairingAuthority,
    UnconfiguredBrokerPairingAuthority,
    pairing_proof_ref,
)
from padiem_control_plane.local_agent_pc_access import PRODUCT_PC_ACCESS_DEFAULT
from padiem_control_plane.padiem_connector_enrollment import (
    CONSENT_BOUND_TO_DEVICE,
    CONNECTOR_ENROLLMENT_CONTRACT_VERSION,
    DEVICE_LIFECYCLE_AUTHORITY,
    ENROLLMENT_BINDING_VERIFIED_BEFORE_BROKER_MUTATION,
    ENROLLMENT_CODE_HEX_CHARS,
    ENROLLMENT_REFUSAL_BY_CANONICAL_CODE,
    ENROLLMENT_REFUSAL_FALLBACK,
    ENROLLMENT_REASON_BINDING_ABSENT,
    ENROLLMENT_REASON_BINDING_OWNER_MISMATCH,
    ENROLLMENT_REASON_BINDING_SCOPE_MISMATCH,
    ENROLLMENT_REASON_CONSENT_DEVICE_MISMATCH,
    ENROLLMENT_REASON_CONSENT_LIVENESS_DEPENDENCY_UNMET,
    ENROLLMENT_REASON_CONSENT_REQUIRED,
    ENROLLMENT_REASON_CONSENT_SCOPE_MISMATCH,
    ENROLLMENT_REASON_CONSENT_SWAP_DENIED,
    ENROLLMENT_REASON_CONSENT_WITHDRAWN,
    ENROLLMENT_REASON_DEVICE_SWAP_DENIED,
    ENROLLMENT_REASON_DEPENDENCY_UNAVAILABLE,
    ENROLLMENT_REASON_ELIGIBLE,
    ENROLLMENT_REASON_PRODUCT_NOT_REVIEWED,
    ENROLLMENT_REASON_PRODUCT_SCOPED_SCOPE,
    ENROLLMENT_REASON_SCOPE_OWNER_MISMATCH,
    ENROLLMENT_REASON_SCOPE_UNAVAILABLE,
    ENROLLMENT_REASON_SCOPE_UNVERIFIED,
    ENROLLMENT_REASON_SESSION_INACTIVE,
    ENROLLMENT_REASON_SESSION_REQUIRED,
    ENROLLMENT_REASON_SUBJECT_NOT_USER,
    ENROLLMENT_REASON_TENANT_REQUIRED,
    EXECUTION_APPROVAL_OWNER,
    ONE_CONSENT_PER_DEVICE,
    SERVER_BOUND_CHALLENGE_REQUIRED,
    UNSUPPORTED_AUTH_METHODS,
    UNSIGNED_CHALLENGE_RECEIPT_TRUSTED,
    ConnectorEnrollmentConsent,
    ConnectorEnrollmentScope,
    UnconfiguredCanonicalEnrollmentScopePort,
    connector_enrollment_boundary,
    connector_enrollment_dependencies,
    enrollment_refusal_reason,
    evaluate_connector_enrollment,
    issue_connector_enrollment_challenge,
    redeem_connector_enrollment,
)

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
CLAW = "b54-padiem-claw"
CHAT = "b62"
REVIEWED_PRODUCTS = frozenset({CLAW, CHAT})
BROKER_PEPPER = b"b" * 32
PAIRING_PEPPER = b"p" * 32
AUTHORITY_REF = "control-plane.local-agent-broker.test.v1"
SUBJECT = "usr_connector_owner_1"
OTHER_SUBJECT = "usr_connector_owner_2"
TENANT = "tenant_padiem_1"
ACCOUNT_REF = "account_connector_1"
OTHER_ACCOUNT_REF = "account_connector_2"
WORKSPACE_REF = "workspace_connector_1"
OTHER_WORKSPACE_REF = "workspace_connector_2"
OFFICE_PC = "device.office-pc"
LAPTOP = "device.laptop-pc"
CONSENT_1 = "consent_connector_1"
CONSENT_2 = "consent_connector_2"


def _session(
    *,
    subject_id: str = SUBJECT,
    subject_type: SubjectType = SubjectType.USER,
    product_id: str = CLAW,
    tenant_id: str | None = TENANT,
    state: AuthSessionState = AuthSessionState.ACTIVE,
    issued_at: datetime = NOW - timedelta(minutes=5),
    expires_at: datetime = NOW + timedelta(hours=1),
    session_id: str = "session_connector_1",
) -> AuthSessionSnapshot:
    return AuthSessionSnapshot(
        session_id=session_id,
        product_id=product_id,
        subject=CanonicalSubjectRef(subject_type=subject_type, subject_id=subject_id),
        issued_at=issued_at,
        expires_at=expires_at,
        state=state,
        tenant_id=tenant_id,
    )


def _scope(
    *,
    owner_subject_id: str = SUBJECT,
    account_ref: str = ACCOUNT_REF,
    workspace_ref: str = WORKSPACE_REF,
    product_scoped: bool = False,
) -> ConnectorEnrollmentScope:
    return ConnectorEnrollmentScope(
        owner_subject_id=owner_subject_id,
        account_ref=account_ref,
        workspace_ref=workspace_ref,
        product_scoped=product_scoped,
    )


class _StaticScopeResolver:
    """Test double for the injected Control Plane owner resolver."""

    def __init__(self, scope: ConnectorEnrollmentScope | Exception) -> None:
        self._scope = scope
        self.calls: list[dict] = []

    def resolve_scope(self, *, subject_id: str, tenant_ref: str | None, now: datetime):
        self.calls.append({"subject_id": subject_id, "tenant_ref": tenant_ref, "now": now})
        if isinstance(self._scope, Exception):
            raise self._scope
        return self._scope


def _resolver(scope: ConnectorEnrollmentScope | Exception | None = None) -> _StaticScopeResolver:
    return _StaticScopeResolver(_scope() if scope is None else scope)


def _consent(
    *,
    consent_id: str = CONSENT_1,
    owner_subject_id: str = SUBJECT,
    account_ref: str = ACCOUNT_REF,
    workspace_ref: str = WORKSPACE_REF,
    device_id: str = OFFICE_PC,
    granted_at: datetime = NOW - timedelta(minutes=1),
    withdrawn_at: datetime | None = None,
) -> ConnectorEnrollmentConsent:
    return ConnectorEnrollmentConsent(
        consent_id=consent_id,
        owner_subject_id=owner_subject_id,
        account_ref=account_ref,
        workspace_ref=workspace_ref,
        device_id=device_id,
        granted_at=granted_at,
        withdrawn_at=withdrawn_at,
    )


def _broker_and_pairing(*, issuance_rate_limit: int | None = None):
    broker = InMemoryLocalAgentBrokerAuthority(pepper=BROKER_PEPPER, authority_ref=AUTHORITY_REF)
    pairing = InMemoryBrokerPairingAuthority(
        pepper=PAIRING_PEPPER,
        authority=broker,
        issuance_rate_limit=issuance_rate_limit,
    )
    return broker, pairing


def _evaluate(**overrides):
    kwargs = dict(
        auth_session=_session(),
        allowed_product_ids=REVIEWED_PRODUCTS,
        scope_resolver=_resolver(),
        consent=_consent(),
        now=NOW,
    )
    kwargs.update(overrides)
    return evaluate_connector_enrollment(**kwargs)


def _issue(*, pairing_authority=None, **overrides):
    """Issue a challenge with sane defaults; returns ``(pairing, receipt)``."""

    if pairing_authority is None:
        _, pairing_authority = _broker_and_pairing()
    kwargs = dict(
        auth_session=_session(),
        allowed_product_ids=REVIEWED_PRODUCTS,
        scope_resolver=_resolver(),
        consent=_consent(),
        device_id=OFFICE_PC,
        pairing_authority=pairing_authority,
        consent_liveness_reverified_by_existing_path=True,
        now=NOW,
    )
    kwargs.update(overrides)
    return pairing_authority, issue_connector_enrollment_challenge(**kwargs)


def _proof(receipt, *, device_id: str | None = None) -> str:
    return pairing_proof_ref(
        challenge_id=receipt.challenge.challenge_id,
        device_id=receipt.device_id if device_id is None else device_id,
        pairing_code=receipt.pairing_code,
    )


def _redeem(receipt, *, pairing_authority, proof_ref: str | None = None, **overrides):
    kwargs = dict(
        auth_session=_session(),
        allowed_product_ids=REVIEWED_PRODUCTS,
        scope_resolver=_resolver(),
        consent=_consent(),
        pairing_authority=pairing_authority,
        challenge_id=receipt.challenge.challenge_id,
        device_id=receipt.device_id,
        proof_ref=_proof(receipt) if proof_ref is None else proof_ref,
        consent_liveness_reverified_by_existing_path=True,
        now=NOW + timedelta(seconds=1),
    )
    kwargs.update(overrides)
    return redeem_connector_enrollment(**kwargs)


def _binding_count(broker) -> int:
    return len(broker._bindings)


# --- S1-01 .. S1-09: identity -> scope ---------------------------------------


def test_s1_01_verified_canonical_session_and_consent_are_eligible():
    decision = _evaluate()
    assert decision.eligible is True
    assert decision.reason == ENROLLMENT_REASON_ELIGIBLE
    assert decision.scope == _scope()
    assert decision.consent_id == CONSENT_1
    assert decision.dispatch_authorized is False
    assert decision.creates_login is False
    assert decision.creates_device_registry is False


def test_s1_02_a_missing_canonical_session_is_refused():
    for value in (None, {}, "session_connector_1"):
        decision = _evaluate(auth_session=value)
        assert decision.eligible is False
        assert decision.reason == ENROLLMENT_REASON_SESSION_REQUIRED
        assert decision.scope is None


def test_s1_03_revoked_or_expired_sessions_are_refused():
    revoked = _evaluate(auth_session=_session(state=AuthSessionState.REVOKED))
    assert revoked.reason == ENROLLMENT_REASON_SESSION_INACTIVE
    expired = _evaluate(
        auth_session=_session(
            issued_at=NOW - timedelta(hours=2),
            expires_at=NOW - timedelta(hours=1),
        )
    )
    assert expired.reason == ENROLLMENT_REASON_SESSION_INACTIVE


def test_s1_04_non_user_canonical_subjects_are_refused():
    decision = _evaluate(auth_session=_session(subject_type=SubjectType.ACCOUNT))
    assert decision.eligible is False
    assert decision.reason == ENROLLMENT_REASON_SUBJECT_NOT_USER


def test_s1_05_a_session_without_a_canonical_tenant_is_refused():
    decision = _evaluate(auth_session=_session(tenant_id=None))
    assert decision.eligible is False
    assert decision.reason == ENROLLMENT_REASON_TENANT_REQUIRED


def test_s1_06_unreviewed_product_sessions_are_refused_without_a_second_registry():
    decision = _evaluate(auth_session=_session(product_id="b66-padiem-quote"))
    assert decision.eligible is False
    assert decision.reason == ENROLLMENT_REASON_PRODUCT_NOT_REVIEWED
    assert _evaluate(allowed_product_ids=frozenset()).reason == ENROLLMENT_REASON_PRODUCT_NOT_REVIEWED
    assert _evaluate(allowed_product_ids={"b54-padiem-claw"}).reason == (
        ENROLLMENT_REASON_PRODUCT_NOT_REVIEWED
    )
    # The reviewed set is an input from the canonical identity authority: the
    # contract declares no product ids of its own.
    assert REVIEWED_PRODUCTS >= {"b54-padiem-claw", "b62"}


def test_s1_07_a_scope_for_another_owner_is_refused():
    decision = _evaluate(scope_resolver=_resolver(_scope(owner_subject_id=OTHER_SUBJECT)))
    assert decision.eligible is False
    assert decision.reason == ENROLLMENT_REASON_SCOPE_OWNER_MISMATCH


def test_s1_08_a_broken_scope_resolver_fails_closed():
    unconfigured = _evaluate(scope_resolver=UnconfiguredCanonicalEnrollmentScopePort())
    assert unconfigured.eligible is False
    assert unconfigured.reason == ENROLLMENT_REASON_SCOPE_UNAVAILABLE
    assert _evaluate(scope_resolver=_resolver(RuntimeError("down"))).reason == (
        ENROLLMENT_REASON_SCOPE_UNAVAILABLE
    )
    assert _evaluate(scope_resolver=_resolver("account_connector_1")).reason == (
        ENROLLMENT_REASON_SCOPE_UNVERIFIED
    )


def test_s1_09_a_product_scoped_scope_is_refused():
    with pytest.raises(ControlPlaneContractError) as raised:
        _scope(product_scoped=True)
    assert raised.value.code == ENROLLMENT_REASON_PRODUCT_SCOPED_SCOPE
    product_scoped = _resolver(
        ControlPlaneContractError(ENROLLMENT_REASON_PRODUCT_SCOPED_SCOPE, "product scoped scope")
    )
    decision = _evaluate(scope_resolver=product_scoped)
    assert decision.eligible is False
    assert decision.reason == ENROLLMENT_REASON_PRODUCT_SCOPED_SCOPE


# --- S1-10 .. S1-12: enrollment consent --------------------------------------


def test_s1_10_enrollment_consent_is_mandatory():
    assert _evaluate(consent=None).reason == ENROLLMENT_REASON_CONSENT_REQUIRED
    assert _evaluate(consent="consented").reason == ENROLLMENT_REASON_CONSENT_REQUIRED


def test_s1_11_a_withdrawn_consent_refuses_enrollment():
    withdrawn = _consent(withdrawn_at=NOW - timedelta(seconds=30))
    assert withdrawn.is_active(now=NOW) is False
    assert _evaluate(consent=withdrawn).reason == ENROLLMENT_REASON_CONSENT_WITHDRAWN


def test_s1_12_consent_for_another_user_or_workspace_is_refused():
    assert _evaluate(consent=_consent(owner_subject_id=OTHER_SUBJECT)).reason == (
        ENROLLMENT_REASON_CONSENT_SCOPE_MISMATCH
    )
    assert _evaluate(consent=_consent(workspace_ref=OTHER_WORKSPACE_REF)).reason == (
        ENROLLMENT_REASON_CONSENT_SCOPE_MISMATCH
    )
    assert _evaluate(consent=_consent(account_ref=OTHER_ACCOUNT_REF)).reason == (
        ENROLLMENT_REASON_CONSENT_SCOPE_MISMATCH
    )


# --- S1-13 .. S1-14: challenge issuance --------------------------------------


def test_s1_13_the_challenge_is_scoped_to_the_server_derived_scope():
    resolver = _resolver()
    pairing, receipt = _issue(scope_resolver=resolver)
    assert receipt.challenge.account_ref == ACCOUNT_REF
    assert receipt.challenge.workspace_ref == WORKSPACE_REF
    assert receipt.challenge.issued_at == NOW
    assert receipt.challenge.expires_at > NOW
    assert receipt.scope == _scope()
    assert receipt.consent_id == CONSENT_1
    assert receipt.device_id == OFFICE_PC
    assert re.fullmatch(rf"[0-9a-f]{{{PAIRING_CODE_HEX_CHARS}}}", receipt.pairing_code)
    assert pairing.pending_challenge_count == 1
    assert resolver.calls == [{"subject_id": SUBJECT, "tenant_ref": TENANT, "now": NOW}]
    # The server recorded the binding itself; nothing about it came from a client.
    stored = pairing.enrollment_binding(challenge_id=receipt.challenge.challenge_id, now=NOW)
    assert isinstance(stored, BrokerPairingEnrollmentBinding)
    assert stored.consent_ref == CONSENT_1
    assert stored.owner_ref == SUBJECT
    assert stored.device_id == OFFICE_PC
    assert stored.account_ref == ACCOUNT_REF
    assert stored.workspace_ref == WORKSPACE_REF
    assert stored.bound_at == NOW
    assert stored.safe_dict()["client_supplied_receipt_trusted"] is False


def test_s1_14_an_ineligible_account_cannot_mint_a_challenge():
    _, pairing = _broker_and_pairing()
    with pytest.raises(ControlPlaneContractError) as raised:
        _issue(pairing_authority=pairing, auth_session=_session(state=AuthSessionState.REVOKED))
    assert raised.value.code == ENROLLMENT_REASON_SESSION_INACTIVE
    with pytest.raises(ControlPlaneContractError) as no_consent:
        _issue(pairing_authority=pairing, consent=None)
    assert no_consent.value.code == ENROLLMENT_REASON_CONSENT_REQUIRED
    assert pairing.pending_challenge_count == 0
    assert "revoke" not in str(raised.value.safe_message).lower()


# --- S1-15 .. S1-19: the registered PC ---------------------------------------


def test_s1_15_issue_then_redeem_registers_the_pc_in_the_canonical_broker():
    broker, pairing = _broker_and_pairing()
    _, receipt = _issue(pairing_authority=pairing)
    redeemed = _redeem(receipt, pairing_authority=pairing)
    assert redeemed.device_id == OFFICE_PC
    assert redeemed.credential_generation == 1
    assert redeemed.scope == _scope()
    assert redeemed.binding.consent_ref == CONSENT_1

    binding = authenticate_local_agent_binding(
        broker,
        binding_ref=redeemed.binding_ref,
        credential=redeemed.credential,
        now=NOW + timedelta(seconds=2),
    )
    assert binding.device_id == OFFICE_PC
    assert binding.account_ref == ACCOUNT_REF
    assert binding.workspace_ref == WORKSPACE_REF
    assert binding.binding_ref == redeemed.binding_ref
    assert _binding_count(broker) == 1


def test_s1_16_a_wrong_ownership_proof_is_refused_without_echoing_upstream_text():
    broker, pairing = _broker_and_pairing()
    _, receipt = _issue(pairing_authority=pairing)
    with pytest.raises(ControlPlaneContractError) as raised:
        _redeem(receipt, pairing_authority=pairing, proof_ref="pairing-proof:" + "0" * 64)
    assert raised.value.code == "enrollment_proof_invalid"
    assert "proof is invalid" not in raised.value.safe_message
    with pytest.raises(ControlPlaneContractError) as bad_ref:
        _redeem(receipt, pairing_authority=pairing, proof_ref="not-a-proof")
    assert bad_ref.value.code == "enrollment_proof_invalid"
    assert _binding_count(broker) == 0
    # A rejected proof never consumes the challenge.
    assert pairing.pending_challenge_count == 1


def test_s1_17_a_challenge_is_single_use():
    broker, pairing = _broker_and_pairing()
    _, receipt = _issue(pairing_authority=pairing)
    _redeem(receipt, pairing_authority=pairing)
    with pytest.raises(ControlPlaneContractError) as raised:
        _redeem(
            receipt,
            pairing_authority=pairing,
            now=NOW + timedelta(seconds=2),
        )
    assert raised.value.code == "enrollment_duplicate_redeem_denied"
    assert _binding_count(broker) == 1


def test_s1_18_a_second_product_cannot_enroll_the_same_pc():
    broker, pairing = _broker_and_pairing()

    def enroll(product_id: str):
        _, receipt = _issue(
            pairing_authority=pairing,
            auth_session=_session(product_id=product_id),
        )
        return _redeem(
            receipt,
            pairing_authority=pairing,
            auth_session=_session(product_id=product_id),
        )

    first = enroll(CLAW)
    with pytest.raises(ControlPlaneContractError) as raised:
        enroll(CHAT)
    assert raised.value.code == "enrollment_duplicate_device_denied"
    bindings = [b for b in broker._bindings.values() if b.device_id == OFFICE_PC]
    assert len(bindings) == 1
    assert bindings[0].binding_ref == first.binding_ref


def test_s1_19_the_same_owner_may_enroll_a_genuinely_different_pc():
    broker, pairing = _broker_and_pairing()
    bindings = []
    for index, device_id in enumerate((OFFICE_PC, LAPTOP)):
        _, receipt = _issue(
            pairing_authority=pairing,
            consent=_consent(consent_id=f"consent_connector_{index + 1}", device_id=device_id),
            device_id=device_id,
        )
        redeemed = _redeem(
            receipt,
            pairing_authority=pairing,
            consent=_consent(consent_id=f"consent_connector_{index + 1}", device_id=device_id),
        )
        bindings.append(redeemed.binding_ref)
    assert len(set(bindings)) == 2
    assert {b.device_id for b in broker._bindings.values()} == {OFFICE_PC, LAPTOP}


# --- S1-20 .. S1-23: account change, redemption, receipt ---------------------


def test_s1_20_a_session_revoked_between_issue_and_redeem_refuses_redemption():
    broker, pairing = _broker_and_pairing()
    _, receipt = _issue(pairing_authority=pairing)
    with pytest.raises(ControlPlaneContractError) as raised:
        _redeem(
            receipt,
            pairing_authority=pairing,
            auth_session=_session(state=AuthSessionState.REVOKED),
        )
    assert raised.value.code == ENROLLMENT_REASON_SESSION_INACTIVE
    with pytest.raises(ControlPlaneContractError) as other_account:
        _redeem(
            receipt,
            pairing_authority=pairing,
            auth_session=_session(subject_id=OTHER_SUBJECT, session_id="session_connector_2"),
            scope_resolver=_resolver(
                _scope(owner_subject_id=OTHER_SUBJECT, account_ref=OTHER_ACCOUNT_REF)
            ),
            consent=_consent(
                owner_subject_id=OTHER_SUBJECT,
                account_ref=OTHER_ACCOUNT_REF,
                device_id=OFFICE_PC,
            ),
        )
    assert other_account.value.code == ENROLLMENT_REASON_BINDING_OWNER_MISMATCH
    assert _binding_count(broker) == 0
    assert pairing.pending_challenge_count == 1


def test_s1_21_a_consent_withdrawn_between_issue_and_redeem_refuses_redemption():
    broker, pairing = _broker_and_pairing()
    _, receipt = _issue(pairing_authority=pairing)
    with pytest.raises(ControlPlaneContractError) as raised:
        _redeem(
            receipt,
            pairing_authority=pairing,
            consent=_consent(withdrawn_at=NOW + timedelta(microseconds=1)),
        )
    assert raised.value.code == ENROLLMENT_REASON_CONSENT_WITHDRAWN
    assert _binding_count(broker) == 0


def test_s1_22_redeeming_another_accounts_challenge_cannot_bind_this_account():
    broker, pairing = _broker_and_pairing()
    _, receipt = _issue(pairing_authority=pairing)
    other_scope = _scope(owner_subject_id=OTHER_SUBJECT, account_ref=OTHER_ACCOUNT_REF)
    with pytest.raises(ControlPlaneContractError) as raised:
        _redeem(
            receipt,
            pairing_authority=pairing,
            auth_session=_session(subject_id=OTHER_SUBJECT, session_id="session_connector_2"),
            scope_resolver=_resolver(other_scope),
            consent=_consent(
                owner_subject_id=OTHER_SUBJECT,
                account_ref=OTHER_ACCOUNT_REF,
                device_id=OFFICE_PC,
            ),
        )
    assert raised.value.code == ENROLLMENT_REASON_BINDING_OWNER_MISMATCH
    for binding in broker._bindings.values():
        assert binding.account_ref == ACCOUNT_REF
        assert binding.account_ref != OTHER_ACCOUNT_REF
    assert _binding_count(broker) == 0


def test_s1_23_the_receipt_returns_the_credential_once_and_never_in_safe_dict():
    _, pairing = _broker_and_pairing()
    _, receipt = _issue(pairing_authority=pairing)
    redeemed = _redeem(receipt, pairing_authority=pairing)
    assert isinstance(redeemed.credential, bytes) and redeemed.credential
    projection = redeemed.safe_dict()
    assert projection["raw_device_credential"] is False
    assert projection["credential_returned_once"] is True
    assert projection["credential_generation"] == 1
    encoded = repr(projection)
    assert redeemed.credential.hex() not in encoded
    assert SUBJECT not in encoded and TENANT not in encoded
    assert "owner_subject_ref" in projection
    assert projection["device_lifecycle_authority"] == DEVICE_LIFECYCLE_AUTHORITY
    assert projection["execution_approval_owner"] == EXECUTION_APPROVAL_OWNER
    challenge_projection = receipt.safe_dict()
    assert challenge_projection["pairing_code"] is None
    assert receipt.pairing_code not in repr(challenge_projection)


# --- S1-24 .. S1-31: no new authority, no dispatch, posture, edges -----------


def test_s1_24_enrollment_mints_no_execution_approval_and_never_authorizes_dispatch():
    decision = _evaluate()
    projection = decision.safe_dict()
    assert projection["dispatch_authorized"] is False
    assert projection["execution_approval_minted"] is False
    assert projection["execution_approval_owner"] == EXECUTION_APPROVAL_OWNER
    assert projection["creates_login"] is False
    assert projection["creates_device_registry"] is False
    with pytest.raises((AttributeError, TypeError)):
        decision.dispatch_authorized = True
    assert decision.dispatch_authorized is False


def test_s1_25_no_second_login_device_db_or_pairing_authority_exists():
    dependencies = connector_enrollment_dependencies()
    for key in (
        "second_login_system",
        "second_device_db",
        "second_pairing_authority",
        "second_credential_store",
        "second_rotation_authority",
        "second_revocation_authority",
        "second_enrollment_store",
        "new_authority_created",
        "new_auth_method_invented",
    ):
        assert dependencies[key] is False, key
    assert dependencies["enrollment_consent_is_execution_approval"] is False
    assert dependencies["dispatch_authorized"] is False

    source = inspect.getsource(enrollment_module)
    assert "import hmac" not in source
    assert "import secrets" not in source
    assert "sqlite" not in source.lower()
    assert "CREATE TABLE" not in source
    definitions = re.findall(r"^class (\w+)", source, flags=re.MULTILINE)
    assert set(definitions) == {
        "ConnectorEnrollmentScope",
        "ConnectorEnrollmentConsent",
        "ConnectorEnrollmentDecision",
        "ConnectorEnrollmentChallengeReceipt",
        "ConnectorEnrollmentReceipt",
        "CanonicalEnrollmentScopePort",
        "UnconfiguredCanonicalEnrollmentScopePort",
    }
    assert not any(name.endswith("Authority") for name in definitions)
    assert "from .auth_sessions import" in source
    assert "from .local_agent_broker_pairing import" in source
    assert "from .local_agent_pc_access import" in source


def test_s1_26_the_refusal_mapping_matches_the_canonical_sources():
    package_root = Path(enrollment_module.__file__).parent
    pairing_source = (package_root / "local_agent_broker_pairing.py").read_text(encoding="utf-8")
    broker_source = (package_root / "local_agent_broker.py").read_text(encoding="utf-8")
    for canonical_code in ENROLLMENT_REFUSAL_BY_CANONICAL_CODE:
        assert (
            f'"{canonical_code}"' in pairing_source or f'"{canonical_code}"' in broker_source
        ), canonical_code
    assert ENROLLMENT_REFUSAL_FALLBACK not in ENROLLMENT_REFUSAL_BY_CANONICAL_CODE.values()
    assert enrollment_refusal_reason("pairing_challenge_expired") == "enrollment_challenge_expired"
    assert enrollment_refusal_reason("something_unknown") == ENROLLMENT_REFUSAL_FALLBACK
    assert enrollment_refusal_reason(None) == ENROLLMENT_REFUSAL_FALLBACK
    assert CANONICAL_SAFE_REF_RE.pattern == enrollment_module._SAFE_REF_RE.pattern
    assert PROOF_REF_RE.pattern == enrollment_module.PROOF_REF_RE.pattern
    assert ENROLLMENT_CODE_HEX_CHARS == PAIRING_CODE_HEX_CHARS
    assert PAIRING_PROOF_TRANSCRIPT == enrollment_module.PROOF_TRANSCRIPT
    assert enrollment_module.CANONICAL_PAIRING_AUTHORITY.startswith(
        "padiem_control_plane.local_agent_broker_pairing."
    )


def test_s1_27_unsupported_connector_auth_methods_are_recorded_as_dependencies():
    methods = dict(UNSUPPORTED_AUTH_METHODS)
    assert "oidc_device_authorization_grant_rfc8628" in methods
    assert all(reason for reason in methods.values())
    dependencies = connector_enrollment_dependencies()
    assert dependencies["unsupported_auth_method_count"] == len(UNSUPPORTED_AUTH_METHODS)
    assert dependencies["new_auth_method_invented"] is False
    source = inspect.getsource(enrollment_module)
    for forbidden in ("client_secret", "password_hash", "token_endpoint", "authorization_code"):
        assert forbidden not in source


def test_s1_28_the_product_default_stays_off_and_the_boundary_is_unchanged():
    assert PRODUCT_PC_ACCESS_DEFAULT == "off"
    boundary = connector_enrollment_boundary()
    assert boundary["product_pc_access_default"] == "off"
    assert boundary["product_scoped_enrollment"] is False
    assert boundary["shared_device_identity_across_products"] is True
    assert boundary["enrollment_consent_required"] is True
    assert boundary["enrollment_consent_is_execution_approval"] is False
    assert boundary["enrollment_consent_grants_read"] is False
    assert boundary["enrollment_consent_grants_write"] is False
    assert boundary["enrollment_consent_grants_dispatch"] is False
    assert boundary["device_possession_proof_required"] is True
    assert boundary["self_asserted_device_ownership"] is False
    assert boundary["self_asserted_account_workspace_authority"] is False
    assert boundary["dispatch_authorized_by_this_contract"] is False
    assert boundary["pc_execution_path_newly_wired"] is False
    assert boundary["production_activation"] is False
    assert boundary["production_ready"] is False
    assert boundary["refusal_text_echoed"] is False
    assert boundary["contract_version"] == CONNECTOR_ENROLLMENT_CONTRACT_VERSION


def test_s1_29_the_canonical_issuance_bound_surfaces_as_a_bounded_reason():
    _, pairing = _broker_and_pairing(issuance_rate_limit=1)
    _issue(pairing_authority=pairing)
    with pytest.raises(ControlPlaneContractError) as raised:
        _issue(pairing_authority=pairing, now=NOW + timedelta(seconds=1))
    assert raised.value.code == "enrollment_rate_limited"
    assert "exceeded" not in raised.value.safe_message
    assert "per-scope" not in raised.value.safe_message


def test_s1_30_only_verified_canonical_facts_reach_the_scope_resolver():
    resolver = _resolver()
    decision = _evaluate(scope_resolver=resolver)
    assert decision.eligible is True
    assert len(resolver.calls) == 1
    call = resolver.calls[0]
    assert set(call) == {"subject_id", "tenant_ref", "now"}
    assert call["subject_id"] == SUBJECT
    assert call["tenant_ref"] == TENANT
    assert call["now"] == NOW
    source = inspect.getsource(enrollment_module.evaluate_connector_enrollment)
    assert "device_id" not in source
    assert "session_id" not in source
    assert _evaluate(scope_resolver=resolver).scope == _scope()


def test_s1_31_an_unconfigured_pairing_authority_is_a_bounded_refusal():
    with pytest.raises(ControlPlaneContractError) as raised:
        _issue(pairing_authority=UnconfiguredBrokerPairingAuthority())
    assert raised.value.code == ENROLLMENT_REASON_DEPENDENCY_UNAVAILABLE
    assert "not configured" not in raised.value.safe_message


# --- S1-32 .. S1-45: CENTRAL security review follow-up -----------------------


def test_s1_32_a_different_consent_cannot_redeem_this_challenge():
    broker, pairing = _broker_and_pairing()
    _, receipt = _issue(pairing_authority=pairing, consent=_consent(consent_id=CONSENT_1))
    with pytest.raises(ControlPlaneContractError) as raised:
        _redeem(
            receipt,
            pairing_authority=pairing,
            consent=_consent(consent_id=CONSENT_2),
        )
    assert raised.value.code == ENROLLMENT_REASON_CONSENT_SWAP_DENIED
    assert _binding_count(broker) == 0
    # Nothing was consumed either: the original consent still redeems it.
    redeemed = _redeem(receipt, pairing_authority=pairing, consent=_consent(consent_id=CONSENT_1))
    assert redeemed.consent_id == CONSENT_1
    assert _binding_count(broker) == 1


def test_s1_33_a_withdrawn_consent_cannot_be_replaced_by_a_new_one():
    broker, pairing = _broker_and_pairing()
    _, old_receipt = _issue(
        pairing_authority=pairing,
        consent=_consent(consent_id=CONSENT_1),
    )
    # Consent A is withdrawn, and consent B is granted for the same computer.
    withdrawn = _consent(consent_id=CONSENT_1, withdrawn_at=NOW + timedelta(seconds=1))
    _, new_receipt = _issue(
        pairing_authority=pairing,
        consent=_consent(consent_id=CONSENT_2),
        now=NOW + timedelta(seconds=2),
    )
    assert new_receipt.consent_id == CONSENT_2

    with pytest.raises(ControlPlaneContractError) as swapped:
        _redeem(
            old_receipt,
            pairing_authority=pairing,
            consent=_consent(consent_id=CONSENT_2),
            now=NOW + timedelta(seconds=3),
        )
    assert swapped.value.code == ENROLLMENT_REASON_CONSENT_SWAP_DENIED

    with pytest.raises(ControlPlaneContractError) as withdrawn_consent:
        _redeem(
            old_receipt,
            pairing_authority=pairing,
            consent=withdrawn,
            now=NOW + timedelta(seconds=3),
        )
    assert withdrawn_consent.value.code == ENROLLMENT_REASON_CONSENT_WITHDRAWN
    assert _binding_count(broker) == 0

    # The new consent can only ever redeem its own challenge.
    redeemed = _redeem(
        new_receipt,
        pairing_authority=pairing,
        consent=_consent(consent_id=CONSENT_2),
        now=NOW + timedelta(seconds=4),
    )
    assert redeemed.consent_id == CONSENT_2
    assert _binding_count(broker) == 1


def test_s1_34_one_consent_cannot_enroll_a_second_computer():
    broker, pairing = _broker_and_pairing()
    with pytest.raises(ControlPlaneContractError) as at_issue:
        _issue(pairing_authority=pairing, consent=_consent(device_id=OFFICE_PC), device_id=LAPTOP)
    assert at_issue.value.code == ENROLLMENT_REASON_CONSENT_DEVICE_MISMATCH
    assert pairing.pending_challenge_count == 0

    _, receipt = _issue(pairing_authority=pairing, consent=_consent(device_id=OFFICE_PC))
    with pytest.raises(ControlPlaneContractError) as at_redeem:
        _redeem(
            receipt,
            pairing_authority=pairing,
            device_id=LAPTOP,
            proof_ref=_proof(receipt, device_id=LAPTOP),
        )
    assert at_redeem.value.code == ENROLLMENT_REASON_CONSENT_DEVICE_MISMATCH
    # A second, differently-identified consent for the other computer is a
    # consent swap against this challenge.
    with pytest.raises(ControlPlaneContractError) as swap:
        _redeem(
            receipt,
            pairing_authority=pairing,
            device_id=LAPTOP,
            consent=_consent(consent_id=CONSENT_2, device_id=LAPTOP),
        )
    assert swap.value.code == ENROLLMENT_REASON_CONSENT_SWAP_DENIED
    # The authority's own invariant also refuses a device swap outright.
    with pytest.raises(ControlPlaneContractError) as device_swap:
        pairing.redeem_enrollment(
            challenge_id=receipt.challenge.challenge_id,
            device_id=LAPTOP,
            proof_ref=_proof(receipt, device_id=LAPTOP),
            consent_ref=CONSENT_1,
            owner_ref=SUBJECT,
            account_ref=ACCOUNT_REF,
            workspace_ref=WORKSPACE_REF,
            now=NOW + timedelta(seconds=1),
        )
    assert device_swap.value.code == ENROLLMENT_REASON_DEVICE_SWAP_DENIED
    assert _binding_count(broker) == 0
    assert pairing.pending_challenge_count == 1


def test_s1_35_two_computers_each_need_their_own_consent():
    broker, pairing = _broker_and_pairing()
    _, office = _issue(
        pairing_authority=pairing,
        consent=_consent(consent_id=CONSENT_1, device_id=OFFICE_PC),
        device_id=OFFICE_PC,
    )
    laptop_consent = _consent(consent_id=CONSENT_2, device_id=LAPTOP)

    # Without its own consent the second computer is refused outright.
    with pytest.raises(ControlPlaneContractError) as no_own_consent:
        _issue(
            pairing_authority=pairing,
            consent=_consent(consent_id=CONSENT_1, device_id=OFFICE_PC),
            device_id=LAPTOP,
        )
    assert no_own_consent.value.code == ENROLLMENT_REASON_CONSENT_DEVICE_MISMATCH

    _, laptop = _issue(
        pairing_authority=pairing,
        consent=laptop_consent,
        device_id=LAPTOP,
        now=NOW + timedelta(seconds=1),
    )
    # And the second computer's challenge cannot ride on the first consent.
    with pytest.raises(ControlPlaneContractError) as swap:
        _redeem(
            laptop,
            pairing_authority=pairing,
            consent=_consent(consent_id=CONSENT_1, device_id=OFFICE_PC),
            device_id=LAPTOP,
            now=NOW + timedelta(seconds=2),
        )
    assert swap.value.code == ENROLLMENT_REASON_CONSENT_DEVICE_MISMATCH

    _redeem(office, pairing_authority=pairing, now=NOW + timedelta(seconds=2))
    _redeem(
        laptop,
        pairing_authority=pairing,
        consent=laptop_consent,
        now=NOW + timedelta(seconds=3),
    )
    assert {b.device_id for b in broker._bindings.values()} == {OFFICE_PC, LAPTOP}
    assert _binding_count(broker) == 2


def test_s1_36_a_fabricated_challenge_receipt_is_never_accepted_as_proof():
    broker, pairing = _broker_and_pairing()
    _, receipt = _issue(pairing_authority=pairing)

    # 1. A challenge id this authority never issued is refused.
    with pytest.raises(ControlPlaneContractError) as unknown:
        _redeem(
            receipt,
            pairing_authority=pairing,
            challenge_id="pairing." + "0" * 32,
        )
    assert unknown.value.code == "enrollment_challenge_not_found"

    # 2. A client-minted receipt object with the right shape carries no authority:
    #    the API accepts no receipt at all, so a forged one cannot even be passed.
    forged = {
        "challenge_id": receipt.challenge.challenge_id,
        "consent_id": CONSENT_1,
        "owner_subject_id": SUBJECT,
        "account_ref": ACCOUNT_REF,
        "workspace_ref": WORKSPACE_REF,
        "device_id": OFFICE_PC,
    }
    signature = inspect.signature(redeem_connector_enrollment)
    assert not any(
        "receipt" in name for name in signature.parameters
    ), "redemption must not accept a client-supplied receipt"
    assert set(signature.parameters) == {
        "auth_session",
        "allowed_product_ids",
        "scope_resolver",
        "consent",
        "pairing_authority",
        "challenge_id",
        "device_id",
        "proof_ref",
        "consent_liveness_reverified_by_existing_path",
        "now",
    }
    with pytest.raises(TypeError):
        redeem_connector_enrollment(receipt=forged)  # type: ignore[call-arg]

    # 3. A self-asserted proof for another device is still just a bad proof.
    with pytest.raises(ControlPlaneContractError) as forged_proof:
        _redeem(
            receipt,
            pairing_authority=pairing,
            proof_ref="pairing-proof:" + "a" * 64,
        )
    assert forged_proof.value.code == "enrollment_proof_invalid"
    assert _binding_count(broker) == 0
    assert pairing.pending_challenge_count == 1


def test_s1_37_the_binding_is_verified_before_any_mutation():
    broker, pairing = _broker_and_pairing()
    _, receipt = _issue(pairing_authority=pairing)
    pending_before = pairing.pending_challenge_count

    for bad in (
        {"consent": _consent(consent_id=CONSENT_2)},
        {"device_id": LAPTOP, "proof_ref": _proof(receipt, device_id=LAPTOP)},
    ):
        with pytest.raises(ControlPlaneContractError):
            _redeem(receipt, pairing_authority=pairing, **bad)
        # No Broker binding and no challenge consumption happened.
        assert _binding_count(broker) == 0
        assert pairing.pending_challenge_count == pending_before
        assert pairing.enrollment_binding(
            challenge_id=receipt.challenge.challenge_id,
            now=NOW + timedelta(seconds=1),
        ).consent_ref == CONSENT_1

    # The untouched challenge still redeems normally afterwards.
    redeemed = _redeem(receipt, pairing_authority=pairing, now=NOW + timedelta(seconds=5))
    assert redeemed.binding_ref
    assert _binding_count(broker) == 1
    assert ENROLLMENT_BINDING_VERIFIED_BEFORE_BROKER_MUTATION is True


def test_s1_38_consent_liveness_is_default_deny_until_its_authority_is_wired():
    broker, pairing = _broker_and_pairing()
    with pytest.raises(ControlPlaneContractError) as at_issue:
        _issue(
            pairing_authority=pairing,
            consent_liveness_reverified_by_existing_path=False,
        )
    assert at_issue.value.code == ENROLLMENT_REASON_CONSENT_LIVENESS_DEPENDENCY_UNMET
    assert pairing.pending_challenge_count == 0

    _, receipt = _issue(pairing_authority=pairing)
    with pytest.raises(ControlPlaneContractError) as at_redeem:
        _redeem(
            receipt,
            pairing_authority=pairing,
            consent_liveness_reverified_by_existing_path=False,
        )
    assert at_redeem.value.code == ENROLLMENT_REASON_CONSENT_LIVENESS_DEPENDENCY_UNMET
    assert _binding_count(broker) == 0

    dependencies = connector_enrollment_dependencies()
    assert dependencies["consent_liveness_authority_implemented"] is False
    assert dependencies["consent_liveness_default_deny"] is True
    assert dependencies["consent_liveness_reverified_is_an_input"] is True
    assert dependencies["self_asserted_consent_liveness_trusted"] is False
    boundary = connector_enrollment_boundary()
    assert boundary["consent_liveness_default_deny"] is True
    assert boundary["server_bound_challenge_required"] is True
    assert boundary["challenge_receipt_is_not_authority"] is True
    assert boundary["unsigned_challenge_receipt_trusted"] is False
    assert boundary["enrollment_binding_verified_before_broker_mutation"] is True
    assert boundary["consent_bound_to_device"] is True
    assert boundary["one_consent_per_device"] is True
    assert boundary["unlimited_pcs_per_enrollment_consent"] is False


def test_s1_39_the_binding_lives_in_the_canonical_authority_not_in_a_receipt():
    broker, pairing = _broker_and_pairing()
    _, receipt = _issue(pairing_authority=pairing)
    rendered = repr(receipt.safe_dict())
    assert receipt.pairing_code not in rendered
    assert "consent_ref" not in receipt.safe_dict()
    # The authority holds the trusted record; its own projection is secret-free.
    authority_projection = pairing.safe_dict()
    assert authority_projection["enrollment_consent_binding_supported"] is True
    assert authority_projection["client_supplied_enrollment_receipt_trusted"] is False
    assert authority_projection["second_enrollment_store"] is False
    assert authority_projection["enrollment_binding_verified_before_mutation"] is True
    for issued in (receipt.pairing_code,):
        assert issued not in repr(authority_projection)
    stored = pairing.enrollment_binding(challenge_id=receipt.challenge.challenge_id, now=NOW)
    assert "consent_ref" in stored.safe_dict()
    assert stored.safe_dict()["server_owned_binding"] is True
    # A plain pairing challenge taken straight from the authority is not a
    # client-facing receipt either: it carries no consent binding at all.
    _, plain_code = pairing.issue_challenge(
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        now=NOW,
        ttl_seconds=300,
    )
    assert re.fullmatch(rf"[0-9a-f]{{{PAIRING_CODE_HEX_CHARS}}}", plain_code)
    assert _binding_count(broker) == 0


def test_s1_40_a_challenge_without_an_enrollment_binding_cannot_be_redeemed_as_one():
    broker, pairing = _broker_and_pairing()
    challenge, code = pairing.issue_challenge(
        account_ref=ACCOUNT_REF,
        workspace_ref=WORKSPACE_REF,
        now=NOW,
        ttl_seconds=300,
    )
    proof = pairing_proof_ref(
        challenge_id=challenge.challenge_id,
        device_id=OFFICE_PC,
        pairing_code=code,
    )
    with pytest.raises(ControlPlaneContractError) as raised:
        redeem_connector_enrollment(
            auth_session=_session(),
            allowed_product_ids=REVIEWED_PRODUCTS,
            scope_resolver=_resolver(),
            consent=_consent(),
            pairing_authority=pairing,
            challenge_id=challenge.challenge_id,
            device_id=OFFICE_PC,
            proof_ref=proof,
            consent_liveness_reverified_by_existing_path=True,
            now=NOW + timedelta(seconds=1),
        )
    assert raised.value.code == ENROLLMENT_REASON_BINDING_ABSENT
    assert _binding_count(broker) == 0
    assert pairing.pending_challenge_count == 1


def test_s1_41_another_owner_cannot_redeem_this_challenge():
    broker, pairing = _broker_and_pairing()
    _, receipt = _issue(pairing_authority=pairing)
    with pytest.raises(ControlPlaneContractError) as raised:
        _redeem(
            receipt,
            pairing_authority=pairing,
            auth_session=_session(subject_id=OTHER_SUBJECT, session_id="session_connector_2"),
            scope_resolver=_resolver(
                _scope(owner_subject_id=OTHER_SUBJECT, account_ref=OTHER_ACCOUNT_REF)
            ),
            consent=_consent(
                consent_id=CONSENT_2,
                owner_subject_id=OTHER_SUBJECT,
                account_ref=OTHER_ACCOUNT_REF,
                device_id=OFFICE_PC,
            ),
        )
    assert raised.value.code == ENROLLMENT_REASON_CONSENT_SWAP_DENIED
    assert _binding_count(broker) == 0


def test_s1_42_another_workspace_scope_cannot_redeem_this_challenge():
    broker, pairing = _broker_and_pairing()
    _, receipt = _issue(pairing_authority=pairing)
    other_scope = _scope(workspace_ref=OTHER_WORKSPACE_REF)
    with pytest.raises(ControlPlaneContractError) as raised:
        _redeem(
            receipt,
            pairing_authority=pairing,
            scope_resolver=_resolver(other_scope),
            consent=_consent(
                consent_id=CONSENT_2,
                workspace_ref=OTHER_WORKSPACE_REF,
                device_id=OFFICE_PC,
            ),
        )
    assert raised.value.code in {
        ENROLLMENT_REASON_CONSENT_SWAP_DENIED,
        ENROLLMENT_REASON_BINDING_SCOPE_MISMATCH,
    }
    assert _binding_count(broker) == 0
    # With the same consent but a foreign workspace the binding scope decides.
    with pytest.raises(ControlPlaneContractError) as scope_raised:
        _redeem(
            receipt,
            pairing_authority=pairing,
            scope_resolver=_resolver(other_scope),
            consent=_consent(device_id=OFFICE_PC),
        )
    assert scope_raised.value.code == ENROLLMENT_REASON_CONSENT_SCOPE_MISMATCH
    assert _binding_count(broker) == 0


def test_s1_43_the_follow_up_stays_parity_checked_with_the_canonical_sources():
    package_root = Path(enrollment_module.__file__).parent
    pairing_source = (package_root / "local_agent_broker_pairing.py").read_text(encoding="utf-8")
    for name in (
        "ENROLLMENT_CONSENT_BINDING_SUPPORTED",
        "ENROLLMENT_BINDING_REQUIRES_EXACT_CONSENT",
        "ENROLLMENT_BINDING_REQUIRES_EXACT_DEVICE",
        "ENROLLMENT_BINDING_REQUIRES_EXACT_OWNER_SCOPE",
        "ENROLLMENT_BINDING_VERIFIED_BEFORE_MUTATION",
        "CLIENT_SUPPLIED_ENROLLMENT_RECEIPT_TRUSTED",
        "SECOND_ENROLLMENT_STORE",
    ):
        assert f"{name} = " in pairing_source, name
    for member in (
        "issue_enrollment_challenge",
        "enrollment_binding",
        "redeem_enrollment",
        "BrokerPairingEnrollmentBinding",
    ):
        assert member in pairing_source, member
    assert SERVER_BOUND_CHALLENGE_REQUIRED is True
    assert UNSIGNED_CHALLENGE_RECEIPT_TRUSTED is False
    assert CONSENT_BOUND_TO_DEVICE is True
    assert ONE_CONSENT_PER_DEVICE is True
    assert enrollment_refusal_reason("enrollment_consent_swap_denied") == (
        ENROLLMENT_REASON_CONSENT_SWAP_DENIED
    )
    assert enrollment_refusal_reason("enrollment_device_swap_denied") == (
        ENROLLMENT_REASON_DEVICE_SWAP_DENIED
    )
    assert enrollment_refusal_reason("enrollment_binding_absent") == (
        ENROLLMENT_REASON_BINDING_ABSENT
    )
    assert enrollment_refusal_reason("enrollment_binding_owner_mismatch") == (
        ENROLLMENT_REASON_BINDING_OWNER_MISMATCH
    )
    assert enrollment_refusal_reason("enrollment_binding_scope_mismatch") == (
        ENROLLMENT_REASON_BINDING_SCOPE_MISMATCH
    )


def test_s1_44_the_follow_up_introduces_no_new_authority_or_store():
    dependencies = connector_enrollment_dependencies()
    assert dependencies["second_enrollment_store"] is False
    assert dependencies["challenge_consent_binding"].startswith("canonical pairing authority")
    assert dependencies["challenge_binding_durability"] == (
        "same as the canonical pairing challenge; no second store"
    )
    assert dependencies["signed_enrollment_receipt"].startswith("not implemented")
    boundary = connector_enrollment_boundary()
    assert boundary["production_activation"] is False
    assert boundary["production_ready"] is False
    assert boundary["dispatch_authorized_by_this_contract"] is False
    pairing = InMemoryBrokerPairingAuthority(
        pepper=PAIRING_PEPPER,
        authority=InMemoryLocalAgentBrokerAuthority(
            pepper=BROKER_PEPPER,
            authority_ref=AUTHORITY_REF,
        ),
    )
    # The follow-up adds no second store to the canonical authority either.
    assert pairing.safe_dict()["second_enrollment_store"] is False
    assert not hasattr(pairing, "_enrollment_store")
    assert not hasattr(pairing, "_consent_store")


def test_s1_45_no_projection_carries_the_code_or_the_credential():
    _, pairing = _broker_and_pairing()
    _, receipt = _issue(pairing_authority=pairing)
    redeemed = _redeem(receipt, pairing_authority=pairing)
    for projection in (
        receipt.safe_dict(),
        redeemed.safe_dict(),
        redeemed.enrollment.safe_dict(),
        redeemed.binding.safe_dict(),
        pairing.safe_dict(),
        connector_enrollment_dependencies(),
        connector_enrollment_boundary(),
    ):
        rendered = repr(projection)
        assert receipt.pairing_code not in rendered
        assert redeemed.credential.hex() not in rendered
    denied = enrollment_refusal_reason("enrollment_consent_swap_denied")
    assert denied == ENROLLMENT_REASON_CONSENT_SWAP_DENIED
