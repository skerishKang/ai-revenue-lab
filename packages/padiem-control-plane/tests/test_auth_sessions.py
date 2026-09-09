from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane.auth_sessions import (
    AuthSessionSnapshot,
    AuthSessionState,
    AuthSessionTransition,
    AuthSessionTransitionKind,
    apply_auth_session_transition,
    validate_auth_session_transition_batch,
)
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)


NOW = datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc)


def subject() -> CanonicalSubjectRef:
    return CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="user_123")


def session(**overrides) -> AuthSessionSnapshot:
    values = {
        "session_id": "session_1",
        "product_id": "b62",
        "subject": subject(),
        "issued_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
        "state": AuthSessionState.ACTIVE,
        "revision": 1,
    }
    values.update(overrides)
    return AuthSessionSnapshot(**values)


def test_active_session_expires_by_time_without_client_state() -> None:
    snapshot = session()

    assert snapshot.effective_state(now=NOW + timedelta(minutes=30)) is AuthSessionState.ACTIVE
    assert snapshot.effective_state(now=NOW + timedelta(hours=1)) is AuthSessionState.EXPIRED
    assert snapshot.is_active(now=NOW + timedelta(hours=2)) is False


def test_revocation_is_terminal_and_exact_revision() -> None:
    snapshot = session()
    transition = AuthSessionTransition(
        event_id="event_revoke_1",
        session_id="session_1",
        kind=AuthSessionTransitionKind.REVOKE,
        occurred_at=NOW + timedelta(minutes=5),
        from_revision=1,
        reason_code="user_signout",
    )

    applied = apply_auth_session_transition(snapshot, transition)
    assert applied.current.state is AuthSessionState.REVOKED
    assert applied.current.revision == 2
    assert applied.current.subject == snapshot.subject

    with pytest.raises(ControlPlaneContractError) as exc_info:
        apply_auth_session_transition(
            applied.current,
            AuthSessionTransition(
                event_id="event_revoke_2",
                session_id="session_1",
                kind=AuthSessionTransitionKind.REVOKE,
                occurred_at=NOW + timedelta(minutes=6),
                from_revision=2,
            ),
        )
    assert exc_info.value.code == "terminal_auth_session"


def test_expiry_transition_cannot_materialize_before_expiry() -> None:
    snapshot = session()

    with pytest.raises(ControlPlaneContractError) as exc_info:
        apply_auth_session_transition(
            snapshot,
            AuthSessionTransition(
                event_id="event_expire_early",
                session_id="session_1",
                kind=AuthSessionTransitionKind.EXPIRE,
                occurred_at=NOW + timedelta(minutes=59),
                from_revision=1,
            ),
        )
    assert exc_info.value.code == "premature_auth_session_expiry"

    applied = apply_auth_session_transition(
        snapshot,
        AuthSessionTransition(
            event_id="event_expire_1",
            session_id="session_1",
            kind=AuthSessionTransitionKind.EXPIRE,
            occurred_at=NOW + timedelta(hours=1),
            from_revision=1,
        ),
    )
    assert applied.current.state is AuthSessionState.EXPIRED


def test_stale_revision_and_session_mismatch_fail_closed() -> None:
    snapshot = session()

    with pytest.raises(ControlPlaneContractError) as exc_info:
        apply_auth_session_transition(
            snapshot,
            AuthSessionTransition(
                event_id="event_stale",
                session_id="session_1",
                kind=AuthSessionTransitionKind.REVOKE,
                occurred_at=NOW + timedelta(minutes=1),
                from_revision=2,
            ),
        )
    assert exc_info.value.code == "stale_auth_session_transition"

    with pytest.raises(ControlPlaneContractError) as exc_info:
        apply_auth_session_transition(
            snapshot,
            AuthSessionTransition(
                event_id="event_other",
                session_id="session_other",
                kind=AuthSessionTransitionKind.REVOKE,
                occurred_at=NOW + timedelta(minutes=1),
                from_revision=1,
            ),
        )
    assert exc_info.value.code == "auth_session_mismatch"


def test_session_requires_timezone_aware_monotonic_times() -> None:
    with pytest.raises(ControlPlaneContractError):
        session(issued_at=datetime(2026, 8, 31, 0, 0))

    with pytest.raises(ControlPlaneContractError):
        session(expires_at=NOW)


def test_public_session_contract_contains_no_tokens_or_credentials() -> None:
    public = session().to_public_dict()

    assert public["session_id"] == "session_1"
    assert public["subject"]["subject_id"] == "user_123"
    serialized = repr(public).lower()
    for forbidden in (
        "bearer",
        "password",
        "refresh_token",
        "access_token",
        "cookie_value",
        "oauth_token",
    ):
        assert forbidden not in serialized


def test_duplicate_transition_event_ids_fail_closed() -> None:
    snapshot = session()
    transition = AuthSessionTransition(
        event_id="event_duplicate",
        session_id="session_1",
        kind=AuthSessionTransitionKind.REVOKE,
        occurred_at=NOW + timedelta(minutes=1),
        from_revision=1,
    )

    with pytest.raises(ControlPlaneContractError) as exc_info:
        validate_auth_session_transition_batch(snapshot, (transition, transition))
    assert exc_info.value.code == "duplicate_auth_session_event"


def test_anonymous_subject_is_supported_without_making_browser_authoritative() -> None:
    anonymous = CanonicalSubjectRef(
        subject_type=SubjectType.ANONYMOUS,
        subject_id="anon_123",
    )
    snapshot = session(subject=anonymous)

    assert snapshot.subject.subject_type is SubjectType.ANONYMOUS
    assert snapshot.is_active(now=NOW + timedelta(minutes=1)) is True

def test_tenant_id_is_absent_by_default_and_wire_omits_the_key() -> None:
    snapshot = session()

    assert snapshot.tenant_id is None
    assert set(snapshot.to_public_dict()) == {
        "session_id",
        "product_id",
        "subject",
        "issued_at",
        "expires_at",
        "state",
        "revision",
    }


def test_distinct_bounded_tenant_fact_is_carried_in_state_and_wire() -> None:
    snapshot = session(tenant_id="tenant_alpha-1")

    assert snapshot.tenant_id == "tenant_alpha-1"
    assert snapshot.to_public_dict()["tenant_id"] == "tenant_alpha-1"


def test_tenant_id_never_aliases_product_or_subject() -> None:
    with pytest.raises(ControlPlaneContractError) as exc_info:
        session(tenant_id="b62")
    assert exc_info.value.code == "invalid_auth_session"

    with pytest.raises(ControlPlaneContractError) as exc_info:
        session(tenant_id="user_123")
    assert exc_info.value.code == "invalid_auth_session"


@pytest.mark.parametrize(
    "value",
    [
        "",
        " tenant_1",
        "tenant 1",
        "-tenant",
        "tenant\n1",
        "tenant_1;drop",
        "x" * 129,
        123,
        True,
    ],
)
def test_malformed_or_oversized_tenant_id_fails_closed(value) -> None:
    with pytest.raises(ControlPlaneContractError) as exc_info:
        session(tenant_id=value)
    assert exc_info.value.code == "invalid_auth_session"


def test_tenant_fact_survives_terminal_transition_batch() -> None:
    snapshot = session(tenant_id="tenant_alpha")
    applied = apply_auth_session_transition(
        snapshot,
        AuthSessionTransition(
            event_id="event_revoke_tenant",
            session_id="session_1",
            kind=AuthSessionTransitionKind.REVOKE,
            occurred_at=NOW + timedelta(minutes=5),
            from_revision=1,
        ),
    )

    assert applied.current.tenant_id == "tenant_alpha"
    assert applied.current.to_public_dict()["tenant_id"] == "tenant_alpha"
