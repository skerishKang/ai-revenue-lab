"""#5002 + B7: the Engine forwards the account's validated model verbatim.

The retired automatic route has no Engine-side special case any more. Every
model id — including the retired one — travels to Business 14, which owns
availability and refuses unknown ids; the Engine never rewrites a model into
another default. A missing model still fails closed with the field-level
``invalid_request`` before any runtime or provider call.
"""
from __future__ import annotations

import json

import pytest

from padiem_ai_core import (
    B14ExecutionResult,
    ExecutionRuntime,
    StreamingExecutionRuntime,
)

from app.service import EngineService
from app.streaming_service import PreparedStream, STREAM_PATH, StreamingEngineService
from app.web_research_service import WebResearchEngineService

# Inert, syntactically valid model routes. They prove what the Engine forwards
# verbatim; B14 stays the availability authority, so nothing here claims these
# are registered models.
_MEMBER_MODEL_ID = "testowner/member-route.v1"
_ADMIN_MODEL_ID = "testowner/administrator-route.v1"
_AUTO_MODEL_ID = "b14/auto"


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


class _FakeB14StreamClient:
    def __init__(self) -> None:
        self.manual_calls: list[object] = []

    def stream(self, request):
        self.manual_calls.append(request)
        return self._events()

    async def _events(self):
        from padiem_ai_core import B14StreamEvent

        yield B14StreamEvent(response_id="resp-1", model="provider/route", delta_content="hi")
        yield B14StreamEvent(response_id="resp-1", model="provider/route", done=True)


class _NoExecutionRuntime:
    """Any runtime call would be a contract violation for a refused request."""

    def __init__(self) -> None:
        self.calls: list[object] = []

    async def run(self, request):
        self.calls.append(request)
        raise AssertionError("a refused model must never reach a runtime")


# --- one rule: the Engine forwards whatever model the account validated ------


@pytest.mark.asyncio
async def test_the_execute_route_forwards_the_model_verbatim_including_the_retired_id() -> None:
    b14 = _FakeB14()
    service = EngineService(
        runtime_factory=lambda app_id: ExecutionRuntime(app_id=app_id, b14_client=b14),
        b14_service_bound=True,
    )

    response = await service.execute_payload(_payload(_AUTO_MODEL_ID))

    assert response.status_code == 200
    assert len(b14.calls) == 1
    assert b14.calls[0].to_payload()["model"] == _AUTO_MODEL_ID


@pytest.mark.asyncio
async def test_the_stream_route_dispatches_the_single_manual_lane_for_the_retired_id() -> None:
    b14 = _FakeB14StreamClient()
    service = StreamingEngineService(
        runtime_factory=lambda app_id: StreamingExecutionRuntime(
            app_id=app_id, b14_stream_client=b14
        ),
        b14_service_bound=True,
    )

    prepared = await service.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json",
        body=json.dumps(_payload(_AUTO_MODEL_ID)).encode(),
    )

    assert isinstance(prepared, PreparedStream)
    assert len(b14.manual_calls) == 1
    assert b14.manual_calls[0].to_payload()["model"] == _AUTO_MODEL_ID


@pytest.mark.asyncio
async def test_the_research_route_forwards_the_model_verbatim_including_the_retired_id() -> None:
    b14 = _FakeB14()
    service = WebResearchEngineService(
        research_runtime_factory=lambda _app_id: None,
        execution_runtime_factory=lambda _app_id: ExecutionRuntime(
            app_id=_app_id, b14_client=b14
        ),
        b14_service_bound=True,
    )
    research_payload = {
        "app_id": "padiem-claw",
        "operation": "search_judgement",
        "query": "그럼 올해도 신청할 수 있어?",
        "agent": {
            "id": "claw-answer-agent",
            "title": "Claw answer agent",
            "description": "Answers with the account's validated model.",
            "system_instruction": "Answer the user.",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 512,
            "model_policy": {"model": _AUTO_MODEL_ID},
        },
    }

    response = await service.research_payload(research_payload)

    assert response.status_code == 200
    assert len(b14.calls) == 1
    assert b14.calls[0].to_payload()["model"] == _AUTO_MODEL_ID


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    ["b14/auto", "b14/auto ", " B14/AUTO", "b14/auto-preview"],
)
async def test_no_spelling_of_the_retired_id_gets_an_engine_side_special_case(model: str) -> None:
    """B7: the Engine has no auto-route rule left, so every spelling of the
    retired id is forwarded verbatim and Business 14 owns the refusal."""
    b14 = _FakeB14()
    service = EngineService(
        runtime_factory=lambda app_id: ExecutionRuntime(app_id=app_id, b14_client=b14),
        b14_service_bound=True,
    )

    response = await service.execute_payload(_payload(model))

    assert response.status_code == 200
    assert len(b14.calls) == 1
    # Core strips surrounding whitespace on the model route before dispatch.
    assert b14.calls[0].to_payload()["model"] == model.strip()


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
