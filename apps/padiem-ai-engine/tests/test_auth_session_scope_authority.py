"""Focused tests for the #2168 S3b per-request CP auth-session scope seam.

Deterministic and network-free: a fake CP session client returns canonical
auth-session public-dict payloads; a fixed clock drives expiry decisions. No
production composition, factory wiring or Control Plane import is involved.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.auth_session_scope_authority import AuthSessionScopeAuthority
from app.document_context_service import DocumentAuthorityError, TrustedCallerScope

_NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
_APP_ID = "padiem-chat"
_SESSION_ID = "auths_01TESTSESSION"


class FakeSessionClient:
    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls: list[str] = []

    def resolve_auth_session(self, *, session_id: str) -> Any:
        self.calls.append(session_id)
        if self.error is not None:
            raise self.error
        return self.payload


class AsyncFakeSessionClient(FakeSessionClient):
    async def resolve_auth_session(self, *, session_id: str) -> Any:
        self.calls.append(session_id)
        if self.error is not None:
            raise self.error
        return self.payload


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


def authority_for(client: Any) -> AuthSessionScopeAuthority:
    return AuthSessionScopeAuthority(session_client=client, clock=lambda: _NOW)


async def scope_for(client: Any) -> TrustedCallerScope:
    return await authority_for(client).scope_for_request(
        app_id=_APP_ID, auth_session_id=_SESSION_ID
    )


# --- A. happy path: scope triple derived entirely from trusted sources -----


async def test_a_valid_session_mints_scope_from_caller_app_and_cp_session() -> None:
    client = FakeSessionClient(session_payload())
    scope = await scope_for(client)
    assert scope == TrustedCallerScope(
        app_id=_APP_ID, subject_id="user_alpha_123", tenant_id="tenant_acme"
    )
    assert client.calls == [_SESSION_ID]


async def test_b_subject_and_tenant_come_from_the_session_not_the_caller() -> None:
    client = FakeSessionClient(
        session_payload(
            subject={"subject_type": "account", "subject_id": "acct_zulu"},
            tenant_id="tenant_zulu",
        )
    )
    scope = await scope_for(client)
    assert (scope.app_id, scope.subject_id, scope.tenant_id) == (
        _APP_ID,
        "acct_zulu",
        "tenant_zulu",
    )


async def test_c_async_cp_client_is_supported() -> None:
    client = AsyncFakeSessionClient(session_payload())
    scope = await scope_for(client)
    assert scope.tenant_id == "tenant_acme"


# --- D. absent or malformed tenant fails closed, never defaults ------------


async def test_d_absent_tenant_key_fails_closed_without_default() -> None:
    payload = session_payload()
    del payload["tenant_id"]
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await scope_for(FakeSessionClient(payload))
    assert excinfo.value.code == "tenant_unavailable"
    assert excinfo.value.status_code == 503


async def test_e_null_tenant_fails_closed() -> None:
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await scope_for(FakeSessionClient(session_payload(tenant_id=None)))
    assert excinfo.value.code == "tenant_unavailable"


@pytest.mark.parametrize("tenant_id", [_APP_ID, "user_alpha_123"])
async def test_f_tenant_alias_to_app_or_subject_is_rejected(tenant_id: str) -> None:
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await scope_for(FakeSessionClient(session_payload(tenant_id=tenant_id)))
    assert excinfo.value.code == "tenant_unavailable"
    assert excinfo.value.status_code == 503


@pytest.mark.parametrize("tenant_id", ["", " tenant ", "t" * 129, 7, None.__class__])
async def test_g_malformed_tenant_identifier_is_rejected(tenant_id: Any) -> None:
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await scope_for(FakeSessionClient(session_payload(tenant_id=tenant_id)))
    assert excinfo.value.code in {"tenant_unavailable", "auth_session_unavailable"}
    assert excinfo.value.status_code == 503


# --- H. unresolvable or inactive sessions fail closed -----------------------


async def test_h_client_exception_fails_closed_without_reflection() -> None:
    client = FakeSessionClient(error=RuntimeError("upstream secret detail"))
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await scope_for(client)
    assert excinfo.value.code == "auth_session_unavailable"
    assert excinfo.value.status_code == 503
    assert "secret" not in excinfo.value.safe_message


async def test_i_missing_session_returns_none_fails_closed() -> None:
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await scope_for(FakeSessionClient(None))
    assert excinfo.value.code == "auth_session_unavailable"


@pytest.mark.parametrize("state", ["revoked", "expired"])
async def test_j_inactive_session_states_are_rejected(state: str) -> None:
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await scope_for(FakeSessionClient(session_payload(state=state)))
    assert excinfo.value.code == "auth_session_inactive"
    assert excinfo.value.status_code == 403


async def test_k_active_session_past_expiry_is_rejected_by_clock() -> None:
    authority = AuthSessionScopeAuthority(
        session_client=FakeSessionClient(session_payload()),
        clock=lambda: _NOW + timedelta(hours=2),
    )
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await authority.scope_for_request(
            app_id=_APP_ID, auth_session_id=_SESSION_ID
        )
    assert excinfo.value.code == "auth_session_inactive"


# --- L. closed wire schema: no request-asserted or extra fields ------------


@pytest.mark.parametrize(
    "payload",
    [
        session_payload(tenant="raw_tenant_assertion"),
        session_payload(subject={"subject_type": "user", "subject_id": "u", "role": "owner"}),
        {k: v for k, v in session_payload().items() if k != "revision"},
        session_payload(subject="user_alpha_123"),
        session_payload(subject_type="user"),
    ],
)
async def test_l_schema_violations_fail_closed(payload: dict[str, Any]) -> None:
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await scope_for(FakeSessionClient(payload))
    assert excinfo.value.code == "auth_session_unavailable"
    assert excinfo.value.status_code == 503


@pytest.mark.parametrize("subject_type", ["service", "SESSION", ""])
async def test_m_unknown_subject_types_are_rejected(subject_type: str) -> None:
    payload = session_payload(
        subject={"subject_type": subject_type, "subject_id": "u1"}
    )
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await scope_for(FakeSessionClient(payload))
    assert excinfo.value.code == "auth_session_unavailable"


# --- N. cross-binding guards: session must belong to this app/request ------


async def test_n_session_for_another_product_is_rejected() -> None:
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await scope_for(FakeSessionClient(session_payload(product_id="other_app")))
    assert excinfo.value.code == "auth_scope_mismatch"
    assert excinfo.value.status_code == 403


async def test_o_session_id_mismatch_between_payload_and_clue_is_rejected() -> None:
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await scope_for(FakeSessionClient(session_payload(session_id="auths_other")))
    assert excinfo.value.code == "auth_scope_mismatch"


# --- P. request-context input validation happens before any port call ------


@pytest.mark.parametrize("app_id", ["", " ", "chat app", "a" * 129, None, 5])
async def test_p_invalid_app_id_never_reaches_the_port(app_id: Any) -> None:
    client = FakeSessionClient(session_payload())
    authority = authority_for(client)
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await authority.scope_for_request(
            app_id=app_id, auth_session_id=_SESSION_ID
        )
    assert excinfo.value.code == "auth_session_unavailable"
    assert client.calls == []


@pytest.mark.parametrize("session_id", ["", "bad id", "s" * 129, None])
async def test_q_invalid_auth_session_clue_never_reaches_the_port(session_id: Any) -> None:
    client = FakeSessionClient(session_payload())
    authority = authority_for(client)
    with pytest.raises(DocumentAuthorityError) as excinfo:
        await authority.scope_for_request(app_id=_APP_ID, auth_session_id=session_id)
    assert excinfo.value.code == "auth_session_unavailable"
    assert client.calls == []


async def test_r_construction_requires_the_resolution_port() -> None:
    with pytest.raises(ValueError):
        AuthSessionScopeAuthority(session_client=object())
