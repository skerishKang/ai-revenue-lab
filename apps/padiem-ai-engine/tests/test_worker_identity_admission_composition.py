"""Canonical A7 Worker composition regression tests (#3298).

These tests are network-free. They prove that once B14 execution is available,
canonical orchestration is always admission-bound: a missing Control Plane
admission binding produces a None adapter and fails closed rather than falling
back to the unguarded canonical idempotency service.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import tomllib
import types
from pathlib import Path
from typing import Any

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
REPO_CORE = APP_ROOT.parent.parent / "packages" / "padiem-ai-core"
if REPO_CORE.is_dir() and str(REPO_CORE) not in sys.path:
    sys.path.insert(0, str(REPO_CORE))


class _FakeResponse:
    def __init__(
        self,
        body: Any = None,
        status: int = 200,
        headers: Any = None,
    ) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(
        self,
        ctx: Any = None,
        env: Any = None,
    ) -> None:
        self.ctx = ctx
        self.env = env


def _workers_stub() -> types.ModuleType:
    module = types.ModuleType("workers")
    module.Request = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    module.Response = _FakeResponse  # type: ignore[attr-defined]
    module.WorkerEntrypoint = _FakeWorkerEntrypoint  # type: ignore[attr-defined]
    return module


class _AdmissionBinding:
    async def fetch_entitlement_snapshot(
        self,
        payload,
    ):
        del payload
        raise AssertionError(
            "composition test must not call authority"
        )

    async def reserve_usage(
        self,
        payload,
    ):
        del payload
        raise AssertionError(
            "composition test must not call authority"
        )

    async def record_usage(
        self,
        payload,
    ):
        del payload
        raise AssertionError(
            "composition test must not call authority"
        )


class _BoundAdmissionEnv:
    B14_SERVICE = object()
    CONTROL_PLANE_ENGINE_ADMISSION = _AdmissionBinding()


class _MissingAdmissionEnv:
    B14_SERVICE = object()


class _NoB14Env:
    CONTROL_PLANE_ENGINE_ADMISSION = _AdmissionBinding()


@pytest.fixture(scope="module")
def identity_module():
    saved = {
        name: sys.modules.get(name)
        for name in ("workers", "worker", "worker_identity")
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


def _payload() -> dict[str, object]:
    return {
        "app_id": "b62",
        "agent": {
            "id": "agent:padiem:a7_test@1",
            "title": "A7 test",
            "description": "A7 composition test",
            "system_instruction": "No dispatch expected",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 128,
            "required_capabilities": [],
            "model_policy": {"model": "test/route"},
        },
        "messages": [
            {
                "role": "user",
                "content": "prove fail closed",
            }
        ],
        "trace_id": "trace_a7_composition",
        "execution_context": {
            "trace_id": "trace_a7_composition",
        },
        "subject_id": "subject:padiem:user:a7",
        "max_retries": 0,
        "require_evidence": False,
        "require_verification": False,
    }


def test_b14_bound_composition_uses_admission_bound_service_with_real_adapter(
    identity_module,
) -> None:
    from app.execution_admission_service import (
        AdmissionBoundOrchestrationEngineService,
    )
    from app.tenant_auth import (
        ControlPlaneTenantAdmissionAdapter,
    )

    services = asyncio.run(
        identity_module._engine_services_for_env(
            _BoundAdmissionEnv()
        )
    )

    assert isinstance(
        services.orchestration,
        AdmissionBoundOrchestrationEngineService,
    )
    assert isinstance(
        services.orchestration._admission_adapter,
        ControlPlaneTenantAdmissionAdapter,
    )


def test_missing_admission_binding_never_falls_back_to_unguarded_orchestration(
    identity_module,
) -> None:
    from app.execution_admission_service import (
        AdmissionBoundOrchestrationEngineService,
    )

    services = asyncio.run(
        identity_module._engine_services_for_env(
            _MissingAdmissionEnv()
        )
    )

    assert isinstance(
        services.orchestration,
        AdmissionBoundOrchestrationEngineService,
    )
    assert (
        services.orchestration._admission_adapter
        is None
    )

    response = asyncio.run(
        services.orchestration.orchestrate_payload(
            _payload()
        )
    )
    assert response.status_code == 503
    assert (
        response.body["error"]["code"]
        == "entitlement_unavailable"
    )


def test_no_b14_binding_remains_non_executable(
    identity_module,
) -> None:
    from app.orchestration_idempotency_service import (
        CanonicalIdempotencyOrchestrationEngineService,
    )

    services = asyncio.run(
        identity_module._engine_services_for_env(
            _NoB14Env()
        )
    )
    assert isinstance(
        services.orchestration,
        CanonicalIdempotencyOrchestrationEngineService,
    )
    assert (
        services.orchestration._b14_service_bound
        is False
    )


def test_engine_source_declares_exact_private_admission_service_binding() -> None:
    config = tomllib.loads(
        (
            APP_ROOT / "wrangler.toml"
        ).read_text(encoding="utf-8")
    )
    services = {
        item["binding"]: item["service"]
        for item in config["services"]
    }

    assert services[
        "CONTROL_PLANE_ENGINE_ADMISSION"
    ] == "padiem-control-plane-engine-admission"


def test_e7_capability_manifest_stays_deferred_until_live_evidence() -> None:
    from app.capability_manifest import (
        CapabilityState,
        current_capability_manifest,
    )

    manifest = current_capability_manifest()
    feature = next(
        item
        for item in manifest.capabilities
        if item.id
        == "tenant_entitlement_usage_admission"
    )
    assert feature.state is CapabilityState.DEFERRED
