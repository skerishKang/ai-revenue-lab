"""A7 unscoped Production probe: the request must be contract-valid (#3298 follow-up).

The A7 unscoped smoke exists to prove ONE thing: a contract-valid
orchestration request that carries no authenticated USER subject reaches the A7
admission seam and is rejected there, before Core/provider dispatch.

It silently stopped proving that. The probe's ``agent.id`` carried an ``@1``
version suffix, which belongs to the AgentDefinition / ``agent_plan`` grammar
but NOT to the Padiem AI Core ``AgentProfile`` identifier contract. Ordinary
request validation therefore rejected the probe with ``400 invalid_request``
*before* admission was consulted, and the live smoke failed with
``A7_UNSCOPED_ADMISSION_SMOKE=FAIL_UNEXPECTED_VERDICT``.

These tests lock the seam offline so a future payload edit cannot quietly
turn the A7 probe back into a parser-failure test:

- the probe agent id satisfies the Core AgentProfile contract;
- the probe passes ordinary request validation (so it is contract-valid);
- ``subject_id`` is still deliberately absent;
- the admission seam IS reached, unscoped, for capability ``orchestration.run``;
- the Core runtime / provider dispatch seam is NEVER reached.
"""

from __future__ import annotations

import copy
import importlib.util
import pathlib
from typing import Any

import pytest

from padiem_ai_core.contracts import AgentProfile

from app.execution_admission_service import (
    AdmissionBoundOrchestrationEngineService,
    _run_admission_request,
)
from app.orchestration_idempotency_service import _initial_execution_fingerprint
from app.orchestration_service import _parse_orchestration_options
from app.service import build_execution_request

ENGINE_ROOT = pathlib.Path(__file__).resolve().parents[1]
SMOKE_PATH = ENGINE_ROOT / "scripts" / "a7_unscoped_admission_production_smoke.py"


def _smoke_module():
    spec = importlib.util.spec_from_file_location("a7_unscoped_smoke_under_test", SMOKE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload() -> dict[str, Any]:
    return _smoke_module()._payload()


_EXECUTION_FIELDS = (
    "app_id",
    "agent",
    "messages",
    "session_id",
    "additional_system_context",
    "trace_id",
    "execution_context",
)


def _execution_subset(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: payload[k] for k in _EXECUTION_FIELDS if k in payload}


def test_probe_agent_id_satisfies_the_core_agent_profile_contract() -> None:
    agent = _payload()["agent"]
    # The Core AgentProfile identifier contract is `agent:<owner>:<name>`; the
    # "@version" suffix is the AgentDefinition/agent_plan grammar and is NOT
    # valid here. This is the exact defect that broke the Production smoke.
    assert "@" not in agent["id"]
    profile = AgentProfile(
        id=agent["id"],
        title=agent["title"],
        description=agent["description"],
        system_instruction=agent["system_instruction"],
        task_type=agent["task_type"],
        optimize_for=agent["optimize_for"],
        max_tokens=agent["max_tokens"],
        required_capabilities=tuple(agent["required_capabilities"]),
        model_policy=dict(agent["model_policy"]),
    )
    assert profile.id == agent["id"]


def test_probe_is_contract_valid_for_ordinary_orchestration_validation() -> None:
    payload = _payload()
    app_id, exec_req, _ = build_execution_request(_execution_subset(payload))
    assert app_id == "b54-padiem-claw"
    assert exec_req.agent.id == payload["agent"]["id"]
    # An explicit, non-empty model route is required by the wire contract; the
    # probe keeps one so no implicit b14/auto fallback can ever be exercised.
    model = payload["agent"]["model_policy"]["model"]
    assert isinstance(model, str) and model.strip()


def test_probe_omits_the_authenticated_user_subject() -> None:
    payload = _payload()
    assert "subject_id" not in payload
    _, _, _, subject_id, _, _ = _parse_orchestration_options(payload)
    assert subject_id is None


def test_probe_reaches_the_a7_admission_seam_unscoped() -> None:
    payload = _payload()
    # A None fingerprint previously meant the probe never built an admission
    # request at all and silently degraded into the loose (non-admission) path.
    assert _initial_execution_fingerprint(payload) is not None
    admission_request = _run_admission_request(copy.deepcopy(payload))
    assert admission_request is not None, "probe must reach A7 admission"
    assert admission_request.subject_id is None
    assert admission_request.capability == "orchestration.run"
    assert admission_request.app_id == "b54-padiem-claw"


async def test_probe_never_reaches_the_core_or_provider_dispatch_seam() -> None:
    payload = _payload()

    class _RecordingAdmissionAdapter:
        def __init__(self) -> None:
            self.calls: list[Any] = []

        def resolve_admission(self, request):
            self.calls.append(request)
            # The unscoped subject is refused by the live Control Plane
            # authority; a local double must never be able to allow it.
            raise RuntimeError("admission-double-must-not-allow")

    adapter = _RecordingAdmissionAdapter()
    runtime_calls: list[str] = []

    def _runtime_factory(app_id: str):
        runtime_calls.append(app_id)
        raise AssertionError("Core runtime must not be constructed for an unscoped probe")

    service = AdmissionBoundOrchestrationEngineService(
        runtime_factory=_runtime_factory,
        b14_service_bound=True,
        admission_adapter=adapter,
    )
    await service.orchestrate_payload(copy.deepcopy(payload))

    assert len(adapter.calls) == 1, "the admission seam must be consulted exactly once"
    assert adapter.calls[0].subject_id is None
    assert runtime_calls == [], "Core/provider dispatch seam was reached"


def test_probe_carries_no_privileged_or_entitlement_material() -> None:
    payload = _payload()
    for forbidden in (
        "entitlement",
        "plan",
        "credits",
        "allow",
        "role",
        "api_key",
        "token",
        "secret",
    ):
        assert forbidden not in payload, forbidden