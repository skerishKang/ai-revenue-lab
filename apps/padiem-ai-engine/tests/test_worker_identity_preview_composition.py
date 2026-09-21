"""Identity-worker preview composition tests (#2786 Stage 11-C M3-2).

The deployed entrypoint is ``worker_identity.py`` (wrangler ``main``), so the
preview lane has to be reachable from *that* composition while the Production
authority it already passes in (bound resolver, approval verifier, continuation
store) stays byte-for-byte intact for every unmarked isolate.
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

from app.agent_preview_authority import (  # noqa: E402
    DEPLOY_ENV_NAME,
    ENABLE_ENV_NAME,
    PREVIEW_ENABLE_MARKER,
    PREVIEW_RUNTIME_TOOL_ID,
    build_preview_agent_lane,
    preview_task_payload,
)
from app.capability_manifest import (  # noqa: E402
    CapabilityState,
    current_capability_manifest,
    set_posture_overrides,
)

PREVIEW_ENV = {
    DEPLOY_ENV_NAME: "preview",
    ENABLE_ENV_NAME: PREVIEW_ENABLE_MARKER,
}


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
def identity_worker():
    saved = {name: sys.modules.get(name) for name in ("workers", "worker", "worker_identity")}
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


@pytest.fixture(autouse=True)
def _clean_isolate_state():
    set_posture_overrides(None)
    yield
    set_posture_overrides(None)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _no_runtime(_app_id: str) -> Any:
    raise AssertionError("the preview pilot must never build a provider runtime")


class _Verifier:
    def verify(self, *_args: Any, **_kwargs: Any) -> bool:
        return True


class _ProductionAuthoritySentinel:
    """Stand-in for the real bound resolver the identity composition passes in."""

    def __call__(self, _app_id: str) -> Any:  # pragma: no cover - never resolved
        raise AssertionError("the regression test never resolves a production binding")


class _ContinuationStore:
    """Minimal store surface the coordinator validates at construction."""

    def issue(self, *_args: Any, **_kwargs: Any) -> Any:  # pragma: no cover - stub
        raise AssertionError("the regression test never issues a continuation")

    resolve = claim = commit = release = issue


# --- production regression -------------------------------------------------


def test_factory_passes_the_production_authority_through_untouched(
    identity_worker: Any,
) -> None:
    sentinel = _ProductionAuthoritySentinel()
    verifier = _Verifier()
    store = _ContinuationStore()
    adapter = object()

    service = identity_worker._agent_skill_service_for_env(
        {},
        runtime_factory=_no_runtime,
        binding_resolver=sentinel,
        idempotency_adapter=adapter,
        approval_decision_verifier=verifier,
        continuation_store=store,
    )

    assert service._binding_resolver is sentinel
    assert service._idempotency_adapter is adapter
    assert service._continuation._verifier is verifier
    assert service._continuation._store is store


def test_entrypoint_stays_fail_closed_without_the_marker(identity_worker: Any) -> None:
    services = _run(identity_worker._engine_services_for_env({}))

    response = _run(services.agent_skill.run_payload(preview_task_payload()))

    assert response.status_code == 503
    assert response.body["error"]["code"] == "agent_skill_runtime_unavailable"


def test_entrypoint_refuses_a_production_marker(identity_worker: Any) -> None:
    services = _run(
        identity_worker._engine_services_for_env(
            {DEPLOY_ENV_NAME: "production", ENABLE_ENV_NAME: PREVIEW_ENABLE_MARKER}
        )
    )

    response = _run(services.agent_skill.run_payload(preview_task_payload()))

    assert response.status_code == 503
    assert response.body["error"]["code"] == "agent_skill_runtime_unavailable"


# --- preview activation ---------------------------------------------------


def test_factory_composes_the_preview_lane_when_marked(identity_worker: Any) -> None:
    service = identity_worker._agent_skill_service_for_env(
        PREVIEW_ENV,
        runtime_factory=_no_runtime,
        binding_resolver=object(),
    )

    response = _run(service.run_payload(preview_task_payload()))

    assert response.status_code == 200
    assert response.body["ok"] is True
    assert response.body["agent_skill"]["resolved_tool_ids"] == [PREVIEW_RUNTIME_TOOL_ID]


def test_entrypoint_composes_the_preview_lane(identity_worker: Any) -> None:
    services = _run(identity_worker._engine_services_for_env(PREVIEW_ENV))

    response = _run(services.agent_skill.run_payload(preview_task_payload()))

    assert response.status_code == 200
    assert response.body["agent_skill"]["execution_state"] == "completed"


# --- capability separation ------------------------------------------------


def test_capability_override_is_isolate_scoped(identity_worker: Any) -> None:
    _run(identity_worker._engine_services_for_env(PREVIEW_ENV))
    assert (
        current_capability_manifest().capability_state("agent_skill_runtime")
        is CapabilityState.AVAILABLE
    )

    _run(identity_worker._engine_services_for_env({}))
    assert (
        current_capability_manifest().capability_state("agent_skill_runtime")
        is CapabilityState.DEFERRED
    )


def test_production_capability_states_are_untouched(identity_worker: Any) -> None:
    before = current_capability_manifest().to_public_dict()
    _run(identity_worker._engine_services_for_env({}))
    after = current_capability_manifest().to_public_dict()

    assert after == before
    assert (
        current_capability_manifest().capability_state("agent_skill_runtime")
        is CapabilityState.DEFERRED
    )


# --- provider / user data / secret counters -------------------------------


def test_provider_calls_and_user_data_stay_zero() -> None:
    lane = build_preview_agent_lane(PREVIEW_ENV)
    assert lane is not None

    hostile = dict(PREVIEW_ENV)
    hostile.update(
        {
            "CLOUDFLARE_API_TOKEN": "not-a-real-token",
            "PADIEM_ENGINE_CALLER_SECRET": "not-a-real-secret",
            "ENGINE_CONNECTOR_GRANTS": "not-a-real-binding",
            "ENGINE_IDEMPOTENCY": "not-a-real-binding",
        }
    )
    hostile_lane = build_preview_agent_lane(hostile)
    assert hostile_lane is not None
    # No extra environment value changes the synthetic identity or the tool set.
    assert hostile_lane.binding.app_id == lane.binding.app_id
    assert hostile_lane.binding.subject_id == lane.binding.subject_id

    for _ in range(2):
        response = _run(hostile_lane.service.run_payload(preview_task_payload()))
        assert response.status_code == 200

    assert hostile_lane.provider_runtime_calls == 0
    assert hostile_lane.tool_calls == 2
