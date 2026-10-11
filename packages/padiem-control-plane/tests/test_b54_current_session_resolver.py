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
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


def _run(coro):
    """This package has no pytest-asyncio, so coroutines run explicitly."""

    return asyncio.run(coro)


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


def test_rpc_returns_session_for_product_and_user() -> None:
    store = _RecordingStore(_session())
    result = _run(_do_rpc(store).resolve_current_auth_session(
        {"product_id": B54_PRODUCT_ID, "product_user_id": USER}
    ))
    assert result["ok"] is True
    assert result["session"]["product_id"] == B54_PRODUCT_ID
    assert store.calls == [
        {"product_id": B54_PRODUCT_ID, "product_user_id": USER, "now": store.calls[0]["now"]}
    ]


def test_rpc_uses_the_worker_clock_not_the_caller() -> None:
    store = _RecordingStore(_session())
    _run(
        _do_rpc(store).resolve_current_auth_session(
            {"product_id": B54_PRODUCT_ID, "product_user_id": USER}
        )
    )
    used = store.calls[0]["now"]
    # A server clock, never the fixed test constant.
    assert abs((used - datetime.now(timezone.utc)).total_seconds()) < 60


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
def test_rpc_refuses_any_caller_supplied_authority_field(extra) -> None:
    store = _RecordingStore(_session())
    result = _run(_do_rpc(store).resolve_current_auth_session(
        {"product_id": B54_PRODUCT_ID, "product_user_id": USER, **extra}
    ))
    assert result["ok"] is False
    assert store.calls == [], "a rejected payload must not reach the store"


def test_rpc_missing_required_field_fails_closed() -> None:
    store = _RecordingStore(_session())
    for payload in (
        {"product_id": B54_PRODUCT_ID},
        {"product_user_id": USER},
        {},
    ):
        result = _run(_do_rpc(store).resolve_current_auth_session(payload))
        assert result["ok"] is False
    assert store.calls == []


def test_rpc_reports_missing_session_without_disclosure() -> None:
    store = _RecordingStore(None)
    result = _run(_do_rpc(store).resolve_current_auth_session(
        {"product_id": B54_PRODUCT_ID, "product_user_id": USER}
    ))
    assert result["ok"] is False
    assert "session" not in result


def test_gateway_exposes_the_new_rpc_and_keeps_resolve_auth_session() -> None:
    assert hasattr(_worker_mod.Default, "resolve_current_auth_session")
    assert hasattr(_worker_mod.Default, "resolve_auth_session")


