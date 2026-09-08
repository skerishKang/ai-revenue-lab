"""ACT-2 route-activation proof for the Engine Tool runtime (#2010).

Locks the source-level activation slice: the Tool routes are admitted by both
Engine composition roots, the legacy composition carries an explicitly
unconfigured binding resolver, and every unbound request fails closed with a
machine-readable 503 ``tool_runtime_unavailable`` — never a 404 and never a
provider call. Harness conventions mirror ``test_multimodal_worker_boundary``.
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

CALLER_ID = "act2-route-caller"
CALLER_SECRET = "act2-route-secret-0123456789abcdef-0123456789abcdef"
ALLOWED_APP = "b62"
TOOL_EXECUTE_PATH = "/internal/v1/tools/execute"
TOOL_RESUME_PATH = "/internal/v1/tools/resume"
TOOL_CANCEL_PATH = "/internal/v1/tools/cancel"


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
def entrypoint_modules():
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


def _fetch(module: Any, env: Any, request: Any) -> Any:
    return asyncio.run(module.Default(ctx=None, env=env).fetch(request))


def _body(response: Any) -> dict:
    return json.loads(str(response.body))


def _execute_body() -> bytes:
    return json.dumps(
        {
            "app_id": ALLOWED_APP,
            "agent_id": "agent:padiem:claw_mail_reader@1",
            "tool_id": "tool:google:gmail.search_messages@1",
            "arguments": {},
        }
    ).encode("utf-8")


# --- source-level route admission --------------------------------------------


def test_tool_routes_are_admitted_in_both_composition_roots() -> None:
    legacy_source = (APP_ROOT / "worker.py").read_text(encoding="utf-8")
    identity_source = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")
    for source in (legacy_source, identity_source):
        assert "TOOL_EXECUTE_PATH" in source
        assert "TOOL_RESUME_PATH" in source
        assert "TOOL_CANCEL_PATH" in source


def test_legacy_composition_carries_explicit_unconfigured_resolver(
    entrypoint_modules,
) -> None:
    """The route is admitted, but no trusted Gmail authority is implied."""

    from app.tool_execution_service import ToolExecutionEngineService

    legacy, _identity = entrypoint_modules

    for env in (_identity_env(), _identity_env(B14_SERVICE=object())):
        services = asyncio.run(legacy._engine_services_for_env(env))
        assert isinstance(services.tool_execution, ToolExecutionEngineService)
        assert services.tool_execution._tool_binding_resolver is None


# --- fetch-level fail-closed behaviour ---------------------------------------


@pytest.mark.parametrize("b14_bound", [False, True])
def test_execute_route_fails_closed_through_legacy_fetch(
    entrypoint_modules, b14_bound: bool
) -> None:
    legacy, _identity = entrypoint_modules
    env = _identity_env(**({"B14_SERVICE": object()} if b14_bound else {}))
    response = _fetch(legacy, env, _Request(TOOL_EXECUTE_PATH, body=_execute_body()))
    assert response.status == 503
    assert _body(response)["error"]["code"] == "tool_runtime_unavailable"


@pytest.mark.parametrize("b14_bound", [False, True])
def test_execute_route_fails_closed_through_canonical_fetch(
    entrypoint_modules, b14_bound: bool
) -> None:
    _legacy, identity = entrypoint_modules
    env = _identity_env(**({"B14_SERVICE": object()} if b14_bound else {}))
    response = _fetch(identity, env, _Request(TOOL_EXECUTE_PATH, body=_execute_body()))
    assert response.status == 503
    assert _body(response)["error"]["code"] == "tool_runtime_unavailable"


@pytest.mark.parametrize("path", [TOOL_EXECUTE_PATH, TOOL_RESUME_PATH, TOOL_CANCEL_PATH])
def test_tool_routes_are_never_404_after_activation(
    entrypoint_modules, path: str
) -> None:
    """Admission proof: every Tool route reaches Engine-owned handling."""

    legacy, identity = entrypoint_modules
    for module in (legacy, identity):
        response = _fetch(module, _identity_env(), _Request(path, body=_execute_body()))
        assert response.status != 404
        assert _body(response)["error"]["code"] != "not_found"


@pytest.mark.parametrize("path", [TOOL_EXECUTE_PATH, TOOL_RESUME_PATH, TOOL_CANCEL_PATH])
def test_unauthenticated_tool_requests_reject_before_composition(
    entrypoint_modules, path: str
) -> None:
    legacy, identity = entrypoint_modules
    for module in (legacy, identity):
        response = _fetch(
            module,
            _identity_env(),
            _Request(path, body=_execute_body(), authenticated=False),
        )
        assert response.status == 401
        assert _body(response)["error"]["code"] == "service_authentication_failed"
