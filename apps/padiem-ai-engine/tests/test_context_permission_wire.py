from __future__ import annotations

import json
from pathlib import Path

import pytest

from padiem_ai_core import B14RouteMetadata, ExecutionResult, RunMetadata, RunStatus, UsageMetadata

from app.service import EngineService


class CapturingRuntime:
    def __init__(self) -> None:
        self.calls = []

    async def run(self, request):
        self.calls.append(request)
        return ExecutionResult(
            answer="bounded answer",
            route=B14RouteMetadata(
                selected_provider="mock",
                selected_model="mock/model",
                actual_response_model="mock/model",
                attempt_count=1,
                fallback_used=False,
            ),
            metadata=RunMetadata(
                trace_id=request.trace_id or "trace-1",
                app_id="b61",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
                provider="mock",
                model="mock/model",
                usage=UsageMetadata(input_tokens=1, output_tokens=1, total_tokens=2),
            ),
        )


def valid_payload() -> dict:
    return {
        "app_id": "b61",
        "agent": {
            "id": "storymemory-companion",
            "title": "StoryMemory Companion",
            "description": "Reader companion over bounded context references.",
            "system_instruction": "Answer only from allowed context references.",
            "task_type": "reading",
            "optimize_for": "korean",
            "max_tokens": 512,
        },
        "messages": [{"role": "user", "content": "지금 읽은 범위에서 설명해줘"}],
        "trace_id": "trace-ctx-1",
    }


def permission_payload() -> dict:
    payload = valid_payload()
    payload["context_permission_required"] = True
    payload["context_permission"] = {
        "envelope": {
            "request_id": "trace-ctx-1",
            "source_quality_gate_applied": True,
            "policy_hints": ["product_adapter_narrowed"],
            "candidates": [
                {
                    "id": "ctx/current",
                    "scope_id": "scope/current",
                    "resource_ref": "source/current",
                    "provenance": ["b61_adapter"],
                },
                {
                    "id": "ctx/future",
                    "scope_id": "scope/future",
                    "resource_ref": "source/future",
                    "provenance": ["b61_adapter"],
                },
            ],
        },
        "boundary": {
            "allowed_scope_ids": ["scope/current"],
            "max_allowed_context": 4,
            "policy_version": "context-permission:v1",
        },
    }
    return payload


@pytest.mark.asyncio
async def test_trusted_permitted_candidate_reaches_allowed_model_context_only() -> None:
    runtime = CapturingRuntime()
    service = EngineService(runtime_factory=lambda app_id: runtime, b14_service_bound=True)

    response = await service.execute_payload(permission_payload())

    assert response.status_code == 200
    assert response.body["ok"] is True
    assert response.body["context_permission"]["boundary_disposition"] == "permitted"
    assert response.body["context_permission"]["context_allowed_count"] == 1
    assert response.body["context_permission"]["context_filtered_count"] == 1
    assert len(runtime.calls) == 1
    model_context = runtime.calls[0].additional_system_context
    assert "source/current" in model_context
    assert "source/future" not in model_context


@pytest.mark.asyncio
async def test_candidate_outside_boundary_fails_closed_before_runtime_when_required() -> None:
    runtime = CapturingRuntime()
    service = EngineService(runtime_factory=lambda app_id: runtime, b14_service_bound=True)
    payload = permission_payload()
    payload["context_permission"]["boundary"]["allowed_scope_ids"] = ["scope/unrelated"]

    response = await service.execute_payload(payload)

    assert response.status_code == 422
    assert response.body["ok"] is False
    assert response.body["error"]["code"] == "outside_knowledge_boundary"
    assert runtime.calls == []


@pytest.mark.asyncio
async def test_missing_required_trusted_boundary_fails_closed_before_runtime() -> None:
    runtime = CapturingRuntime()
    service = EngineService(runtime_factory=lambda app_id: runtime, b14_service_bound=True)
    payload = valid_payload()
    payload["context_permission_required"] = True

    response = await service.execute_payload(payload)

    assert response.status_code == 422
    assert response.body["error"]["code"] == "boundary_unavailable"
    assert runtime.calls == []


@pytest.mark.asyncio
async def test_user_self_asserted_permission_is_rejected_before_runtime() -> None:
    runtime = CapturingRuntime()
    service = EngineService(runtime_factory=lambda app_id: runtime, b14_service_bound=True)
    payload = permission_payload()
    payload["context_permission"]["envelope"]["candidates"][0]["user_asserted_permission"] = True

    response = await service.execute_payload(payload)

    assert response.status_code == 403
    assert response.body["error"]["code"] == "user_self_asserted_permission"
    assert runtime.calls == []


@pytest.mark.asyncio
async def test_caller_minted_trust_or_private_context_bytes_are_rejected() -> None:
    service = EngineService(runtime_factory=lambda app_id: CapturingRuntime(), b14_service_bound=True)
    trusted = permission_payload()
    trusted["context_permission"]["trusted"] = True
    private_text = permission_payload()
    private_text["context_permission"]["envelope"]["candidates"][0]["text"] = "PRIVATE STORY TEXT"

    trusted_response = await service.execute_payload(trusted)
    private_response = await service.execute_payload(private_text)

    assert trusted_response.status_code == 400
    assert trusted_response.body["error"]["code"] == "invalid_context_permission"
    assert private_response.status_code == 400
    assert private_response.body["error"]["code"] == "invalid_context_permission"


@pytest.mark.asyncio
async def test_boundary_unavailable_does_not_call_runtime_or_expose_private_bytes() -> None:
    runtime = CapturingRuntime()
    service = EngineService(runtime_factory=lambda app_id: runtime, b14_service_bound=True)
    payload = permission_payload()
    payload["context_permission"]["boundary"]["boundary_available"] = False

    response = await service.execute_payload(payload)
    serialized = json.dumps(response.body).lower()

    assert response.status_code == 422
    assert response.body["error"]["code"] == "boundary_unavailable"
    assert "private" not in serialized
    assert "storymemory" not in serialized
    assert runtime.calls == []


def test_engine_wire_adapter_has_no_storymemory_locator_parser() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "context_permission_wire.py").read_text(
        encoding="utf-8"
    ).lower()

    assert "storymemory" not in source
    assert "localstorage" not in source
    assert "bible:web" not in source
