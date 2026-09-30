"""#3243 — the B54 current-session resolver across Worker RPC, adapter and bridge.

Layered on top of ``test_identity_authority_current_session.py`` (which proves the
durable selection logic). Here the private RPC shape, the Padiem Chat adapter and
the B54 bridge validation are covered:

- the RPC accepts exactly ``product_id`` + ``product_user_id`` and refuses any
  session_id / subject_id / tenant_id / workspace_id / provider / now / expires_at
- the Worker's own clock is used, never the caller's
- the adapter never forwards a caller-supplied session reference
- the bridge pins the product to ``b54-padiem-claw`` and rejects a B62 session,
  a non-USER subject, a tenant-less session and an inactive one
- the Web helper reads only the signed-in product user id, so forged query, body,
  header and cookie values cannot steer it
- nothing from the resolved B54 session is written into a browser payload
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import pathlib
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.b54_identity_bridge import (
    B54_PRODUCT_ID,
    B54IdentityBridgeError,
    resolve_current_b54_canonical_session,
)
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    SubjectType,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
USER = "usr_" + "3" * 32
SUBJECT = "sub_" + "4" * 32
TENANT = "tenant_" + "5" * 32
PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── worker RPC shape ───────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, body="", *, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(self, env=None):
        self.env = env


class _FakeDurableObject:
    def __init__(self, ctx, env):
        self.ctx = ctx
        self.env = env


_workers = types.ModuleType("workers")
_workers.Response = _FakeResponse
_workers.WorkerEntrypoint = _FakeWorkerEntrypoint
_workers.DurableObject = _FakeDurableObject
sys.modules.setdefault("workers", _workers)

_worker_path = PACKAGE_ROOT / "identity_authority_worker.py"
_worker_spec = importlib.util.spec_from_file_location(
    "padiem_identity_authority_worker_3243_test", _worker_path
)
assert _worker_spec is not None and _worker_spec.loader is not None
_worker_mod = importlib.util.module_from_spec(_worker_spec)
sys.modules[_worker_spec.name] = _worker_mod
_worker_spec.loader.exec_module(_worker_mod)


def _session(
    *,
    product_id: str = B54_PRODUCT_ID,
    subject_id: str = SUBJECT,
    state: AuthSessionState = AuthSessionState.ACTIVE,
    tenant_id: str | None = TENANT,
    issued_at: datetime = NOW - timedelta(hours=1),
    expires_at: datetime = NOW + timedelta(hours=1),
    subject_type: SubjectType = SubjectType.USER,
) -> AuthSessionSnapshot:
    return AuthSessionSnapshot(
        session_id="sess_" + "6" * 32,
        product_id=product_id,
        subject=CanonicalSubjectRef(subject_type=subject_type, subject_id=subject_id),
        issued_at=issued_at,
        expires_at=expires_at,
        state=state,
        revision=1,
        tenant_id=tenant_id,
    )


class _RecordingStore:
    """Stands in for the Durable Object store and records the selection call."""

    def __init__(self, session=None) -> None:
        self.session = session
        self.calls: list[dict] = []

    def resolve_current_auth_session_for_product_user(self, **kwargs):
        self.calls.append(kwargs)
        if self.session is None:
            from padiem_control_plane.contracts import ControlPlaneContractError

            raise ControlPlaneContractError(
                "canonical_auth_session_not_found", "no active canonical auth session"
            )
        return self.session


def _do_rpc(store):
    do = _worker_mod.CanonicalIdentityDurableObject.__new__(
        _worker_mod.CanonicalIdentityDurableObject
    )
    do._store = store
    return do


@pytest.mark.asyncio
async def test_rpc_returns_session_for_product_and_user() -> None:
    store = _RecordingStore(_session())
    result = await _do_rpc(store).resolve_current_auth_session(
        {"product_id": B54_PRODUCT_ID, "product_user_id": USER}
    )
    assert result["ok"] is True
    assert result["session"]["product_id"] == B54_PRODUCT_ID
    assert store.calls == [
        {"product_id": B54_PRODUCT_ID, "product_user_id": USER, "now": store.calls[0]["now"]}
    ]


@pytest.mark.asyncio
async def test_rpc_uses_the_worker_clock_not_the_caller() -> None:
    store = _RecordingStore(_session())
    await _do_rpc(store).resolve_current_auth_session(
        {"product_id": B54_PRODUCT_ID, "product_user_id": USER}
    )
    used = store.calls[0]["now"]
    # A server clock, never the fixed test constant.
    assert abs((used - datetime.now(timezone.utc)).total_seconds()) < 60


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra",
    [
        {"session_id": "sess_" + "1" * 32},
        {"subject_id": SUBJECT},
        {"tenant_id": TENANT},
        {"workspace_id": "ws_1"},
        {"provider": "google"},
        {"now": NOW.isoformat()},
        {"expires_at": (NOW + timedelta(days=1)).isoformat()},
        {"state": "active"},
        {"revision": 9},
    ],
)
async def test_rpc_refuses_any_caller_supplied_authority_field(extra) -> None:
    store = _RecordingStore(_session())
    result = await _do_rpc(store).resolve_current_auth_session(
        {"product_id": B54_PRODUCT_ID, "product_user_id": USER, **extra}
    )
    assert result["ok"] is False
    assert store.calls == [], "a rejected payload must not reach the store"


@pytest.mark.asyncio
async def test_rpc_missing_required_field_fails_closed() -> None:
    store = _RecordingStore(_session())
    for payload in (
        {"product_id": B54_PRODUCT_ID},
        {"product_user_id": USER},
        {},
    ):
        result = await _do_rpc(store).resolve_current_auth_session(payload)
        assert result["ok"] is False
    assert store.calls == []


@pytest.mark.asyncio
async def test_rpc_reports_missing_session_without_disclosure() -> None:
    store = _RecordingStore(None)
    result = await _do_rpc(store).resolve_current_auth_session(
        {"product_id": B54_PRODUCT_ID, "product_user_id": USER}
    )
    assert result["ok"] is False
    assert "session" not in result


def test_gateway_exposes_the_new_rpc_and_keeps_resolve_auth_session() -> None:
    assert hasattr(_worker_mod.Default, "resolve_current_auth_session")
    assert hasattr(_worker_mod.Default, "resolve_auth_session")


# ── Padiem Chat adapter ────────────────────────────────────────────────────


def _adapter_session():
    return _session()


@pytest.mark.asyncio
async def test_adapter_sends_only_product_and_user() -> None:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "apps" / "padiem-chat"))
    from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority

    calls: list[tuple[str, dict]] = []

    class _Rpc:
        async def __call__(self, name, payload, key):
            calls.append((name, payload))
            return json.loads(json.dumps(_adapter_session().to_public_dict()))

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
    assert "session_id" not in payload
    assert "subject" not in payload
    assert "tenant_id" not in payload


@pytest.mark.asyncio
async def test_adapter_refuses_missing_product_or_user() -> None:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "apps" / "padiem-chat"))
    from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
    from app.control_plane_identity import IdentityBridgeError

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


# ── B54 bridge validation ──────────────────────────────────────────────────


class _Authority:
    """Only ``USER`` has a session; any other product user resolves to nothing."""

    def __init__(self, session=None) -> None:
        self.session = session
        self.calls: list[dict] = []

    async def resolve_current_auth_session(self, *, product_id, product_user_id):
        self.calls.append(
            {"product_id": product_id, "product_user_id": product_user_id}
        )
        if self.session is None or product_user_id != USER:
            raise RuntimeError("unavailable")
        return self.session

    async def resolve_or_create_product_link(self, **kwargs):
        raise AssertionError("current-session resolution must not create a product link")

    async def establish_auth_session(self, **kwargs):
        raise AssertionError("current-session resolution must not mint a session")


@pytest.mark.asyncio
async def test_bridge_returns_the_b54_session_with_pinned_product() -> None:
    authority = _Authority(_session())
    bridged = await resolve_current_b54_canonical_session(authority, USER, now=NOW)
    assert bridged.auth_session.product_id == B54_PRODUCT_ID
    assert bridged.product_user_id == USER
    assert bridged.auth_session.tenant_id == TENANT
    # The product is pinned server-side, never taken from the caller.
    assert authority.calls == [
        {"product_id": B54_PRODUCT_ID, "product_user_id": USER}
    ]


@pytest.mark.asyncio
async def test_bridge_rejects_a_b62_session_for_the_same_person() -> None:
    authority = _Authority(_session(product_id="b62"))
    with pytest.raises(B54IdentityBridgeError) as excinfo:
        await resolve_current_b54_canonical_session(authority, USER, now=NOW)
    assert excinfo.value.code == "b54_control_plane_session_mismatch"


@pytest.mark.asyncio
async def test_bridge_rejects_tenant_less_session() -> None:
    authority = _Authority(_session(tenant_id=None))
    with pytest.raises(B54IdentityBridgeError) as excinfo:
        await resolve_current_b54_canonical_session(authority, USER, now=NOW)
    assert excinfo.value.code == "b54_control_plane_session_tenant_mismatch"


@pytest.mark.asyncio
async def test_bridge_rejects_non_user_subject() -> None:
    for subject_type in (SubjectType.ANONYMOUS, SubjectType.ACCOUNT):
        authority = _Authority(_session(subject_type=subject_type))
        with pytest.raises(B54IdentityBridgeError) as excinfo:
            await resolve_current_b54_canonical_session(authority, USER, now=NOW)
        assert excinfo.value.code == "b54_control_plane_session_mismatch"


@pytest.mark.asyncio
async def test_bridge_rejects_revoked_and_expired_sessions() -> None:
    revoked = _Authority(_session(state=AuthSessionState.REVOKED))
    with pytest.raises(B54IdentityBridgeError) as revoked_error:
        await resolve_current_b54_canonical_session(revoked, USER, now=NOW)
    assert revoked_error.value.code == "b54_control_plane_session_inactive"

    lapsed = _Authority(
        _session(
            issued_at=NOW - timedelta(hours=3),
            expires_at=NOW - timedelta(hours=1),
        )
    )
    with pytest.raises(B54IdentityBridgeError) as lapsed_error:
        await resolve_current_b54_canonical_session(lapsed, USER, now=NOW)
    assert lapsed_error.value.code == "b54_control_plane_session_inactive"


@pytest.mark.asyncio
async def test_bridge_rejects_foreign_or_malformed_user_id() -> None:
    authority = _Authority(_session())
    # Shape failures never reach the authority at all.
    for bad in ("", "not-usr", None, 12345, "a" * 200):
        with pytest.raises(B54IdentityBridgeError):
            await resolve_current_b54_canonical_session(authority, bad, now=NOW)
    assert authority.calls == []
    # A well-formed but unknown id reaches the authority and simply resolves to
    # nothing — the same fail-closed result, never a foreign session.
    with pytest.raises(B54IdentityBridgeError):
        await resolve_current_b54_canonical_session(authority, "usr_FORGED", now=NOW)
    assert [call["product_user_id"] for call in authority.calls] == ["usr_FORGED"]


@pytest.mark.asyncio
async def test_bridge_fails_closed_without_an_authority() -> None:
    with pytest.raises(B54IdentityBridgeError) as excinfo:
        await resolve_current_b54_canonical_session(None, USER, now=NOW)
    assert excinfo.value.code == "b54_control_plane_identity_unavailable"


# ── Web request helper: no caller authority, no browser output ─────────────


def _signed_in_request(app_state, **adversarial):
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


@pytest.mark.asyncio
async def test_web_helper_resolves_from_the_signed_session_only() -> None:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "apps" / "padiem-chat"))
    import app.auth_routes as auth_routes
    import app.b54_canonical_session as b54_module

    authority = _Authority(_session())

    class _State:
        control_plane_identity_authority = authority

    request = _signed_in_request(
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

    # The signed Padiem session is the only authority for the product user id.
    original_current_user_id = auth_routes.current_user_id
    auth_routes.current_user_id = lambda req: USER
    auth_routes.auth_ready = lambda req: True
    try:
        resolved = await b54_module.resolve_current_b54_canonical_session(request)
    finally:
        auth_routes.current_user_id = original_current_user_id
    assert resolved is not None
    assert resolved.product_user_id == USER
    # Only the signed-in user and the server-pinned product were used.
    assert authority.calls == [{"product_id": B54_PRODUCT_ID, "product_user_id": USER}]
    for forged in ("FORGED", "b62"):
        assert forged not in str(authority.calls)


@pytest.mark.asyncio
async def test_web_helper_returns_none_when_signed_out_or_unbound() -> None:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "apps" / "padiem-chat"))
    import app.auth_routes as auth_routes
    import app.b54_canonical_session as b54_module

    class _State:
        control_plane_identity_authority = None

    request = _signed_in_request(_State())
    original = auth_routes.current_user_id
    auth_routes.current_user_id = lambda req: None
    auth_routes.auth_ready = lambda req: True
    try:
        assert await b54_module.resolve_current_b54_canonical_session(request) is None
    finally:
        auth_routes.current_user_id = original


def test_helper_builds_no_browser_payload() -> None:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "apps" / "padiem-chat"))
    import app.b54_canonical_session as b54_module

    source = inspect.getsource(b54_module.resolve_current_b54_canonical_session)
    for forbidden in (
        "JSONResponse",
        "RedirectResponse",
        "set_cookie",
        "html",
        "template",
    ):
        assert forbidden not in source
    # No B54 identity field is copied into a response-shaped structure.
    assert "session_id" not in source
    assert "canonical_subject" not in source
    assert "tenant_id" not in source
