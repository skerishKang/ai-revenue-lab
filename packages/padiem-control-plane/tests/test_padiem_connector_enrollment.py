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
    InMemoryBrokerPairingAuthority,
    UnconfiguredBrokerPairingAuthority,
    pairing_proof_ref,
)
from padiem_control_plane.local_agent_pc_access import PRODUCT_PC_ACCESS_DEFAULT
from padiem_control_plane.padiem_connector_enrollment import (
    CONNECTOR_ENROLLMENT_CONTRACT_VERSION,
    DEVICE_LIFECYCLE_AUTHORITY,
    ENROLLMENT_CODE_HEX_CHARS,
    ENROLLMENT_REFUSAL_BY_CANONICAL_CODE,
    ENROLLMENT_REFUSAL_FALLBACK,
    ENROLLMENT_REASON_CONSENT_REQUIRED,
    ENROLLMENT_REASON_CONSENT_SCOPE_MISMATCH,
    ENROLLMENT_REASON_CONSENT_WITHDRAWN,
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
    UNSUPPORTED_AUTH_METHODS,
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
WORKSPACE_REF = "workspace_connector_1"
OFFICE_PC = "device.office-pc"
LAPTOP = "device.laptop-pc"


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
    owner_subject_id: str = SUBJECT,
    account_ref: str = ACCOUNT_REF,
    workspace_ref: str = WORKSPACE_REF,
    granted_at: datetime = NOW - timedelta(minutes=1),
    withdrawn_at: datetime | None = None,
) -> ConnectorEnrollmentConsent:
    return ConnectorEnrollmentConsent(
        consent_id="consent_connector_1",
        owner_subject_id=owner_subject_id,
        account_ref=account_ref,
        workspace_ref=workspace_ref,
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


def _issue(**overrides):
    """Issue a challenge with sane defaults; returns ``(pairing, receipt)``."""

    pairing = overrides.pop("pairing_authority", None)
    if pairing is None:
        _, pairing = _broker_and_pairing()
    kwargs = dict(
        auth_session=_session(),
        allowed_product_ids=REVIEWED_PRODUCTS,
        scope_resolver=_resolver(),
        consent=_consent(),
        pairing_authority=pairing,
        now=NOW,
    )
    kwargs.update(overrides)
    return pairing, issue_connector_enrollment_challenge(**kwargs)


# --- S1-01 .. S1-09: identity -> scope ---------------------------------------


def test_s1_01_verified_canonical_session_and_consent_are_eligible():
    decision = _evaluate()
    assert decision.eligible is True
    assert decision.reason == ENROLLMENT_REASON_ELIGIBLE
    assert decision.scope == _scope()
    assert decision.consent_id == "consent_connector_1"
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
    revoked = _evaluate(
        auth_session=_session(state=AuthSessionState.REVOKED),
    )
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
    empty = _evaluate(allowed_product_ids=frozenset())
    assert empty.reason == ENROLLMENT_REASON_PRODUCT_NOT_REVIEWED
    malformed = _evaluate(allowed_product_ids={"b54-padiem-claw"})
    assert malformed.reason == ENROLLMENT_REASON_PRODUCT_NOT_REVIEWED
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
    raising = _evaluate(scope_resolver=_resolver(RuntimeError("resolver down")))
    assert raising.reason == ENROLLMENT_REASON_SCOPE_UNAVAILABLE
    malformed = _evaluate(scope_resolver=_resolver("account_connector_1"))
    assert malformed.reason == ENROLLMENT_REASON_SCOPE_UNVERIFIED


def test_s1_09_a_product_scoped_scope_is_refused():
    # A per-product scope cannot even be constructed.
    with pytest.raises(ControlPlaneContractError) as raised:
        _scope(product_scoped=True)
    assert raised.value.code == ENROLLMENT_REASON_PRODUCT_SCOPED_SCOPE
    # And a resolver that reports one is refused rather than honoured.
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
    other_user = _consent(owner_subject_id=OTHER_SUBJECT)
    assert _evaluate(consent=other_user).reason == ENROLLMENT_REASON_CONSENT_SCOPE_MISMATCH
    other_workspace = _consent(workspace_ref="workspace_connector_2")
    assert _evaluate(consent=other_workspace).reason == ENROLLMENT_REASON_CONSENT_SCOPE_MISMATCH
    other_account = _consent(account_ref="account_connector_2")
    assert _evaluate(consent=other_account).reason == ENROLLMENT_REASON_CONSENT_SCOPE_MISMATCH


# --- S1-13 .. S1-14: challenge issuance --------------------------------------


def test_s1_13_the_challenge_is_scoped_to_the_server_derived_scope():
    resolver = _resolver()
    pairing, receipt = _issue(scope_resolver=resolver)
    assert receipt.challenge.account_ref == ACCOUNT_REF
    assert receipt.challenge.workspace_ref == WORKSPACE_REF
    assert receipt.challenge.issued_at == NOW
    assert receipt.challenge.expires_at > NOW
    assert receipt.scope == _scope()
    assert receipt.consent_id == "consent_connector_1"
    assert re.fullmatch(rf"[0-9a-f]{{{PAIRING_CODE_HEX_CHARS}}}", receipt.pairing_code)
    assert pairing.pending_challenge_count == 1
    assert resolver.calls == [{"subject_id": SUBJECT, "tenant_ref": TENANT, "now": NOW}]


def test_s1_14_an_ineligible_account_cannot_mint_a_challenge():
    _, pairing = _broker_and_pairing()
    with pytest.raises(ControlPlaneContractError) as raised:
        _issue(pairing_authority=pairing, auth_session=_session(state=AuthSessionState.REVOKED))
    assert raised.value.code == ENROLLMENT_REASON_SESSION_INACTIVE
    with pytest.raises(ControlPlaneContractError) as no_consent:
        _issue(pairing_authority=pairing, consent=None)
    assert no_consent.value.code == ENROLLMENT_REASON_CONSENT_REQUIRED
    assert pairing.pending_challenge_count == 0
    # The refused call never echoes canonical text.
    assert "revoke" not in str(raised.value.safe_message).lower()


# --- S1-15 .. S1-19: the registered PC ---------------------------------------


def test_s1_15_issue_then_redeem_registers_the_pc_in_the_canonical_broker():
    broker, pairing = _broker_and_pairing()
    receipt = issue_connector_enrollment_challenge(
        auth_session=_session(),
        allowed_product_ids=REVIEWED_PRODUCTS,
        scope_resolver=_resolver(),
        consent=_consent(),
        pairing_authority=pairing,
        now=NOW,
    )
    proof = pairing_proof_ref(
        challenge_id=receipt.challenge.challenge_id,
        device_id=OFFICE_PC,
        pairing_code=receipt.pairing_code,
    )
    redeemed = redeem_connector_enrollment(
        auth_session=_session(),
        allowed_product_ids=REVIEWED_PRODUCTS,
        scope_resolver=_resolver(),
        consent=_consent(),
        pairing_authority=pairing,
        challenge_id=receipt.challenge.challenge_id,
        device_id=OFFICE_PC,
        proof_ref=proof,
        now=NOW + timedelta(seconds=1),
    )
    assert redeemed.device_id == OFFICE_PC
    assert redeemed.credential_generation == 1
    assert redeemed.scope == _scope()

    # The credential the Connector received authenticates against the canonical
    # Broker binding authority — the PC really is registered there.
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


def test_s1_16_a_wrong_ownership_proof_is_refused_without_echoing_upstream_text():
    _, pairing = _broker_and_pairing()
    receipt = issue_connector_enrollment_challenge(
        auth_session=_session(),
        allowed_product_ids=REVIEWED_PRODUCTS,
        scope_resolver=_resolver(),
        consent=_consent(),
        pairing_authority=pairing,
        now=NOW,
    )
    forged = "pairing-proof:" + "0" * 64
    with pytest.raises(ControlPlaneContractError) as raised:
        redeem_connector_enrollment(
            auth_session=_session(),
            allowed_product_ids=REVIEWED_PRODUCTS,
            scope_resolver=_resolver(),
            consent=_consent(),
            pairing_authority=pairing,
            challenge_id=receipt.challenge.challenge_id,
            device_id=OFFICE_PC,
            proof_ref=forged,
            now=NOW + timedelta(seconds=1),
        )
    assert raised.value.code == "enrollment_proof_invalid"
    assert "proof is invalid" not in raised.value.safe_message
    with pytest.raises(ControlPlaneContractError) as bad_ref:
        redeem_connector_enrollment(
            auth_session=_session(),
            allowed_product_ids=REVIEWED_PRODUCTS,
            scope_resolver=_resolver(),
            consent=_consent(),
            pairing_authority=pairing,
            challenge_id=receipt.challenge.challenge_id,
            device_id=OFFICE_PC,
            proof_ref="not-a-proof",
            now=NOW + timedelta(seconds=1),
        )
    assert bad_ref.value.code == "enrollment_proof_invalid"


def test_s1_17_a_challenge_is_single_use():
    _, pairing = _broker_and_pairing()
    receipt = issue_connector_enrollment_challenge(
        auth_session=_session(),
        allowed_product_ids=REVIEWED_PRODUCTS,
        scope_resolver=_resolver(),
        consent=_consent(),
        pairing_authority=pairing,
        now=NOW,
    )
    proof = pairing_proof_ref(
        challenge_id=receipt.challenge.challenge_id,
        device_id=OFFICE_PC,
        pairing_code=receipt.pairing_code,
    )
    args = dict(
        auth_session=_session(),
        allowed_product_ids=REVIEWED_PRODUCTS,
        scope_resolver=_resolver(),
        consent=_consent(),
        pairing_authority=pairing,
        challenge_id=receipt.challenge.challenge_id,
        device_id=OFFICE_PC,
        proof_ref=proof,
    )
    redeem_connector_enrollment(**args, now=NOW + timedelta(seconds=1))
    with pytest.raises(ControlPlaneContractError) as raised:
        redeem_connector_enrollment(**args, now=NOW + timedelta(seconds=2))
    assert raised.value.code == "enrollment_duplicate_redeem_denied"


def test_s1_18_a_second_product_cannot_enroll_the_same_pc():
    broker, pairing = _broker_and_pairing()

    def enroll(product_id: str):
        receipt = issue_connector_enrollment_challenge(
            auth_session=_session(product_id=product_id),
            allowed_product_ids=REVIEWED_PRODUCTS,
            scope_resolver=_resolver(),
            consent=_consent(),
            pairing_authority=pairing,
            now=NOW,
        )
        proof = pairing_proof_ref(
            challenge_id=receipt.challenge.challenge_id,
            device_id=OFFICE_PC,
            pairing_code=receipt.pairing_code,
        )
        return redeem_connector_enrollment(
            auth_session=_session(product_id=product_id),
            allowed_product_ids=REVIEWED_PRODUCTS,
            scope_resolver=_resolver(),
            consent=_consent(),
            pairing_authority=pairing,
            challenge_id=receipt.challenge.challenge_id,
            device_id=OFFICE_PC,
            proof_ref=proof,
            now=NOW + timedelta(seconds=1),
        )

    first = enroll(CLAW)
    # Exactly one binding exists for this physical PC, and it is the same device
    # id every product resolves — never a per-product registration.
    with pytest.raises(ControlPlaneContractError) as raised:
        enroll(CHAT)
    assert raised.value.code == "enrollment_duplicate_device_denied"
    bindings = [b for b in broker._bindings.values() if b.device_id == OFFICE_PC]
    assert len(bindings) == 1
    assert bindings[0].binding_ref == first.binding_ref


def test_s1_19_the_same_owner_may_enroll_a_genuinely_different_pc():
    broker, pairing = _broker_and_pairing()
    bindings = []
    for device_id in (OFFICE_PC, LAPTOP):
        receipt = issue_connector_enrollment_challenge(
            auth_session=_session(),
            allowed_product_ids=REVIEWED_PRODUCTS,
            scope_resolver=_resolver(),
            consent=_consent(),
            pairing_authority=pairing,
            now=NOW,
        )
        proof = pairing_proof_ref(
            challenge_id=receipt.challenge.challenge_id,
            device_id=device_id,
            pairing_code=receipt.pairing_code,
        )
        redeemed = redeem_connector_enrollment(
            auth_session=_session(),
            allowed_product_ids=REVIEWED_PRODUCTS,
            scope_resolver=_resolver(),
            consent=_consent(),
            pairing_authority=pairing,
            challenge_id=receipt.challenge.challenge_id,
            device_id=device_id,
            proof_ref=proof,
            now=NOW + timedelta(seconds=1),
        )
        bindings.append(redeemed.binding_ref)
    assert len(set(bindings)) == 2
    assert {b.device_id for b in broker._bindings.values()} == {OFFICE_PC, LAPTOP}


# --- S1-20 .. S1-23: account change, redemption, receipt ---------------------


def test_s1_20_a_session_revoked_between_issue_and_redeem_refuses_redemption():
    _, pairing = _broker_and_pairing()
    receipt = issue_connector_enrollment_challenge(
        auth_session=_session(),
        allowed_product_ids=REVIEWED_PRODUCTS,
        scope_resolver=_resolver(),
        consent=_consent(),
        pairing_authority=pairing,
        now=NOW,
    )
    proof = pairing_proof_ref(
        challenge_id=receipt.challenge.challenge_id,
        device_id=OFFICE_PC,
        pairing_code=receipt.pairing_code,
    )
    with pytest.raises(ControlPlaneContractError) as raised:
        redeem_connector_enrollment(
            auth_session=_session(state=AuthSessionState.REVOKED),
            allowed_product_ids=REVIEWED_PRODUCTS,
            scope_resolver=_resolver(),
            consent=_consent(),
            pairing_authority=pairing,
            challenge_id=receipt.challenge.challenge_id,
            device_id=OFFICE_PC,
            proof_ref=proof,
            now=NOW + timedelta(seconds=1),
        )
    assert raised.value.code == ENROLLMENT_REASON_SESSION_INACTIVE
    # ... and a different account cannot redeem it either.
    other_scope = _scope(owner_subject_id=OTHER_SUBJECT, account_ref="account_connector_2")
    with pytest.raises(ControlPlaneContractError) as other_account:
        redeem_connector_enrollment(
            auth_session=_session(subject_id=OTHER_SUBJECT, session_id="session_connector_2"),
            allowed_product_ids=REVIEWED_PRODUCTS,
            scope_resolver=_resolver(other_scope),
            consent=_consent(owner_subject_id=OTHER_SUBJECT, account_ref="account_connector_2"),
            pairing_authority=pairing,
            challenge_id=receipt.challenge.challenge_id,
            device_id=OFFICE_PC,
            proof_ref=proof,
            now=NOW + timedelta(seconds=1),
        )
    assert other_account.value.code == ENROLLMENT_REASON_SCOPE_OWNER_MISMATCH
    assert pairing.pending_challenge_count == 1


def test_s1_21_a_consent_withdrawn_between_issue_and_redeem_refuses_redemption():
    _, pairing = _broker_and_pairing()
    receipt = issue_connector_enrollment_challenge(
        auth_session=_session(),
        allowed_product_ids=REVIEWED_PRODUCTS,
        scope_resolver=_resolver(),
        consent=_consent(),
        pairing_authority=pairing,
        now=NOW,
    )
    proof = pairing_proof_ref(
        challenge_id=receipt.challenge.challenge_id,
        device_id=OFFICE_PC,
        pairing_code=receipt.pairing_code,
    )
    with pytest.raises(ControlPlaneContractError) as raised:
        redeem_connector_enrollment(
            auth_session=_session(),
            allowed_product_ids=REVIEWED_PRODUCTS,
            scope_resolver=_resolver(),
            consent=_consent(withdrawn_at=NOW + timedelta(seconds=0, microseconds=1)),
            pairing_authority=pairing,
            challenge_id=receipt.challenge.challenge_id,
            device_id=OFFICE_PC,
            proof_ref=proof,
            now=NOW + timedelta(seconds=1),
        )
    assert raised.value.code == ENROLLMENT_REASON_CONSENT_WITHDRAWN


def test_s1_22_redeeming_another_accounts_challenge_cannot_bind_this_account():
    broker, pairing = _broker_and_pairing()
    issued_for_owner = issue_connector_enrollment_challenge(
        auth_session=_session(),
        allowed_product_ids=REVIEWED_PRODUCTS,
        scope_resolver=_resolver(),
        consent=_consent(),
        pairing_authority=pairing,
        now=NOW,
    )
    proof = pairing_proof_ref(
        challenge_id=issued_for_owner.challenge.challenge_id,
        device_id=OFFICE_PC,
        pairing_code=issued_for_owner.pairing_code,
    )
    with pytest.raises(ControlPlaneContractError) as raised:
        redeem_connector_enrollment(
            auth_session=_session(subject_id=OTHER_SUBJECT, session_id="session_connector_2"),
            allowed_product_ids=REVIEWED_PRODUCTS,
            scope_resolver=_resolver(
                _scope(owner_subject_id=OTHER_SUBJECT, account_ref="account_connector_2")
            ),
            consent=_consent(owner_subject_id=OTHER_SUBJECT, account_ref="account_connector_2"),
            pairing_authority=pairing,
            challenge_id=issued_for_owner.challenge.challenge_id,
            device_id=OFFICE_PC,
            proof_ref=proof,
            now=NOW + timedelta(seconds=1),
        )
    assert raised.value.code == ENROLLMENT_REASON_SCOPE_OWNER_MISMATCH
    # Whatever the canonical authority created stays owned by the scope it was
    # issued for: this account's identity is never bound to it.
    for binding in broker._bindings.values():
        assert binding.account_ref == ACCOUNT_REF
        assert binding.account_ref != "account_connector_2"


def test_s1_23_the_receipt_returns_the_credential_once_and_never_in_safe_dict():
    _, pairing = _broker_and_pairing()
    receipt = issue_connector_enrollment_challenge(
        auth_session=_session(),
        allowed_product_ids=REVIEWED_PRODUCTS,
        scope_resolver=_resolver(),
        consent=_consent(),
        pairing_authority=pairing,
        now=NOW,
    )
    proof = pairing_proof_ref(
        challenge_id=receipt.challenge.challenge_id,
        device_id=OFFICE_PC,
        pairing_code=receipt.pairing_code,
    )
    redeemed = redeem_connector_enrollment(
        auth_session=_session(),
        allowed_product_ids=REVIEWED_PRODUCTS,
        scope_resolver=_resolver(),
        consent=_consent(),
        pairing_authority=pairing,
        challenge_id=receipt.challenge.challenge_id,
        device_id=OFFICE_PC,
        proof_ref=proof,
        now=NOW + timedelta(seconds=1),
    )
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
    # The one-time code is likewise never part of the challenge projection.
    challenge_projection = receipt.safe_dict()
    assert challenge_projection["pairing_code"] is None
    assert receipt.pairing_code not in repr(challenge_projection)


# --- S1-24 .. S1-28: no new authority, no dispatch, posture ------------------


def test_s1_24_enrollment_mints_no_execution_approval_and_never_authorizes_dispatch():
    decision = _evaluate()
    projection = decision.safe_dict()
    assert projection["dispatch_authorized"] is False
    assert projection["execution_approval_minted"] is False
    assert projection["execution_approval_owner"] == EXECUTION_APPROVAL_OWNER
    assert projection["creates_login"] is False
    assert projection["creates_device_registry"] is False
    # ``dispatch_authorized`` is a read-only property on a frozen slots dataclass,
    # so a True authorization can never be assigned onto the decision.
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
    # The canonical authorities are imported, not re-implemented.
    assert "from .auth_sessions import" in source
    assert "from .local_agent_broker_pairing import" in source
    assert "from .local_agent_pc_access import" in source


def test_s1_26_the_refusal_mapping_matches_the_canonical_sources():
    module_file = enrollment_module.__file__
    assert module_file is not None
    package_root = Path(module_file).parent
    pairing_source = (package_root / "local_agent_broker_pairing.py").read_text(encoding="utf-8")
    broker_source = (package_root / "local_agent_broker.py").read_text(encoding="utf-8")
    for canonical_code in ENROLLMENT_REFUSAL_BY_CANONICAL_CODE:
        assert f'"{canonical_code}"' in pairing_source or f'"{canonical_code}"' in broker_source, (
            canonical_code
        )
    assert ENROLLMENT_REFUSAL_FALLBACK not in ENROLLMENT_REFUSAL_BY_CANONICAL_CODE.values()
    assert enrollment_refusal_reason("pairing_challenge_expired") == "enrollment_challenge_expired"
    assert enrollment_refusal_reason("something_unknown") == ENROLLMENT_REFUSAL_FALLBACK
    assert enrollment_refusal_reason(None) == ENROLLMENT_REFUSAL_FALLBACK
    # Grammar/vocabulary parity with the canonical pairing authority.
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
    # No password/OAuth verification, token minting or client-secret handling.
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


# --- S1-29 .. S1-30: bounded rate + verified-only resolver inputs ------------


def test_s1_29_the_canonical_issuance_bound_surfaces_as_a_bounded_reason():
    _, pairing = _broker_and_pairing(issuance_rate_limit=1)
    issue_connector_enrollment_challenge(
        auth_session=_session(),
        allowed_product_ids=REVIEWED_PRODUCTS,
        scope_resolver=_resolver(),
        consent=_consent(),
        pairing_authority=pairing,
        now=NOW,
    )
    with pytest.raises(ControlPlaneContractError) as raised:
        issue_connector_enrollment_challenge(
            auth_session=_session(),
            allowed_product_ids=REVIEWED_PRODUCTS,
            scope_resolver=_resolver(),
            consent=_consent(),
            pairing_authority=pairing,
            now=NOW + timedelta(seconds=1),
        )
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
    # No session id, no product id, no device id and no credential is ever the
    # resolver's input: the Connector cannot name any of them.
    source = inspect.getsource(enrollment_module.evaluate_connector_enrollment)
    assert "device_id" not in source
    assert "session_id" not in source
    # A resolver that mutates nothing is fine; a scope for another owner is not.
    assert _evaluate(scope_resolver=resolver).scope == _scope()


def test_s1_31_an_unconfigured_pairing_authority_is_a_bounded_refusal():
    with pytest.raises(ControlPlaneContractError) as raised:
        issue_connector_enrollment_challenge(
            auth_session=_session(),
            allowed_product_ids=REVIEWED_PRODUCTS,
            scope_resolver=_resolver(),
            consent=_consent(),
            pairing_authority=UnconfiguredBrokerPairingAuthority(),
            now=NOW,
        )
    assert raised.value.code == ENROLLMENT_REASON_DEPENDENCY_UNAVAILABLE
    assert "not configured" not in raised.value.safe_message
