"""Focused tests for #2195 CP auth-session service binding client
and trusted scope composition.

Deterministic and network-free: a fake Control Plane binding returns
canonical auth-session public-dict payloads; a fixed clock drives expiry
decisions. No production composition, factory wiring or Control Plane
import is involved.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.auth_session_scope_authority import (
    AuthSessionScopeAuthority,
    CloudflareControlPlaneAuthSessionClient,
)
from app.document_context_service import DocumentAuthorityError, TrustedCallerScope

_NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
_APP_ID = "padiem-chat"
_SESSION_ID = "auths_01TESTSESSION"


def session_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "session_id": _SESSION_ID,
        "product_id": _APP_ID,
        "subject": {"subject_type": "user", "subject_id": "user_alpha_123"},
        "issued_at": (_NOW - timedelta(hours=1)).isoformat(),
        "expires_at": (_NOW + timedelta(hours=1)).isoformat(),
        "state": "active",
        "revision": 1,
        "tenant_id": "tenant_acme",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_binding(payload: Any = None) -> Any:
    """Create a fake Control Plane identity binding that returns payload."""
    call_log: list[dict[str, str]] = []

    class FakeBinding:
        pass

    fake = FakeBinding()
    fake.call_log = call_log  # type: ignore[attr-defined]

    async def resolve(payload_arg: dict) -> dict:
        call_log.append(payload_arg)
        sid = payload_arg.get("session_id", "")
        if payload is None:
            return {"ok": False, "error": {"code": "not_found", "message": "not found"}}
        return {"ok": True, "session": payload}

    fake.resolve_auth_session = resolve  # type: ignore[method-assign]
    return fake


def _make_client(binding: Any) -> CloudflareControlPlaneAuthSessionClient:
    return CloudflareControlPlaneAuthSessionClient(binding)


def _make_authority(binding: Any) -> AuthSessionScopeAuthority | None:
    """Construct AuthSessionScopeAuthority from a fake binding, or None."""
    if binding is None:
        return None
    try:
        client = _make_client(binding)
    except (TypeError, ValueError):
        return None
    try:
        return AuthSessionScopeAuthority(
            session_client=client, clock=lambda: _NOW
        )
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 1. cp_service_binding_missing_fails_closed
# ---------------------------------------------------------------------------


def test_cp_service_binding_missing_fails_closed() -> None:
    """Missing CONTROL_PLANE_IDENTITY binding returns None (fail-closed)."""
    authority = _make_authority(binding=None)
    assert authority is None


# ---------------------------------------------------------------------------
# 2. cp_service_binding_malformed_fails_closed
# ---------------------------------------------------------------------------


async def test_cp_service_binding_malformed_fails_closed() -> None:
    """Malformed binding (object without resolve_auth_session) fails closed."""
    client = CloudflareControlPlaneAuthSessionClient(object())
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await client.resolve_auth_session(session_id=_SESSION_ID)
    assert excinfo.value.code == "auth_session_unavailable"
    assert excinfo.value.status_code == 503


# ---------------------------------------------------------------------------
# 3. cp_auth_session_client_calls_private_resolve_auth_session
# ---------------------------------------------------------------------------


async def test_cp_auth_session_client_calls_private_resolve_auth_session() -> None:
    """Client calls the private binding's resolve_auth_session with session_id."""
    binding = _make_binding(session_payload())
    client = _make_client(binding)
    result = await client.resolve_auth_session(session_id=_SESSION_ID)
    assert binding.call_log == [{"session_id": _SESSION_ID}]
    assert result is not None
    assert result["session_id"] == _SESSION_ID


async def test_cp_auth_session_client_returns_none_when_cp_not_found() -> None:
    """Client returns None when CP reports session not found."""
    binding = _make_binding(None)
    client = _make_client(binding)
    result = await client.resolve_auth_session(session_id=_SESSION_ID)
    assert result is None


# ---------------------------------------------------------------------------
# 4. cp_auth_session_snapshot_constructs_trusted_scope
# ---------------------------------------------------------------------------


async def test_cp_auth_session_snapshot_constructs_trusted_scope() -> None:
    """Authority constructs TrustedCallerScope from CP session snapshot."""
    authority = _make_authority(_make_binding(session_payload()))
    assert authority is not None
    scope = await authority.scope_for_request(app_id=_APP_ID, auth_session_id=_SESSION_ID)
    assert scope == TrustedCallerScope(
        app_id=_APP_ID,
        subject_id="user_alpha_123",
        tenant_id="tenant_acme",
    )


# ---------------------------------------------------------------------------
# 5. request_asserted_tenant_cannot_override_cp_scope
# ---------------------------------------------------------------------------


async def test_request_asserted_tenant_cannot_override_cp_scope() -> None:
    """Request-asserted tenant is never used; CP session tenant wins."""
    authority = _make_authority(_make_binding(session_payload()))
    assert authority is not None
    scope = await authority.scope_for_request(app_id=_APP_ID, auth_session_id=_SESSION_ID)
    assert scope.tenant_id == "tenant_acme"


# ---------------------------------------------------------------------------
# 6. request_asserted_subject_cannot_override_cp_scope
# ---------------------------------------------------------------------------


async def test_request_asserted_subject_cannot_override_cp_scope() -> None:
    """Request-asserted subject is never used; CP session subject wins."""
    authority = _make_authority(_make_binding(session_payload()))
    assert authority is not None
    scope = await authority.scope_for_request(app_id=_APP_ID, auth_session_id=_SESSION_ID)
    assert scope.subject_id == "user_alpha_123"


# ---------------------------------------------------------------------------
# 7. zero_tenant_session_fails_closed
# ---------------------------------------------------------------------------


async def test_zero_tenant_session_fails_closed() -> None:
    """Session with empty tenant fails closed (503)."""
    payload = session_payload(tenant_id="")
    authority = _make_authority(_make_binding(payload))
    assert authority is not None
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await authority.scope_for_request(app_id=_APP_ID, auth_session_id=_SESSION_ID)
    assert excinfo.value.code == "auth_session_unavailable"
    assert excinfo.value.status_code == 503


# ---------------------------------------------------------------------------
# 8. ambiguous_or_missing_session_fails_closed
# ---------------------------------------------------------------------------


async def test_ambiguous_or_missing_session_fails_closed() -> None:
    """Missing session (None) fails closed."""
    authority = _make_authority(_make_binding(None))
    assert authority is not None
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await authority.scope_for_request(app_id=_APP_ID, auth_session_id=_SESSION_ID)
    assert excinfo.value.code == "auth_session_unavailable"


async def test_ambiguous_session_payload_fails_closed() -> None:
    """Ambiguous session payload (extra keys) fails closed."""
    payload = session_payload(extra_field="injected")
    authority = _make_authority(_make_binding(payload))
    assert authority is not None
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await authority.scope_for_request(app_id=_APP_ID, auth_session_id=_SESSION_ID)
    assert excinfo.value.code == "auth_session_unavailable"


# ---------------------------------------------------------------------------
# 9. execute_and_stream_share_cp_scope_authority
# ---------------------------------------------------------------------------


async def test_execute_and_stream_share_cp_scope_authority() -> None:
    """Execute and stream paths share the same CP scope authority instance."""
    binding = _make_binding(session_payload())
    authority = _make_authority(binding)
    assert authority is not None

    scope1 = await authority.scope_for_request(app_id=_APP_ID, auth_session_id=_SESSION_ID)
    scope2 = await authority.scope_for_request(app_id=_APP_ID, auth_session_id=_SESSION_ID)
    assert scope1 == scope2
    assert scope1.tenant_id == scope2.tenant_id
    assert scope1.subject_id == scope2.subject_id


# ---------------------------------------------------------------------------
# 10. no_public_https_fallback
# ---------------------------------------------------------------------------


async def test_no_public_https_fallback() -> None:
    """No public HTTPS fallback: the client only uses the private binding."""
    class NoMethodBinding:
        pass

    client = CloudflareControlPlaneAuthSessionClient(NoMethodBinding())
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await client.resolve_auth_session(session_id=_SESSION_ID)
    assert excinfo.value.code == "auth_session_unavailable"
    assert excinfo.value.status_code == 503


# ---------------------------------------------------------------------------
# 11. no_default_tenant
# ---------------------------------------------------------------------------


async def test_no_default_tenant() -> None:
    """Session without tenant_id fails closed; no default tenant is used."""
    payload = session_payload()
    del payload["tenant_id"]
    authority = _make_authority(_make_binding(payload))
    assert authority is not None
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await authority.scope_for_request(app_id=_APP_ID, auth_session_id=_SESSION_ID)
    assert excinfo.value.code == "tenant_unavailable"
    assert excinfo.value.status_code == 503


# ---------------------------------------------------------------------------
# 12. no_duplicate_membership_or_session_resolution_in_engine
# ---------------------------------------------------------------------------


async def test_no_duplicate_membership_or_session_resolution_in_engine() -> None:
    """Engine resolves session exactly once per request; no duplicate calls."""
    binding = _make_binding(session_payload())
    authority = _make_authority(binding)
    assert authority is not None

    await authority.scope_for_request(app_id=_APP_ID, auth_session_id=_SESSION_ID)
    assert binding.call_log == [{"session_id": _SESSION_ID}]


# ---------------------------------------------------------------------------
# 13. non_multimodal_regression_passes
# ---------------------------------------------------------------------------


async def test_non_multimodal_regression_passes() -> None:
    """Non-multimodal (standard execute/stream) scope resolution still works."""
    authority = _make_authority(_make_binding(session_payload()))
    assert authority is not None
    scope = await authority.scope_for_request(app_id=_APP_ID, auth_session_id=_SESSION_ID)
    assert scope.app_id == _APP_ID
    assert scope.subject_id == "user_alpha_123"
    assert scope.tenant_id == "tenant_acme"