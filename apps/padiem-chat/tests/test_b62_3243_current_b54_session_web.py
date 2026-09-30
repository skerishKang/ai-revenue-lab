"""#3243 — Web-side current B54 session resolution (adapter + Web request helper).

Companion to the Control Plane package tests
(``test_b54_current_session_resolver.py`` and
``test_identity_authority_current_session.py``), which cover the durable selection
logic and the private RPC shape. This file covers the Padiem Chat layers, so it
lives where the ``app`` package and pytest-asyncio are available:

- the Worker adapter forwards only ``product_id`` + ``product_user_id``
- the Web helper derives the product user from the signed Padiem session only
- forged query / body / header / cookie identity fields change nothing
- the product is pinned server-side to ``b54-padiem-claw``
- nothing from the resolved B54 session reaches a browser payload
"""

from __future__ import annotations

import inspect
import json
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.b54_identity_bridge import B54_PRODUCT_ID
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

from app.control_plane_identity import IdentityBridgeError
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
USER = "usr_" + "3" * 32
SUBJECT = "sub_" + "4" * 32
TENANT = "tenant_" + "5" * 32


def _session() -> AuthSessionSnapshot:
    return AuthSessionSnapshot(
        session_id="sess_" + "6" * 32,
        product_id=B54_PRODUCT_ID,
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=SUBJECT),
        issued_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
        revision=1,
        tenant_id=TENANT,
    )


class _Authority:
    """Only the expected user resolves; any other id has no session."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def resolve_current_auth_session(self, *, product_id, product_user_id):
        self.calls.append({"product_id": product_id, "product_user_id": product_user_id})
        if product_user_id != USER:
            raise RuntimeError("unavailable")
        return _session()

    async def resolve_or_create_product_link(self, **kwargs):
        raise AssertionError("must not create a product link")

    async def establish_auth_session(self, **kwargs):
        raise AssertionError("must not mint a session")


def _request(app_state, **adversarial) -> "types.SimpleNamespace":
    class _Request:
        def __init__(self) -> None:
            self.app = types.SimpleNamespace(state=app_state)
            self.query_params = dict(adversarial.pop("query", {}))
            self.cookies = dict(adversarial.pop("cookies", {}))
            self.headers = dict(adversarial.pop("headers", {}))
            self._body = dict(adversarial.pop("body", {}))

        async def json(self):
            return self._body

    return _Request()


def _signed_in(monkeypatch, user_id):
    import app.auth_routes as auth_routes

    monkeypatch.setattr(auth_routes, "current_user_id", lambda req: user_id)
    monkeypatch.setattr(auth_routes, "auth_ready", lambda req: True)


# ── adapter ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_adapter_sends_only_product_and_user() -> None:
    calls: list[tuple[str, dict]] = []

    class _Rpc:
        async def __call__(self, name, payload, key):
            calls.append((name, payload))
            return json.loads(json.dumps(_session().to_public_dict()))

    adapter = CloudflareControlPlaneIdentityAuthority.__new__(
        CloudflareControlPlaneIdentityAuthority
    )
    adapter._rpc = _Rpc()
    resolved = await adapter.resolve_current_auth_session(
        product_id=B54_PRODUCT_ID, product_user_id=USER
    )
    assert resolved.product_id == B54_PRODUCT_ID
    assert len(calls) == 1
    name, payload = calls[0]
    assert name == "resolve_current_auth_session"
    assert set(payload) == {"product_id", "product_user_id"}
    for forbidden in ("session_id", "subject", "tenant_id", "now", "expires_at"):
        assert forbidden not in payload


@pytest.mark.asyncio
async def test_adapter_refuses_missing_product_or_user() -> None:
    adapter = CloudflareControlPlaneIdentityAuthority.__new__(
        CloudflareControlPlaneIdentityAuthority
    )
    adapter._rpc = MagicMock()
    for kwargs in (
        {"product_id": "", "product_user_id": USER},
        {"product_id": B54_PRODUCT_ID, "product_user_id": ""},
    ):
        with pytest.raises(IdentityBridgeError):
            await adapter.resolve_current_auth_session(**kwargs)


# ── Web request helper ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_web_helper_resolves_from_the_signed_session_only(monkeypatch) -> None:
    import app.b54_canonical_session as b54_module

    authority = _Authority()

    class _State:
        control_plane_identity_authority = authority

    _signed_in(monkeypatch, USER)
    request = _request(
        _State(),
        query={
            "session_id": "sess_FORGED",
            "product_id": "b62",
            "product_user_id": "usr_FORGED",
            "subject_id": "sub_FORGED",
            "tenant_id": "tenant_FORGED",
            "workspace_id": "ws_FORGED",
            "provider": "google",
            "now": "2099-01-01T00:00:00Z",
            "expires_at": "2099-01-01T00:00:00Z",
        },
        body={
            "session_id": "sess_FORGED",
            "product_id": "b62",
            "product_user_id": "usr_FORGED_BODY",
            "tenant_id": "tenant_FORGED_BODY",
        },
        headers={
            "x-product-user-id": "usr_FORGED_HEADER",
            "x-tenant-id": "tenant_FORGED_HEADER",
        },
        cookies={"session": "forged-session-cookie", "auth_session_id": "sess_FORGED"},
    )
    resolved = await b54_module.resolve_current_b54_canonical_session(request)
    assert resolved is not None
    assert resolved.product_user_id == USER
    # Only the signed-in user and the server-pinned product were used.
    assert authority.calls == [{"product_id": B54_PRODUCT_ID, "product_user_id": USER}]
    for forged in ("FORGED", "b62"):
        assert forged not in str(authority.calls)


@pytest.mark.asyncio
async def test_web_helper_returns_none_when_signed_out(monkeypatch) -> None:
    import app.b54_canonical_session as b54_module

    authority = _Authority()

    class _State:
        control_plane_identity_authority = authority

    _signed_in(monkeypatch, None)
    request = _request(_State())
    assert await b54_module.resolve_current_b54_canonical_session(request) is None
    assert authority.calls == []


@pytest.mark.asyncio
async def test_web_helper_returns_none_without_a_control_plane_binding(monkeypatch) -> None:
    import app.b54_canonical_session as b54_module

    class _State:
        control_plane_identity_authority = None

    _signed_in(monkeypatch, USER)
    assert await b54_module.resolve_current_b54_canonical_session(_request(_State())) is None


@pytest.mark.asyncio
async def test_web_helper_never_discloses_another_users_session(monkeypatch) -> None:
    import app.b54_canonical_session as b54_module

    authority = _Authority()

    class _State:
        control_plane_identity_authority = authority

    _signed_in(monkeypatch, "usr_" + "8" * 32)
    assert await b54_module.resolve_current_b54_canonical_session(_request(_State())) is None


def test_helper_builds_no_browser_payload() -> None:
    import app.b54_canonical_session as b54_module

    source = inspect.getsource(b54_module.resolve_current_b54_canonical_session)
    for forbidden in ("JSONResponse", "RedirectResponse", "set_cookie", "html", "template"):
        assert forbidden not in source
    # No B54 identity field is copied into a response-shaped structure.
    for forbidden in ("session_id", "canonical_subject", "tenant_id"):
        assert forbidden not in source
