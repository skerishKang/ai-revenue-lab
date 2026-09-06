"""Fetch-level boundary tests for the #1964 idempotency replay route (CTO R3).

Exercises the real ``worker_identity.Default`` fetch entrypoint with the
Cloudflare ``workers`` runtime surface stubbed — the same canonical pattern as
``test_engine_canonical_composition_runtime.py`` — and proves the replay route
sits behind the service-identity boundary and fails closed without the
trusted durable adapter:

- unauthenticated request -> 401 ``service_authentication_failed``
- authenticated request with no ``ENGINE_IDEMPOTENCY`` binding -> 503
  ``idempotency_unavailable`` (never a process-local store)

The B14 stub binding is a bare ``object()``: neither test reaches a B14 call,
because authentication (401) and the unbound-adapter composition (503) both
resolve strictly before any B14 invocation.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

CALLER_ID = "r2a-test-caller"
CALLER_SECRET = "r2a-test-secret-0123456789abcdef-0123456789abcdef"  # >=32 bytes per service_identity contract
ALLOWED_APP = "b62"


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


@pytest.fixture(scope="module")
def identity_modules():
    saved = {
        name: sys.modules.get(name)
        for name in ("workers", "worker", "worker_identity")
    }
    sys.modules["workers"] = _workers_stub()
    for name in ("worker", "worker_identity"):
        sys.modules.pop(name, None)
    try:
        identity = importlib.import_module("worker_identity")
        legacy = importlib.import_module("worker")
        yield legacy, identity
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class _Env:
    def __init__(self, **attrs: Any) -> None:
        self.__dict__.update(attrs)


class _Request:
    def __init__(
        self,
        path: str,
        *,
        method: str = "POST",
        body: bytes = b"{}",
        authenticated: bool = True,
    ) -> None:
        self.url = f"https://engine.internal{path}"
        self.method = method
        headers: dict[str, str] = {"content-type": "application/json"}
        if authenticated:
            headers["x-padiem-engine-caller"] = CALLER_ID
            headers["x-padiem-engine-credential"] = CALLER_SECRET
        self.headers = headers
        self._text = body.decode("utf-8")

    async def text(self) -> str:
        return self._text


def _identity_env(**extra: Any) -> _Env:
    return _Env(
        PADIEM_ENGINE_CALLER_ID=CALLER_ID,
        PADIEM_ENGINE_CALLER_SECRET=CALLER_SECRET,
        PADIEM_ENGINE_ALLOWED_APPS=ALLOWED_APP,
        **extra,
    )


def _fetch(identity: Any, env: Any, request: Any) -> Any:
    return asyncio.run(identity.Default(ctx=None, env=env).fetch(request))


def _body(response: Any) -> dict:
    return json.loads(str(response.body))


def _replay_body() -> bytes:
    return json.dumps(
        {
            "app_id": ALLOWED_APP,
            "idempotency_key": "exec_route_probe",
            "request_fingerprint": "f" * 64,
        }
    ).encode("utf-8")


def test_replay_route_requires_service_identity(identity_modules) -> None:
    _legacy, identity = identity_modules
    from app.idempotency_replay_service import IDEMPOTENCY_COMPLETED_REPLAY_PATH

    env = _identity_env(B14_SERVICE=object())
    request = _Request(
        IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        body=_replay_body(),
        authenticated=False,
    )

    response = _fetch(identity, env, request)

    assert response.status == 401
    assert _body(response)["error"]["code"] == "service_authentication_failed"


def test_replay_route_fails_closed_without_durable_adapter(identity_modules) -> None:
    _legacy, identity = identity_modules
    from app.idempotency_replay_service import IDEMPOTENCY_COMPLETED_REPLAY_PATH

    # ENGINE_IDEMPOTENCY is intentionally absent: the composition must never
    # install a process-local store, so the route fails closed at the seam.
    env = _identity_env(B14_SERVICE=object())
    request = _Request(
        IDEMPOTENCY_COMPLETED_REPLAY_PATH,
        body=_replay_body(),
        authenticated=True,
    )

    response = _fetch(identity, env, request)

    assert response.status == 503
    assert _body(response)["error"]["code"] == "idempotency_unavailable"
