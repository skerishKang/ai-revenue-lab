"""#4643: explicit CP voice policy is inert by default and tenant-locked."""
from datetime import UTC, datetime, timedelta
from dataclasses import replace

import pytest

from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, ControlPlaneContractError, SubjectType
from padiem_control_plane.engine_entitlement_producer import (
    produce_authenticated_user_engine_entitlement,
)
from padiem_control_plane.voice_stt_entitlement_policy import (
    VoiceSttPolicy,
    VoiceSttTenantScope,
    voice_stt_grants_for_session,
)

NOW = datetime(2026, 10, 14, 1, 0, tzinfo=UTC)


def session(*, product="b62", tenant="tenant_alpha", subject_type=SubjectType.USER,
            state=AuthSessionState.ACTIVE):
    return AuthSessionSnapshot(
        session_id="sess_test",
        product_id=product,
        subject=CanonicalSubjectRef(subject_type=subject_type, subject_id="subject_alpha"),
        issued_at=NOW - timedelta(hours=2),
        expires_at=NOW + timedelta(hours=1),
        tenant_id=tenant,
        state=state,
    )


def policy(*, units=(("voice.stt.transcribe", 20), ("voice.stt.live_token", 1)),
           scope_product="b62", scope_tenant="tenant_alpha"):
    return VoiceSttPolicy(
        revision="approved_test_only_v1",
        effective_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
        scopes=(VoiceSttTenantScope(scope_product, scope_tenant, units),),
    )


def test_no_policy_preserves_frozen_orchestration_snapshot_byte_for_byte():
    actor = session()
    default = produce_authenticated_user_engine_entitlement(actor, now=NOW)
    explicit_none = produce_authenticated_user_engine_entitlement(actor, now=NOW, voice_policy=None)
    assert default.to_policy_dict() == explicit_none.to_policy_dict()
    assert [x.key for x in default.grants] == ["orchestration.run"]
    assert default.resolve("voice.stt.transcribe") is None
    assert default.resolve("voice.stt.live_token") is None


def test_only_explicit_tenant_and_product_grants_and_bound_limits():
    actor = session()
    grants = voice_stt_grants_for_session(actor, policy=policy(), now=NOW)
    assert [(x.key, x.allowed, x.limit) for x in grants] == [
        ("voice.stt.transcribe", True, 20),
        ("voice.stt.live_token", True, 1),
    ]
    snap = produce_authenticated_user_engine_entitlement(actor, now=NOW, voice_policy=policy())
    assert snap.resolve("orchestration.run").allowed
    assert snap.resolve("voice.stt.transcribe").limit == 20
    assert snap.resolve("voice.stt.live_token").limit == 1
    assert snap.issued_at == NOW - timedelta(hours=1)


@pytest.mark.parametrize("actor", [
    session(tenant=None),
    session(tenant="tenant_beta"),
    session(product="b54-padiem-claw"),
    session(subject_type=SubjectType.ACCOUNT),
    session(state=AuthSessionState.REVOKED),
])
def test_wrong_identity_or_inactive_session_cannot_inherit_voice(actor):
    assert voice_stt_grants_for_session(actor, policy=policy(), now=NOW) == ()


def test_product_scoping_requires_explicit_second_scope():
    actor = session(product="b54-padiem-claw")
    assert voice_stt_grants_for_session(actor, policy=policy(), now=NOW) == ()
    granted = policy(scope_product="b54-padiem-claw")
    snap = produce_authenticated_user_engine_entitlement(actor, now=NOW, voice_policy=granted)
    assert snap.resolve("voice.stt.transcribe").limit == 20


def test_time_bounded_policy_denies_before_and_after_window():
    pol = policy()
    actor = session()
    assert voice_stt_grants_for_session(actor, policy=pol, now=NOW-timedelta(hours=3)) == ()
    assert voice_stt_grants_for_session(actor, policy=pol, now=NOW+timedelta(hours=1)) == ()


@pytest.mark.parametrize("units", [
    (("voice.stt.transcribe", True),),
    (("voice.stt.transcribe", 0),),
    (("voice.stt.transcribe", -1),),
    (("voice.stt.transcribe", 1_000_001),),
    (("orchestration.run", 1),),
    (("voice.stt.live_token", 1), ("voice.stt.live_token", 2)),
    (),
])
def test_bad_or_unbounded_grants_are_rejected(units):
    with pytest.raises(ControlPlaneContractError) as err:
        policy(units=units)
    assert err.value.code == "invalid_voice_stt_policy"


def test_conflicting_scopes_and_bad_policy_types_are_rejected():
    scope = VoiceSttTenantScope("b62", "tenant_alpha", (("voice.stt.transcribe", 2),))
    with pytest.raises(ControlPlaneContractError):
        replace(policy(), scopes=(scope, scope))
    with pytest.raises(ControlPlaneContractError):
        replace(policy(), effective_at=NOW.replace(tzinfo=None))
    with pytest.raises(ControlPlaneContractError):
        replace(policy(), scopes=())


def test_a_changed_explicit_policy_changes_snapshot_fingerprint_and_expiry():
    actor = session()
    first = produce_authenticated_user_engine_entitlement(actor, now=NOW, voice_policy=policy())
    updated = policy(units=(("voice.stt.transcribe", 19),))
    second = produce_authenticated_user_engine_entitlement(actor, now=NOW, voice_policy=updated)
    assert first.snapshot_id != second.snapshot_id
    assert first.revision != second.revision
    assert second.resolve("voice.stt.live_token") is None
    assert first.expires_at == policy().expires_at


def test_policy_cannot_admit_spoofed_product_or_subject_alias():
    with pytest.raises(ControlPlaneContractError):
        policy(scope_product="b66")
    with pytest.raises(ControlPlaneContractError):
        policy(scope_tenant="b62")
