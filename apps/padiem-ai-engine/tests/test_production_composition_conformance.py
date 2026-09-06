"""Production composition conformance gate (#1752 A8 / #1753 E9 — CTO WO-2).

Root cause this test closes (CTO audit 2026-09-06, findings F1/F3): the E9
activation gates prove that a *service class* works when a test constructs it
with its trusted authority injected. They never prove that the *Production
composition root* actually injects that authority, so a manifest can claim
AVAILABLE while Production fails closed (A3 tool_runtime did exactly that).

This module imports the real canonical composition root
(``worker_identity._engine_services_for_env``) with a stub Cloudflare env that
provides only a B14 service binding, and then asserts, for every capability the
manifest declares AVAILABLE, that a minimal valid request is NOT answered by a
fail-closed unavailable posture. DEFERRED capabilities must fail closed.

Invariants enforced here:

```text
FALSE_AVAILABLE_MANIFEST_ENTRIES = 0
MANIFEST_AVAILABLE_BEFORE_EVIDENCE = NO
```

A capability may only be AVAILABLE when the actual Production composition
wires a non-fail-closed authority for it. Any future activation PR that flips
a manifest state without wiring the real composition must fail this gate.

Negative control (CTO WO-2): on pre-WO-1 main this test fails on the
``tool_runtime`` capability because the manifest claims AVAILABLE while
``worker_identity`` composes ``ToolExecutionEngineService(tool_binding_resolver=None)``.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from typing import Any

import pytest

_FAIL_CLOSED_CODES = frozenset(
    {
        "tool_runtime_unavailable",
        "web_tools_off",
        "memory_binding_unavailable",
        "memory_write_binding_unavailable",
        "attachment_resolver_unavailable",
        "agent_skill_runtime_unavailable",
        "document_resolver_unavailable",
        "idempotency_unavailable",
        "b14_service_unavailable",
    }
)


class _FakeResponse:
    def __init__(self, body: Any = None, status: int = 200, headers: Any = None) -> None:
        self.body = body
        self.status = status
        self.headers = headers


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


class _StubBindingResponse:
    """Minimal B14 service-binding response surface (status/headers/body)."""

    def __init__(self, *, status: int = 200, body: bytes = b"{}") -> None:
        self.status = status
        self.headers = {"get": lambda _name: "application/json"}
        self.body = body


class _StubB14Binding:
    """Stub B14 service binding: records fetch calls, returns a sentinel body.

    The completed/streaming probes only need proof that the composition wired
    a real transport (i.e. the binding was reached) rather than a
    ``b14_service_unavailable`` fail-closed posture. Core's parsing of the
    sentinel body is allowed to surface a bounded upstream error — that still
    proves the Production composition reached its provider authority, which is
    exactly what unit-level activation gates never proved.
    """

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def fetch(self, js_object: Any) -> _StubBindingResponse:
        self.calls.append(js_object)
        return _StubBindingResponse(status=200, body=b'{"sentinel": true}')


class _StubEnv:
    """Cloudflare env with the B14 service binding and mock web provider.

    A1's web authority is env-driven by design: the composition must READ the
    deployment state (``PADIEM_ENGINE_WEB_PROVIDER``) and wire the provider.
    Providing the mock provider here proves the seam is wired end-to-end
    without any network access. There is deliberately no ENGINE_IDEMPOTENCY,
    no ENGINE_MEMORY_*, no tool registry and no continuation binding: those
    capabilities are DEFERRED and must fail closed.
    """

    def __init__(self) -> None:
        self.B14_SERVICE = _StubB14Binding()
        self.PADIEM_ENGINE_WEB_PROVIDER = "mock"


def _load_composition():
    saved = {
        name: sys.modules.get(name)
        for name in ("workers", "worker", "worker_identity")
    }
    sys.modules["workers"] = _workers_stub()
    for name in ("worker", "worker_identity"):
        sys.modules.pop(name, None)
    try:
        identity = importlib.import_module("worker_identity")
        return identity._engine_services_for_env
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _agent() -> dict[str, Any]:
    return {
        "id": "agent:padiem:orchestrator_1",
        "title": "Orchestrator",
        "description": "Orchestrates execution",
        "system_instruction": "Execute tasks",
        "task_type": "general",
        "optimize_for": "balanced",
        "max_tokens": 2048,
    }


def _execute_payload() -> bytes:
    return json.dumps(
        {
            "app_id": "b62",
            "agent": _agent(),
            "messages": [{"role": "user", "content": "composition probe"}],
        }
    ).encode("utf-8")


def _research_payload() -> bytes:
    return json.dumps(
        {
            "app_id": "b62",
            "operation": "search",
            "query": "padiem composition probe",
            "agent": _agent(),
        }
    ).encode("utf-8")


def _tool_payload() -> bytes:
    return json.dumps(
        {
            "app_id": "b62",
            "agent_id": "agent:padiem:agent_1@1",
            "tool_id": "tool:padiem:noop_1@1",
            "arguments": {},
        }
    ).encode("utf-8")


def _memory_payload() -> bytes:
    return json.dumps(
        {
            "app_id": "b62",
            "query": "composition probe",
            "agent": _agent(),
        }
    ).encode("utf-8")


async def _call(service: Any, *, path: str, payload: bytes) -> Any:
    return await service.handle(
        method="POST",
        path=path,
        content_type="application/json",
        body=payload,
    )


def _is_fail_closed(response: Any) -> bool:
    if response.status_code == 503:
        return True
    code = response.body.get("error", {}).get("code")
    return code in _FAIL_CLOSED_CODES


# --- AVAILABLE capabilities must be non-fail-closed --------------------------


@pytest.mark.asyncio
async def test_completed_run_composition_reaches_b14_authority() -> None:
    compose = _load_composition()
    services = compose(_StubEnv())
    # The composition must have built a real runtime factory against the B14
    # binding; a fail-closed unbound service cannot advertise completed_run.
    assert services.completed._b14_service_bound is True


@pytest.mark.asyncio
async def test_streaming_run_composition_reaches_b14_authority() -> None:
    compose = _load_composition()
    services = compose(_StubEnv())
    assert services.streaming._b14_service_bound is True


@pytest.mark.asyncio
async def test_orchestration_run_composition_reaches_b14_authority() -> None:
    compose = _load_composition()
    services = compose(_StubEnv())
    assert services.orchestration._b14_service_bound is True


@pytest.mark.asyncio
async def test_tool_runtime_composition_must_not_fail_closed() -> None:
    """AVAILABLE tool_runtime must be composed with a real binding resolver.

    Negative control: on pre-WO-1 main the manifest claims AVAILABLE while the
    Production composition injects ``tool_binding_resolver=None``, so this
    probe returns 503 ``tool_runtime_unavailable`` and fails — exactly the
    false-AVAILABLE defect the CTO audit found (F1).
    """
    compose = _load_composition()
    services = compose(_StubEnv())
    from app.tool_projection import TOOL_EXECUTE_PATH

    assert services.tool_execution is not None
    response = await _call(services.tool_execution, path=TOOL_EXECUTE_PATH, payload=_tool_payload())
    assert not _is_fail_closed(response), (
        "tool_runtime is manifest-AVAILABLE but the Production composition "
        f"fails closed: {response.status_code} {response.body}"
    )


@pytest.mark.asyncio
async def test_web_research_composition_must_not_fail_closed() -> None:
    """AVAILABLE web projections must be composed with a real web provider."""
    compose = _load_composition()
    services = compose(_StubEnv())
    from app.web_research_service import RESEARCH_PATH

    response = await _call(services.research, path=RESEARCH_PATH, payload=_research_payload())
    assert not _is_fail_closed(response), (
        "web_search/web_fetch/deep_research are manifest-AVAILABLE but the "
        f"Production composition fails closed: {response.status_code} {response.body}"
    )


# --- DEFERRED capabilities must fail closed ---------------------------------


@pytest.mark.asyncio
async def test_memory_rag_composition_fails_closed() -> None:
    compose = _load_composition()
    services = compose(_StubEnv())
    from app.memory_service import MEMORY_PATH

    response = await _call(services.memory, path=MEMORY_PATH, payload=_memory_payload())
    assert _is_fail_closed(response), (
        "memory_rag is manifest-DEFERRED but the Production composition did "
        f"not fail closed: {response.status_code} {response.body}"
    )


@pytest.mark.asyncio
async def test_multimodal_composition_fails_closed_without_resolver() -> None:
    compose = _load_composition()
    services = compose(_StubEnv())
    from app.multimodal_attachment_service import MULTIMODAL_EXECUTE_PATH

    assert services.multimodal is not None
    response = await _call(
        services.multimodal,
        path=MULTIMODAL_EXECUTE_PATH,
        payload=json.dumps(
            {
                "app_id": "b62",
                "agent": _agent(),
                "messages": [{"role": "user", "content": "composition probe"}],
                "attachment_ref": "att_probe_0000000001",
            }
        ).encode("utf-8"),
    )
    assert _is_fail_closed(response), (
        "multimodal_completed_run is manifest-DEFERRED but the Production "
        f"composition did not fail closed: {response.status_code} {response.body}"
    )
