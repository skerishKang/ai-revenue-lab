from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from calendar_binding_selection import TrustedCalendarBindingSelectionCallsite
from google_oauth_durable_store import (
    GoogleOAuthBindingSelection,
    GoogleOAuthBindingSelectionStatus,
)
from identity_connector_ticket import CanonicalConnectorContext
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def session() -> AuthSessionSnapshot:
    return AuthSessionSnapshot(
        session_id="auth-session-1",
        product_id="b62",
        subject=CanonicalSubjectRef(SubjectType.USER, "user-1"),
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
        revision=1,
    )


def context() -> CanonicalConnectorContext:
    return CanonicalConnectorContext(
        product_id="b62",
        subject_id="user-1",
        actor_ref="actor-1",
        account_ref="account-1",
        workspace_ref="workspace-1",
        created_at=NOW - timedelta(minutes=1),
    )


class FakeContextStore:
    def __init__(self, result: CanonicalConnectorContext | None) -> None:
        self.result = result
        self.calls: list[tuple[AuthSessionSnapshot, datetime]] = []

    def resolve_existing(
        self,
        *,
        auth_session: AuthSessionSnapshot,
        now: datetime,
    ) -> CanonicalConnectorContext | None:
        self.calls.append((auth_session, now))
        return self.result

    def resolve_or_create(self, **kwargs):
        raise AssertionError("callsite must not create connector context")


class FakeOAuthStore:
    def __init__(self, result: GoogleOAuthBindingSelection | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, datetime]] = []

    def select_active_calendar_binding(
        self,
        *,
        workspace_ref: str,
        now: datetime,
    ) -> GoogleOAuthBindingSelection:
        self.calls.append((workspace_ref, now))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def resolved_selection() -> GoogleOAuthBindingSelection:
    return GoogleOAuthBindingSelection(
        status=GoogleOAuthBindingSelectionStatus.RESOLVED,
        connector_id="google-calendar",
        workspace_ref="workspace-1",
        binding_ref="binding-1",
        actor_ref="actor-1",
        account_ref="account-1",
    )


def test_exact_trusted_auth_session_workspace_reaches_existing_selector() -> None:
    context_store = FakeContextStore(context())
    oauth_store = FakeOAuthStore(resolved_selection())
    callsite = TrustedCalendarBindingSelectionCallsite(
        context_store=context_store,
        oauth_store=oauth_store,
    )

    result = callsite.select_for_auth_session(auth_session=session(), now=NOW)

    assert result is oauth_store.result
    assert context_store.calls == [(session(), NOW)]
    assert oauth_store.calls == [("workspace-1", NOW)]


def test_missing_trusted_workspace_fails_before_selector() -> None:
    context_store = FakeContextStore(None)
    oauth_store = FakeOAuthStore(resolved_selection())
    callsite = TrustedCalendarBindingSelectionCallsite(
        context_store=context_store,
        oauth_store=oauth_store,
    )

    with pytest.raises(ControlPlaneContractError) as caught:
        callsite.select_for_auth_session(auth_session=session(), now=NOW)

    assert caught.value.code == "trusted_workspace_unavailable"
    assert oauth_store.calls == []


def test_caller_cannot_supply_workspace_to_callsite() -> None:
    signature = inspect.signature(
        TrustedCalendarBindingSelectionCallsite.select_for_auth_session
    )
    assert "workspace_ref" not in signature.parameters
    with pytest.raises(TypeError):
        TrustedCalendarBindingSelectionCallsite.select_for_auth_session(
            object(),
            auth_session=session(),
            now=NOW,
            workspace_ref="caller-workspace",
        )


def test_zero_binding_selection_remains_not_connected() -> None:
    not_connected = GoogleOAuthBindingSelection(
        status=GoogleOAuthBindingSelectionStatus.NOT_CONNECTED,
        connector_id="google-calendar",
        workspace_ref="workspace-1",
    )
    callsite = TrustedCalendarBindingSelectionCallsite(
        context_store=FakeContextStore(context()),
        oauth_store=FakeOAuthStore(not_connected),
    )

    assert (
        callsite.select_for_auth_session(auth_session=session(), now=NOW)
        is not_connected
    )


def test_duplicate_binding_error_is_not_resolved_or_hidden() -> None:
    duplicate = ControlPlaneContractError(
        "ambiguous_google_oauth_binding",
        "multiple usable Calendar bindings",
    )
    callsite = TrustedCalendarBindingSelectionCallsite(
        context_store=FakeContextStore(context()),
        oauth_store=FakeOAuthStore(duplicate),
    )

    with pytest.raises(ControlPlaneContractError) as caught:
        callsite.select_for_auth_session(auth_session=session(), now=NOW)

    assert caught.value.code == "ambiguous_google_oauth_binding"


def test_callsite_is_private_and_has_no_credential_projection() -> None:
    callsite = TrustedCalendarBindingSelectionCallsite(
        context_store=FakeContextStore(context()),
        oauth_store=FakeOAuthStore(resolved_selection()),
    )

    rendered = str(callsite.safe_dict())
    assert callsite.safe_dict()["caller_workspace_authority"] is False
    assert callsite.safe_dict()["public_route"] is False
    assert callsite.safe_dict()["public_identity_projection"] is False
    assert callsite.safe_dict()["raw_refresh_token_output"] is False
    assert callsite.safe_dict()["sealed_refresh_token_output"] is False
    assert callsite.safe_dict()["access_token_output"] is False
    assert callsite.safe_dict()["client_secret_output"] is False
    assert "sealed:v1:" not in rendered
    assert "Bearer " not in rendered
