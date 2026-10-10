"""#3977: the shared Core carries validated provider-native parameters.

These tests pin the transport contract B66 (#3906) depends on. The customer's
explicitly chosen reasoning level must reach the B14 request body as a
TOP-LEVEL ``reasoning_effort`` field, in the non-streaming and streaming shapes
alike, while an unspecified choice contributes nothing at all. Which served
model accepts which value stays B14 capability authority; the Core only fixes
the wire name and the closed spelling, and fails closed on anything else.

Every success below is an ``httpx.MockTransport`` observation, not a paid
provider call.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from padiem_ai_core.b14_execution import (
    B14_CHAT_COMPLETIONS_PATH,
    NATIVE_MODEL_PARAMETER_FIELDS,
    REASONING_EFFORT_VALUES,
    B14ChatRequest,
    B14ExecutionClient,
    B14ExecutionConfig,
)
from padiem_ai_core.b14_streaming import B14StreamingClient
from padiem_ai_core.contracts import AgentProfile
from padiem_ai_core.execution_runtime import (
    ExecutionRequest,
    ExecutionRuntime,
    ExecutionRuntimeError,
)
from padiem_ai_core.multimodal_execution_runtime import (
    MultimodalExecutionRequest,
    MultimodalExecutionRuntime,
)
from padiem_ai_core.streaming_runtime import StreamingExecutionRuntime

BASE_URL = "https://b14.internal"
MODEL_ID = "google/gemini-3.5-flash-lite"


def run(coro):
    return asyncio.run(coro)


def collect(stream):
    async def _drain():
        return [event async for event in stream]

    return asyncio.run(_drain())


def agent(**overrides) -> AgentProfile:
    values = {
        "id": "general-agent",
        "title": "General",
        "description": "General product-neutral agent",
        "system_instruction": "Answer carefully.",
        "task_type": "general",
        "optimize_for": "korean",
        "max_tokens": 700,
        "required_capabilities": ("chat",),
        "model_policy": {"model": MODEL_ID},
    }
    values.update(overrides)
    return AgentProfile(**values)


def execution_request(profile=None, **overrides) -> ExecutionRequest:
    values = {
        "agent": profile or agent(),
        "messages": ({"role": "user", "content": "안녕하세요"},),
        "trace_id": "trace-3977",
        "session_id": "session-3977",
    }
    values.update(overrides)
    return ExecutionRequest(**values)


def chat_request(**overrides) -> B14ChatRequest:
    values = {
        "messages": ({"role": "user", "content": "hello"},),
        "model": MODEL_ID,
    }
    values.update(overrides)
    return B14ChatRequest(**values)


class RecordingExecutor:
    """Stands in for the B14 client and records the exact Core request."""

    def __init__(self):
        self.requests = []

    async def execute(self, request: B14ChatRequest):
        from padiem_ai_core.b14_execution import B14ExecutionResult

        self.requests.append(request)
        return B14ExecutionResult(answer="ok")


def nonstream_transport(seen: dict, model_id: str = MODEL_ID):
    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "business14": {"selected_model": model_id},
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    return httpx.MockTransport(handler)


def stream_transport(
    seen: dict, model_id: str = MODEL_ID,
    provider_name: str = "Google AI Studio",
    upstream_model: str = "gemini-3.5-flash-lite",
    provider_id: str = "google",
):
    def handler(request: httpx.Request) -> httpx.Response:
        first = {
            "id": "b14req_3977",
            "object": "chat.completion.chunk",
            "model": model_id,
            "choices": [
                {"index": 0, "delta": {"content": "ok"}, "finish_reason": None}
            ],
            "business14": {
                "request_id": "b14req_3977",
                "route_mode": "manual",
                "selected_provider": provider_name,
                "selected_model": model_id,
                "selected_upstream_model": upstream_model,
                "selected_route_id": f"{provider_id}:{model_id}",
                "reason_codes": [],
                "fallback_used": False,
                "attempt_count": 1,
                "route_evidence_status": "live_streaming_preview",
                "committed": True,
            },
        }
        last = {
            "id": "b14req_3977",
            "object": "chat.completion.chunk",
            "model": model_id,
            "choices": [
                {"index": 0, "delta": {}, "finish_reason": "stop"}
            ],
            "business14": dict(first["business14"], committed=False),
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        raw = (
            b"data: " + json.dumps(first).encode("utf-8") + b"\n\n"
            + b"data: " + json.dumps(last).encode("utf-8") + b"\n\n"
            + b"data: [DONE]\n\n"
        )
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, content=raw, headers={"content-type": "text/event-stream"}
        )

    return httpx.MockTransport(handler)


# A real 1x1 PNG: the multimodal contract verifies the media type against the
# bytes, so a placeholder string would fail for an unrelated reason.
PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)


# --------------------------------------------------------------------------
# 1. Omission is the default: nothing new enters the request.
# --------------------------------------------------------------------------

def test_no_native_parameter_keeps_provider_sampling_default_omitted() -> None:
    payload = chat_request().to_payload()
    assert payload == {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": "hello"}],
    }
    assert "reasoning_effort" not in payload
    assert "model_parameters" not in payload


def test_empty_or_null_native_parameters_are_omitted_not_invented() -> None:
    for raw in ({}, {"reasoning_effort": None}, None):
        payload = chat_request(model_parameters=raw).to_payload()
        assert "reasoning_effort" not in payload
        assert "model_parameters" not in payload


# --------------------------------------------------------------------------
# 2. An explicit level is transmitted as a TOP-LEVEL field, never nested.
# --------------------------------------------------------------------------

def test_explicit_level_becomes_a_top_level_reasoning_effort_field() -> None:
    payload = chat_request(model_parameters={"reasoning_effort": "low"}).to_payload()
    assert payload["reasoning_effort"] == "low"
    assert "model_parameters" not in payload
    # The exact model ID is preserved; no substitution, no fallback widening.
    assert payload["model"] == MODEL_ID


@pytest.mark.parametrize("level", sorted(REASONING_EFFORT_VALUES))
def test_every_documented_level_is_carried_verbatim(level: str) -> None:
    payload = chat_request(model_parameters={"reasoning_effort": level}).to_payload()
    assert payload["reasoning_effort"] == level


SENSENOVA_NATIVE_EXPLICIT = {
    "top_p": 0.95, "top_k": 20, "min_p": 0.0,
    "presence_penalty": 1.5, "repetition_penalty": 1.0,
}


def test_explicit_sensenova_fields_are_top_level_with_no_injected_defaults() -> None:
    request = chat_request(
        model="sensenova/sensenova-6.8-flash-lite",
        model_parameters=SENSENOVA_NATIVE_EXPLICIT,
    )
    payload = request.to_payload()
    assert payload["model"] == "sensenova/sensenova-6.8-flash-lite"
    for name, value in SENSENOVA_NATIVE_EXPLICIT.items():
        assert payload[name] == value
    assert "temperature" not in payload
    assert "max_tokens" not in payload
    assert "reasoning_effort" not in payload
    assert "model_parameters" not in payload


@pytest.mark.parametrize("raw", [
    {"top_p": -0.01}, {"top_p": 1.01}, {"top_p": True},
    {"top_p": float("nan")}, {"min_p": float("inf")},
    {"top_k": 0}, {"top_k": False}, {"top_k": 1.5},
    {"presence_penalty": -2.01}, {"presence_penalty": 2.01},
    {"repetition_penalty": 0}, {"repetition_penalty": -1},
    {"repetition_penalty": float("inf")},
])
def test_invalid_explicit_numeric_native_fields_fail_closed(raw) -> None:
    with pytest.raises(ValueError):
        chat_request(model_parameters=raw)


def test_core_runtime_preserves_sensenova_fields_in_selected_exact_route() -> None:
    executor = RecordingExecutor()
    runtime = ExecutionRuntime(app_id="padiem-chat", b14_client=executor)
    profile = agent(model_policy={
        "model": "sensenova/sensenova-6.8-flash-lite",
        "model_parameters": SENSENOVA_NATIVE_EXPLICIT,
        "allow_external_fallback": False,
    })
    run(runtime.run(execution_request(profile=profile)))
    assert len(executor.requests) == 1
    payload = executor.requests[0].to_payload()
    assert payload["model"] == "sensenova/sensenova-6.8-flash-lite"
    for name, value in SENSENOVA_NATIVE_EXPLICIT.items():
        assert payload[name] == value
    assert "temperature" not in payload
    assert "model_parameters" not in payload


# --------------------------------------------------------------------------
# 3. Closed vocabulary: anything unverified fails closed at construction.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw",
    [
        {"reasoning_effort": "extreme"},          # outside the documented set
        {"reasoning_effort": "LOW"},              # exact spelling only
        {"reasoning_effort": 3},                  # not a string
        {"reasoning_effort": ""},                 # empty is not a level
        {"temperature_bias": "low"},              # field this contract omits
        {"reasoning_effort": "low", "min_p": -0.5},
    ],
)
def test_unsupported_native_parameters_are_rejected(raw) -> None:
    with pytest.raises(ValueError):
        chat_request(model_parameters=raw)


def test_native_parameter_set_is_the_closed_documented_vocabulary() -> None:
    assert NATIVE_MODEL_PARAMETER_FIELDS == frozenset({
        "reasoning_effort", "top_p", "top_k", "min_p",
        "presence_penalty", "repetition_penalty",
    })
    assert REASONING_EFFORT_VALUES == frozenset({"minimal", "low", "medium", "high"})


def test_rejected_parameter_never_reaches_the_transport() -> None:
    executor = RecordingExecutor()
    runtime = ExecutionRuntime(app_id="padiem-chat", b14_client=executor)
    request = execution_request(
        profile=agent(model_policy={"model": MODEL_ID, "model_parameters": {"reasoning_effort": "extreme"}})
    )
    with pytest.raises(ExecutionRuntimeError) as raised:
        run(runtime.run(request))
    assert raised.value.metadata.status.value == "rejected"
    assert executor.requests == []


# --------------------------------------------------------------------------
# 4. The runtime threads the policy through to the real HTTP body.
# --------------------------------------------------------------------------

def test_runtime_places_the_level_at_the_top_level_of_the_b14_request() -> None:
    seen: dict = {}
    core_client = B14ExecutionClient(
        B14ExecutionConfig(BASE_URL), transport=nonstream_transport(seen)
    )
    runtime = ExecutionRuntime(app_id="padiem-chat", b14_client=core_client)
    result = run(
        runtime.run(
            execution_request(
                profile=agent(
                    model_policy={
                        "model": MODEL_ID,
                        "model_parameters": {"reasoning_effort": "medium"},
                    }
                )
            )
        )
    )
    assert result.answer == "ok"
    assert seen["url"] == BASE_URL + B14_CHAT_COMPLETIONS_PATH
    assert seen["body"]["reasoning_effort"] == "medium"
    assert seen["body"]["model"] == MODEL_ID
    assert "model_parameters" not in seen["body"]


def test_runtime_without_a_policy_parameter_sends_no_reasoning_field() -> None:
    seen: dict = {}
    core_client = B14ExecutionClient(
        B14ExecutionConfig(BASE_URL), transport=nonstream_transport(seen)
    )
    runtime = ExecutionRuntime(app_id="padiem-chat", b14_client=core_client)
    run(runtime.run(execution_request()))
    assert "reasoning_effort" not in seen["body"]
    assert "model_parameters" not in seen["body"]


# --------------------------------------------------------------------------
# 5. Streaming and non-streaming carry the identical native field.
# --------------------------------------------------------------------------

def test_stream_and_non_stream_bodies_agree_on_the_native_field() -> None:
    nonstream_seen: dict = {}
    stream_seen: dict = {}
    profile = agent(
        model_policy={"model": MODEL_ID, "model_parameters": {"reasoning_effort": "high"}}
    )

    run(
        ExecutionRuntime(
            app_id="padiem-chat",
            b14_client=B14ExecutionClient(
                B14ExecutionConfig(BASE_URL), transport=nonstream_transport(nonstream_seen)
            ),
        ).run(execution_request(profile=profile))
    )
    collect(
        StreamingExecutionRuntime(
            app_id="padiem-chat",
            b14_stream_client=B14StreamingClient(
                B14ExecutionConfig(BASE_URL), transport=stream_transport(stream_seen)
            ),
        ).stream(execution_request(profile=profile))
    )

    assert stream_seen["body"]["reasoning_effort"] == "high"
    assert nonstream_seen["body"]["reasoning_effort"] == "high"
    for seen in (nonstream_seen, stream_seen):
        assert seen["body"]["model"] == MODEL_ID
        assert "model_parameters" not in seen["body"]
    # The only intended difference between the two shapes is the stream flag.
    assert stream_seen["body"]["stream"] is True
    assert "stream" not in nonstream_seen["body"]
    assert {k: v for k, v in stream_seen["body"].items() if k != "stream"} == {
        k: v for k, v in nonstream_seen["body"].items()
    }


def test_sensenova_explicit_numeric_fields_have_stream_and_nonstream_parity() -> None:
    """Core wire test only; B14 still validates the exact serving model."""
    model_id = "sensenova/sensenova-6.8-flash-lite"
    nonstream_seen: dict = {}
    stream_seen: dict = {}
    profile = agent(model_policy={
        "model": model_id,
        "model_parameters": SENSENOVA_NATIVE_EXPLICIT,
        "allow_external_fallback": False,
    })
    run(
        ExecutionRuntime(
            app_id="padiem-chat",
            b14_client=B14ExecutionClient(
                B14ExecutionConfig(BASE_URL),
                transport=nonstream_transport(nonstream_seen, model_id=model_id),
            ),
        ).run(execution_request(profile=profile))
    )
    collect(
        StreamingExecutionRuntime(
            app_id="padiem-chat",
            b14_stream_client=B14StreamingClient(
                B14ExecutionConfig(BASE_URL),
                transport=stream_transport(
                    stream_seen,
                    model_id=model_id,
                    provider_name="SenseNova",
                    upstream_model="sensenova-6.8-flash-lite",
                    provider_id="sensenova",
                ),
            ),
        ).stream(execution_request(profile=profile))
    )

    for seen in (nonstream_seen, stream_seen):
        payload = seen["body"]
        assert payload["model"] == model_id
        assert "model_parameters" not in payload
        assert "temperature" not in payload
        for name, value in SENSENOVA_NATIVE_EXPLICIT.items():
            assert payload[name] == value
    assert stream_seen["body"]["stream"] is True
    assert "stream" not in nonstream_seen["body"]
    assert {
        key: value for key, value in stream_seen["body"].items() if key != "stream"
    } == nonstream_seen["body"]


def test_streaming_lane_omits_the_field_when_nothing_was_chosen() -> None:
    stream_seen: dict = {}
    collect(
        StreamingExecutionRuntime(
            app_id="padiem-chat",
            b14_stream_client=B14StreamingClient(
                B14ExecutionConfig(BASE_URL), transport=stream_transport(stream_seen)
            ),
        ).stream(execution_request())
    )
    assert "reasoning_effort" not in stream_seen["body"]


# --------------------------------------------------------------------------
# 6. The image lane has no verified native contract, so it refuses.
# --------------------------------------------------------------------------

def multimodal_request(profile: AgentProfile) -> MultimodalExecutionRequest:
    return MultimodalExecutionRequest(
        agent=profile,
        messages=(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "이 사진"},
                    {"type": "image_url", "image_url": {"url": PNG_DATA_URL}},
                ],
            },
        ),
        trace_id="trace-3977-mm",
    )


def test_multimodal_runtime_refuses_an_explicit_level_instead_of_dropping_it() -> None:
    executor = RecordingExecutor()
    profile = agent(
        required_capabilities=("chat", "image"),
        model_policy={"model": MODEL_ID, "model_parameters": {"reasoning_effort": "low"}},
    )
    runtime = MultimodalExecutionRuntime(app_id="padiem-chat", b14_client=executor)
    with pytest.raises(ExecutionRuntimeError) as raised:
        run(runtime.run(multimodal_request(profile)))
    assert raised.value.metadata.status.value == "rejected"
    assert executor.requests == []


def test_multimodal_runtime_still_runs_without_a_native_parameter() -> None:
    seen: dict = {}
    profile = agent(required_capabilities=("chat", "image"))
    runtime = MultimodalExecutionRuntime(
        app_id="padiem-chat",
        b14_client=B14ExecutionClient(
            B14ExecutionConfig(BASE_URL), transport=nonstream_transport(seen)
        ),
    )
    run(runtime.run(multimodal_request(profile)))
    assert "reasoning_effort" not in seen["body"]
    assert seen["body"]["model"] == MODEL_ID


# --------------------------------------------------------------------------
# 7. Existing Core consumers keep their exact request shape.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "policy",
    [
        {"model": "test/route"},
        {"model": "test/route", "temperature": 0.7},
        {"model": "test/route", "max_attempts": 1, "max_retries": 0},
        {"model": "b14/auto", "allow_external_fallback": True},
    ],
)
def test_policies_without_native_parameters_are_unchanged(policy) -> None:
    executor = RecordingExecutor()
    runtime = ExecutionRuntime(app_id="padiem-chat", b14_client=executor)
    run(runtime.run(execution_request(profile=agent(model_policy=policy))))
    payload = executor.requests[0].to_payload()
    assert "reasoning_effort" not in payload
    assert "model_parameters" not in payload
    assert payload["model"] == policy["model"]
    if "temperature" in policy:
        assert payload["temperature"] == policy["temperature"]
    else:
        assert "temperature" not in payload


# --------------------------------------------------------------------------
# 8. Existing construction sites keep working: the field is defaulted, not
#    required. These are the shapes the known Core consumers actually use.
# --------------------------------------------------------------------------

def test_positional_construction_still_works() -> None:
    # B62/B14 call sites that pass messages and model positionally.
    request = B14ChatRequest(
        ({"role": "user", "content": "hello"},), "test/route", 0.4, 64
    )
    payload = request.to_payload()
    assert payload == {
        "model": "test/route",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.4,
        "max_tokens": 64,
    }


def test_auto_route_consumer_shape_is_unchanged() -> None:
    # The Router auto lane (B62 chat and engine auto execution) never sets the
    # native field, so its body stays exactly the pre-#3977 shape.
    from padiem_ai_core.b14_execution import B14RoutingOptions

    request = B14ChatRequest(
        messages=({"role": "user", "content": "안녕하세요"},),
        model="b14/auto",
        temperature=0.3,
        max_tokens=128,
        routing=B14RoutingOptions(
            task_type="general",
            required_capabilities=("free",),
            optimize_for="balanced",
            allow_external_fallback=True,
            max_attempts=2,
        ),
    )
    payload = request.to_payload()
    assert "reasoning_effort" not in payload
    assert payload["business14"] == {
        "task_type": "general",
        "required_capabilities": ["free"],
        "optimize_for": "balanced",
        "allow_external_fallback": True,
        "max_attempts": 2,
    }


def test_agent_profile_consumer_without_the_key_is_accepted_by_every_lane() -> None:
    """Text, streaming and image lanes all accept a policy that omits the field."""
    executor = RecordingExecutor()
    text = run(
        ExecutionRuntime(app_id="padiem-chat", b14_client=executor).run(
            execution_request()
        )
    )
    assert text.answer == "ok"

    collect(
        StreamingExecutionRuntime(
            app_id="padiem-chat",
            b14_stream_client=B14StreamingClient(
                B14ExecutionConfig(BASE_URL), transport=stream_transport({})
            ),
        ).stream(execution_request())
    )
    assert executor.requests[0].model_parameters == {}

    image_executor = RecordingExecutor()
    run(
        MultimodalExecutionRuntime(
            app_id="padiem-chat", b14_client=image_executor
        ).run(
            multimodal_request(
                agent(required_capabilities=("chat", "image"))
            )
        )
    )
    assert image_executor.requests[0].model_parameters == {}


def test_frozen_mapping_cannot_be_mutated_by_the_caller() -> None:
    """A caller must not be able to widen the request after validation."""
    mutable = {"reasoning_effort": "low"}
    request = chat_request(model_parameters=mutable)
    mutable["reasoning_effort"] = "high"
    mutable["top_p"] = 0.9
    payload = request.to_payload()
    assert payload["reasoning_effort"] == "low"
    assert "top_p" not in payload

