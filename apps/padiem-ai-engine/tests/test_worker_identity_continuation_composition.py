"""f88 regression: the canonical identity composition must resolve its durable
continuation authority (#2529).

Root cause of the f88 post-deploy HTTP 500 (non-JSON) on every route including
GET /internal/v1/health: ``worker_identity._continuation_store_for_env``
referenced ``CloudflareD1IdentityBoundContinuationStore`` without importing it
(the import was dropped by the Calendar promotion). With B14 bound AND the
``ENGINE_CONTINUATION`` D1 binding present (the production shape), every
request raised an uncaught ``NameError`` out of ``fetch()`` — the narrow
``except (TypeError, ValueError)`` never covered it — so the Workers runtime
answered 500 with a non-JSON body on all routes.

These tests are behavioral, not string-based: they import the real
``worker_identity`` composition root (Cloudflare-only modules stubbed, same
harness convention as ``test_tool_runtime_route_activation``) and execute the
composition with a production-shaped bound env. Re-dropping the import fails
``test_identity_module_resolves_the_continuation_store`` at attribute lookup
and fails the composition tests with ``NameError``.

Safety locks: no network, no secrets, no mutation, no D1 access (stub
bindings only).
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path
from typing import Any

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
# Prefer this checkout's Core package over any stale site-packages install so
# the composition under test matches the deployed bundle sources.
REPO_CORE = APP_ROOT.parent.parent / "packages" / "padiem-ai-core"
if REPO_CORE.is_dir() and str(REPO_CORE) not in sys.path:
    sys.path.insert(0, str(REPO_CORE))


class _FakeResponse:
    def __init__(self, body: Any = None, status: int = 200, headers: Any = None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(self, ctx: Any = None, env: Any = None) -> None:
        self.ctx = ctx
        self.env = env


def _workers_stub() -> types.ModuleType:
    module = types.ModuleType("workers")
    module.Request = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    module.Response = _FakeResponse  # type: ignore[attr-defined]
    module.WorkerEntrypoint = _FakeWorkerEntrypoint  # type: ignore[attr-defined]
    return module


class _StubD1Binding:
    """Minimal D1-like binding: only ``prepare`` is required by the store."""

    def prepare(self, _sql: str) -> "_StubD1Binding":
        return self


class _BoundEnv:
    """Production-shaped env: B14 bound AND continuation D1 bound (f88 shape)."""

    B14_SERVICE = object()
    ENGINE_CONTINUATION = _StubD1Binding()


class _UnboundEnv:
    B14_SERVICE = object()


@pytest.fixture(scope="module")
def identity_module():
    saved = {
        name: sys.modules.get(name) for name in ("workers", "worker", "worker_identity")
    }
    sys.modules["workers"] = _workers_stub()
    for name in ("worker", "worker_identity"):
        sys.modules.pop(name, None)
    try:
        yield importlib.import_module("worker_identity")
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def test_identity_module_resolves_the_continuation_store(identity_module) -> None:
    """The store name must be a real module attribute (i.e. imported)."""
    from app.continuation_d1 import CloudflareD1IdentityBoundContinuationStore

    assert (
        identity_module.CloudflareD1IdentityBoundContinuationStore
        is CloudflareD1IdentityBoundContinuationStore
    )


def test_continuation_store_resolves_with_bound_d1(identity_module) -> None:
    store = identity_module._continuation_store_for_env(_BoundEnv())
    assert store is not None


def test_continuation_store_absent_without_binding(identity_module) -> None:
    assert identity_module._continuation_store_for_env(_UnboundEnv()) is None


def test_identity_composition_succeeds_with_b14_and_continuation_bound(
    identity_module,
) -> None:
    """f88 regression: bound-env composition must not raise (was NameError)."""
    services = asyncio.run(identity_module._engine_services_for_env(_BoundEnv()))
    assert services.orchestration is not None
    health = services.completed.health()
    assert health.status_code == 200
    assert health.body["status"] == "ok"


def test_identity_composition_succeeds_without_continuation_binding(
    identity_module,
) -> None:
    services = asyncio.run(identity_module._engine_services_for_env(_UnboundEnv()))
    health = services.completed.health()
    assert health.status_code == 200
