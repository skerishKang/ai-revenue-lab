"""#5002: the Engine forwards the account's validated model verbatim.

Every model id travels to Business 14, which owns availability and refuses
unknown ids; the Engine never rewrites a model into another default. A missing
model still fails closed with the field-level ``invalid_request`` before any
runtime or provider call.
"""
from __future__ import annotations

import json

import pytest

from padiem_ai_core import (
    B14ExecutionResult,
    ExecutionRuntime,
)

from app.service import EngineService

# Inert, syntactically valid model routes. They prove what the Engine forwards
# verbatim; B14 stays the availability authority, so nothing here claims these
# are registered models.
_MEMBER_MODEL_ID = "testowner/member-route.v1"
_ADMIN_MODEL_ID = "testowner/administrator-route.v1"


def _payload(model: str, *, product_tier: str | None = None) -> dict:
    policy: dict[str, object] = {"model": model, "max_retries": 0}
    if product_tier is not None:
        policy["product_tier"] = product_tier
    return {
        "app_id": "padiem-claw",
        "agent": {
            "id": "claw-answer-agent",
            "title": "Claw answer agent",
            "description": "Answers with the account's validated model.",
            "system_instruction": "Answer the user.",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 512,
            "model_policy": policy,
        },
        "messages": [{"role": "user", "content": "안녕"}],
        "trace_id": "trace-5002",
    }


class _FakeB14:
    def __init__(self) -> None:
        self.calls: list[object] = []

    async def execute(self, request):
        self.calls.append(request)
        return B14ExecutionResult(answer="unused")


class _NoExecutionRuntime:
    """Any runtime call would be a contract violation for a refused request."""

    def __init__(self) -> None:
        self.calls: list[object] = []

    async def run(self, request):
        self.calls.append(request)
        raise AssertionError("a refused model must never reach a runtime")


# --- the account's own validated model and grade still reach B14 -------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "product_tier"),
    [
        # An ordinary member grade, and the administrator's exact route on the
        # administrator's own lane. The Engine forwards both verbatim.
        (_MEMBER_MODEL_ID, "free"),
        (_ADMIN_MODEL_ID, "plus"),
    ],
)
async def test_the_exact_validated_model_and_grade_reach_the_b14_request_verbatim(
    model: str, product_tier: str
) -> None:
    b14 = _FakeB14()
    service = EngineService(
        runtime_factory=lambda app_id: ExecutionRuntime(app_id=app_id, b14_client=b14),
        b14_service_bound=True,
    )

    response = await service.execute_payload(_payload(model, product_tier=product_tier))

    assert response.status_code == 200
    assert len(b14.calls) == 1
    body = b14.calls[0].to_payload()
    assert body["model"] == model
    assert body["business14"]["product_tier"] == product_tier
    assert body["business14"]["max_retries"] == 0
    # No hidden substitution ever appears in an outbound body.
    assert "testowner/other-route" not in json.dumps(body, ensure_ascii=False)


@pytest.mark.asyncio
async def test_an_explicit_caller_retry_budget_reaches_b14_verbatim() -> None:
    b14 = _FakeB14()
    service = EngineService(
        runtime_factory=lambda app_id: ExecutionRuntime(app_id=app_id, b14_client=b14),
        b14_service_bound=True,
    )
    payload = _payload(_MEMBER_MODEL_ID, product_tier="free")
    payload["agent"]["model_policy"]["max_retries"] = 1

    response = await service.execute_payload(payload)

    assert response.status_code == 200
    assert len(b14.calls) == 1
    assert b14.calls[0].to_payload()["business14"]["max_retries"] == 1


@pytest.mark.asyncio
async def test_a_missing_model_still_fails_closed_before_any_b14_call() -> None:
    runtime = _NoExecutionRuntime()
    b14 = _FakeB14()
    service = EngineService(
        runtime_factory=lambda app_id: ExecutionRuntime(app_id=app_id, b14_client=b14),
        b14_service_bound=True,
    )
    payload = _payload(_MEMBER_MODEL_ID)
    payload["agent"].pop("model_policy")

    response = await service.execute_payload(payload)

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_request"
    assert runtime.calls == []
    assert b14.calls == []
