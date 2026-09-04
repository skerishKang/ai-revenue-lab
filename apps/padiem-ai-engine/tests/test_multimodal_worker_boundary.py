"""Canonical-entrypoint boundary proof for Engine E5A (#1750).

Locks the composition-root invariant that adding the trusted multimodal route
leaves every pre-existing Engine route family unchanged and never opens a
browser/public surface.
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

CALLER_ID = "e5-boundary-caller"
CALLER_SECRET = "e5-boundary-secret-0123456789abcdef-0123456789abcdef"
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
        name: sys.modules.get(name) for name in ("workers", "worker", "worker_identity")
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


def _execute_body() -> bytes:
    return json.dumps({"app_id": ALLOWED_APP}).encode("utf-8")


@pytest.mark.parametrize(
    ("path", "expected_code"),
    [
        ("/internal/v1/execute", "b14_service_unavailable"),
        ("/internal/v1/stream", "b14_service_unavailable"),
        ("/internal/v1/orchestrate", "b14_service_unavailable"),
        ("/internal/v1/research", "b14_service_unavailable"),
        ("/internal/v1/memory/retrieve", "memory_binding_unavailable"),
        ("/internal/v1/memory/write", "memory_write_binding_unavailable"),
        ("/internal/v1/agent-skill/run", "agent_skill_runtime_unavailable"),
    ],
)
def test_canonical_entrypoint_preserves_existing_route_behavior(
    identity_modules, path: str, expected_code: str
) -> None:
    """E5A must not alter execute/stream/orchestration/research/memory/agent-skill."""

    _legacy, identity = identity_modules

    response = _fetch(identity, _identity_env(), _Request(path, body=_execute_body()))

    assert response.status == 503
    assert _body(response)["error"]["code"] == expected_code


def test_canonical_entrypoint_keeps_health_public_and_existing_auth_boundary(
    identity_modules,
) -> None:
    from app.service import HEALTH_PATH

    _legacy, identity = identity_modules

    health = _fetch(identity, _Env(), _Request(HEALTH_PATH, method="GET"))
    assert health.status == 200
    assert _body(health)["service_identity"] == "required_for_all_non_health_routes"

    unauthorized = _fetch(
        identity,
        _identity_env(),
        _Request("/internal/v1/execute", body=_execute_body(), authenticated=False),
    )
    assert unauthorized.status == 401
    assert _body(unauthorized)["error"]["code"] == "service_authentication_failed"


def test_multimodal_route_is_not_a_public_or_browser_surface(identity_modules) -> None:
    from app.contract_manifest import EngineFeatureState, current_engine_contract_manifest

    _legacy, identity = identity_modules

    manifest = current_engine_contract_manifest()
    assert manifest.feature_state("public_browser_api") is EngineFeatureState.UNAVAILABLE

    identity_source = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")
    assert "Access-Control-Allow-Origin" not in identity_source
    assert "workers.dev" not in identity_source
    assert "MULTIMODAL_EXECUTE_PATH" in identity_source
    assert "_authenticate_non_health_request" in identity_source


def test_legacy_worker_is_not_widened_by_e5a(identity_modules) -> None:
    legacy, _identity = identity_modules
    legacy_source = (APP_ROOT / "worker.py").read_text(encoding="utf-8")

    assert "multimodal" not in legacy_source
    assert "MultimodalAttachmentEngineService" not in legacy_source
    assert "MULTIMODAL_EXECUTE_PATH" not in legacy_source

    assert legacy._engine_services_for_env(_identity_env()).multimodal is None
