"""Every part's thought signature and the executor's own outcome (#4727).

PR #5818 replayed the token attached to a ``functionCall`` part. Two facts about
the native wire were left outside that shape:

* a signature can attach to the model turn's own answer text, and a follow-up
  has to return each token with the part it came from;
* a tool result is not always a completion. A refusal, an executor failure, a
  cancellation and a permission denial were all reaching the model as if the
  tool had answered.

This file pins both. No test here reaches a provider: every outbound request is
a synthetic MockTransport exchange, so this is mock/static evidence only.
"""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.b14_runtime_config import runtime_config as rcfg
from app.pilot.google_provider import _google_tool_body
from app.pilot.platform import (
    _canonicalize_google_compat_signatures,
    _openai_compatible_messages,
)
from app.pilot.stream_types import StreamEvent, StreamToolCall
from app.pilot.tool_channel import (
    InvalidToolDeclaration,
    validate_messages,
)

GOOGLE_TOOL_MODEL = "google/gemini-3.1-flash-lite"
UPSTREAM_MODEL = "gemini-3.1-flash-lite"
STREAM_URL = "/api/pilot/v1/chat/completions/stream-preview"
CALL_SIGNATURE = "sig_call_abc"
TURN_SIGNATURE = "sig_turn_xyz"

PC_TOOL = {"type": "function", "function": {
    "name": "pc_files",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
}}


class _ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_runtime_config(monkeypatch):
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    rcfg.provider_mode = "mock"
    yield
    rcfg.provider_mode = "mock"


def _google_live(monkeypatch) -> None:
    from app.pilot import stream_gateway

    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_05", "unit-google-key-not-a-secret")
    monkeypatch.setattr(rcfg, "provider_mode", "live")
    monkeypatch.setattr(stream_gateway, "_request_id", lambda: "b14stream_fixed")


def _client(transport) -> TestClient:
    app = create_app()
    if transport is not None:
        app.state.stream_transport = transport
    return TestClient(app)


def _native_frame(parts=(), *, finish=None):
    candidate = {"index": 0, "content": {"role": "model", "parts": list(parts)}}
    if finish is not None:
        candidate["finishReason"] = finish
    payload = {
        "responseId": "native_response", "modelVersion": UPSTREAM_MODEL,
        "candidates": [candidate],
    }
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode()


def _body(messages, *, tools=(PC_TOOL,), tool_choice="auto"):
    return _google_tool_body(
        messages=list(messages), tools=list(tools), tool_choice=tool_choice,
        temperature=None, max_tokens=None, model_parameters=None,
    )


def _call_part(call_id, *, signature=None):
    part = {"functionCall": {"id": call_id, "name": "pc_files",
                             "args": {"path": "a.txt"}}}
    if signature is not None:
        part["thoughtSignature"] = signature
    return part


# ---------------------------------------------------------------------------
# A: the decoder relays the token on the part that carried it
# ---------------------------------------------------------------------------


def _decode(parts):
    from app.pilot.google_provider import _GoogleToolStream

    stream = _GoogleToolStream({"pc_files"})
    events = []
    for part_group in parts:
        events.extend(stream.decode(_native_frame(part_group)))
    return events


def test_a_signed_answer_text_part_relays_its_own_token() -> None:
    events = _decode([
        [{"text": "확인하겠습니다", "thoughtSignature": TURN_SIGNATURE}],
        [_call_part("call_1", signature=CALL_SIGNATURE)],
    ])

    text = [event for event in events if event.delta_content]
    call = [event for event in events if event.tool_call is not None]
    assert text[0].signature == TURN_SIGNATURE
    assert call[0].tool_call.signature == CALL_SIGNATURE


def test_an_unsigned_answer_text_part_keeps_the_existing_frame_shape() -> None:
    """A provider that issues no token produces exactly the bytes it did before."""
    from app.pilot.stream_gateway import _encode_event

    events = _decode([[{"text": "확인하겠습니다"}]])
    (event,) = events
    assert event.signature is None

    def encode(with_token):
        return _encode_event(
            StreamEvent(
                response_id="native_response", model=UPSTREAM_MODEL,
                delta_content="확인하겠습니다",
                signature=TURN_SIGNATURE if with_token else None,
            ),
            request_id="b14stream_fixed",
            decision=_decision(),
        )

    assert b'"signature"' not in encode(False)
    assert encode(True) != encode(False)
    # The unsigned frame is byte-identical to the frame this lane always sent.
    assert json.loads(encode(False)[6:])["choices"][0]["delta"]["content"] == (
        "확인하겠습니다"
    )


def _decision():
    from app.pilot import router_core as rcore

    return rcore.RouteDecision(
        request_id="b14stream_fixed", route_mode="manual",
        selected_provider="Google AI Studio",
        selected_model=GOOGLE_TOOL_MODEL,
        selected_upstream_model=UPSTREAM_MODEL,
        selected_route_id=f"platform:{GOOGLE_TOOL_MODEL}",
        reason_codes=(), fallback_allowed=False, eligible_fallback=(),
        excluded_candidates=(), credential_available=True,
        credential_status="available", provider_mode="live",
        evidence_status="live", platform_provider_id="google",
    )


def test_a_thinking_part_is_still_not_relayed_as_answer_text() -> None:
    """Reasoning text stays out of the product answer, with its token.

    The part is deliberately not carried, so its token has no part to travel
    back with. Pinning this here keeps the choice visible instead of accidental.
    """
    events = _decode([
        [{"text": "생각 요약", "thought": True, "thoughtSignature": "sig_thought"}],
        [{"text": "최종 답"}],
    ])

    assert [event.delta_content for event in events] == ["최종 답"]
    assert events[0].signature is None


def test_a_malformed_answer_token_is_not_relayed() -> None:
    from app.pilot.errors import MalformedUpstreamResponse

    with pytest.raises(MalformedUpstreamResponse):
        _decode([[{"text": "답", "thoughtSignature": 1234}]])


# ---------------------------------------------------------------------------
# A: the frame, the contract field and the replay keep the same relationship
# ---------------------------------------------------------------------------


def test_the_signed_text_chunk_reaches_the_caller_and_an_unsigned_one_does_not(
    monkeypatch,
) -> None:
    _google_live(monkeypatch)
    stream = _ChunkStream([
        _native_frame([{"text": "확인", "thoughtSignature": TURN_SIGNATURE}]),
        _native_frame([{"text": "하겠습니다"}]),
        _native_frame(finish="STOP"),
    ])
    response = _client(httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream),
    )).post(STREAM_URL, json={
        "model": GOOGLE_TOOL_MODEL, "stream": True,
        "messages": [{"role": "user", "content": "파일"}],
        "tools": [PC_TOOL],
    })

    assert response.status_code == 200, response.text
    signed, unsigned = response.text.split("\n\n")[:2]
    assert json.loads(signed[6:])["signature"] == TURN_SIGNATURE
    assert "signature" not in json.loads(unsigned[6:])


def test_the_answer_token_is_replayed_on_the_part_it_signed() -> None:
    body = _body([
        {"role": "user", "content": "파일 내용을 알려줘"},
        {"role": "assistant", "content": "읽어 보겠습니다.",
         "signature": TURN_SIGNATURE, "tool_calls": [{
             "id": "call_1", "type": "function",
             "function": {"name": "pc_files", "arguments": '{"path":"a.txt"}'},
             "signature": CALL_SIGNATURE,
         }]},
        {"role": "tool", "tool_call_id": "call_1", "content": "hello"},
    ])

    parts = body["contents"][1]["parts"]
    assert parts[0] == {"text": "읽어 보겠습니다.",
                        "thoughtSignature": TURN_SIGNATURE}
    assert parts[1]["functionCall"]["id"] == "call_1"
    assert parts[1]["thoughtSignature"] == CALL_SIGNATURE
    # Neither neutral field leaks into the provider body.
    assert "signature" not in json.dumps(body)


def test_a_turn_without_answer_text_cannot_carry_an_answer_token() -> None:
    with pytest.raises(InvalidToolDeclaration):
        validate_messages([{
            "role": "assistant", "content": None, "signature": TURN_SIGNATURE,
            "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "pc_files", "arguments": "{}"},
            }],
        }])


def test_the_compatible_form_of_the_answer_token_is_accepted_as_the_same_fact():
    validated = validate_messages([{
        "role": "assistant", "content": "답",
        "extra_content": {"google": {"thought_signature": TURN_SIGNATURE}},
    }])

    assert validated[0]["signature"] == TURN_SIGNATURE


# ---------------------------------------------------------------------------
# A: the compatible lane carries the same value, other providers carry nothing
# ---------------------------------------------------------------------------


def test_the_compatible_lane_projects_the_turn_token_for_google_only() -> None:
    messages = [{"role": "assistant", "content": "답", "signature": TURN_SIGNATURE}]

    google = _openai_compatible_messages(messages, "google")[0]
    other = _openai_compatible_messages(messages, "tokenharbor")[0]

    assert google["extra_content"] == {"google": {"thought_signature": TURN_SIGNATURE}}
    assert "signature" not in google
    assert other == {"role": "assistant", "content": "답"}
    # The caller's message object is never rewritten.
    assert messages[0]["signature"] == TURN_SIGNATURE


def test_a_compatible_google_answer_returns_the_turn_token_as_canonical() -> None:
    response_data = {"choices": [{
        "index": 0,
        "message": {
            "role": "assistant", "content": "답",
            "extra_content": {"google": {"thought_signature": TURN_SIGNATURE}},
        },
    }]}

    _canonicalize_google_compat_signatures(response_data)

    message = response_data["choices"][0]["message"]
    assert message["signature"] == TURN_SIGNATURE
    assert "extra_content" not in message


def test_an_unsigned_message_is_passed_through_as_the_same_object() -> None:
    messages = [{"role": "user", "content": "안녕"}]

    assert _openai_compatible_messages(messages, "google")[0] is messages[0]


# ---------------------------------------------------------------------------
# B: the executor's outcome reaches the model as the outcome it is
# ---------------------------------------------------------------------------

_DENIED = {"status": "rejected", "error_code": "approval_denied"}
_DENIED_BY_POLICY = {"status": "policy_blocked", "error_class": "policy_blocked",
                     "error_code": "tool_auth_scope_missing"}
_EXECUTOR_ERROR = {"status": "failed", "error_code": "pc_query_unavailable",
                   "duration_ms": 12}
_CANCELLED = {"status": "failed", "error_code": "cancelled"}
#: A run that ran out of time is its own fact: not a refusal, not a crash, and
#: not the same sentence the model should hear for either.
_TIMED_OUT = {"status": "timeout", "error_class": "provider_timeout",
              "error_code": "stream_timeout", "duration_ms": 30_000}


def _followup(execution=None, *, content="hello"):
    message = {"role": "tool", "tool_call_id": "call_1", "name": "pc_files",
               "content": content}
    if execution is not None:
        message["execution"] = execution
    return [
        {"role": "user", "content": "파일 내용을 알려줘"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "pc_files", "arguments": '{"path":"a.txt"}'},
        }]},
        message,
    ]


def _response_of(body) -> dict:
    return body["contents"][2]["parts"][0]["functionResponse"]["response"]


def test_a_completed_run_is_still_the_plain_result_it_was() -> None:
    body = _body(_followup())

    assert _response_of(body) == {"result": "hello"}
    assert _response_of(_body(_followup({"status": "completed"}))) == {
        "result": "hello",
    }


@pytest.mark.parametrize("execution,label", [
    (_DENIED, "refused"),
    (_DENIED_BY_POLICY, "unauthorized"),
    (_EXECUTOR_ERROR, "failed"),
    (_CANCELLED, "cancelled"),
    (_TIMED_OUT, "out of time"),
])
def test_a_non_completion_is_never_shaped_like_a_result(execution, label) -> None:
    assert label
    response = _response_of(_body(_followup(execution)))

    # The word the model reads for an actual output is reserved for one.
    assert "result" not in response
    assert response["status"] == execution["status"]
    for name in ("error_code", "error_class"):
        if name in execution:
            assert response[name] == execution[name]
    assert response["detail"] == "hello"


def test_the_six_outcomes_are_six_different_answers() -> None:
    responses = [_response_of(_body(_followup(each))) for each in (
        {"status": "completed"}, _DENIED, _DENIED_BY_POLICY, _EXECUTOR_ERROR,
        _CANCELLED, _TIMED_OUT,
    )]

    assert len({json.dumps(item, sort_keys=True) for item in responses}) == 6


def test_a_timeout_reaches_the_model_as_a_timeout_and_not_as_a_failure() -> None:
    """The two look alike in prose and differ in fact.

    A model told "the tool failed" may retry the same call; a model told the run
    ran out of time has the cause its own timeout budget needs. The status and
    the named class are what the executor decided, so they travel verbatim.
    """
    timed_out = _response_of(_body(_followup(_TIMED_OUT, content="")))
    crashed = _response_of(_body(_followup(_EXECUTOR_ERROR, content="")))

    assert timed_out == {
        "status": "timeout", "error_class": "provider_timeout",
        "error_code": "stream_timeout",
    }
    assert crashed["status"] == "failed"
    assert timed_out["status"] != crashed["status"]


def test_a_refusal_needs_no_invented_prose() -> None:
    response = _response_of(_body(_followup(_DENIED, content="")))

    assert response == {"status": "rejected", "error_code": "approval_denied"}


def test_a_completion_still_owes_the_model_its_text() -> None:
    with pytest.raises(InvalidToolDeclaration):
        _body(_followup({"status": "completed"}, content=""))
    with pytest.raises(InvalidToolDeclaration):
        _body(_followup(content=""))


@pytest.mark.parametrize("execution", [
    {"status": "failed"},                      # no cause named
    {"status": "completed", "extra": "x"},     # unknown field
    "failed",                                  # not an object
    {"status": ""},
    {"status": "failed", "duration_ms": -1},
    {"status": "failed", "error_code": "raw provider body with spaces"},
])
def test_an_unusable_outcome_block_is_refused_before_dispatch(execution) -> None:
    """B14 checks the shape and demands a cause; the vocabulary is Core's.

    A status value the executor never reported is refused by the contract that
    owns the enum (``test_the_outcome_vocabulary_is_the_executors_own``), which
    runs before any request reaches this gateway. B14 does not keep a second
    list of the same values to drift out of step with it.
    """
    with pytest.raises(InvalidToolDeclaration):
        validate_messages(_followup(execution)[2:])


def test_the_compatible_lane_does_not_invent_a_field_for_the_outcome() -> None:
    message = {"role": "tool", "tool_call_id": "call_1", "content": "hello",
               "execution": _CANCELLED}

    for provider in ("google", "tokenharbor"):
        projected = _openai_compatible_messages([message], provider)[0]
        assert projected == {"role": "tool", "tool_call_id": "call_1",
                             "content": "hello"}


# ---------------------------------------------------------------------------
# B: the whole follow-up still runs over the real route
# ---------------------------------------------------------------------------


def test_a_denied_result_round_trips_over_the_route_as_a_refusal(monkeypatch) -> None:
    _google_live(monkeypatch)
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, stream=_ChunkStream([
            _native_frame([{"text": "승인이 필요했습니다."}]),
            _native_frame(finish="STOP"),
        ]), headers={"Content-Type": "text/event-stream"})

    response = _client(httpx.MockTransport(handler)).post(
        STREAM_URL,
        json={
            "model": GOOGLE_TOOL_MODEL, "stream": True, "tools": [PC_TOOL],
            "messages": _followup(_DENIED),
        },
    )

    assert response.status_code == 200, response.text
    assert "승인이 필요했습니다." in response.text
    assert _response_of(seen[0]) == {
        "status": "rejected", "error_code": "approval_denied", "detail": "hello",
    }


# ---------------------------------------------------------------------------
# The stream types themselves keep the shape honest
# ---------------------------------------------------------------------------


def test_a_done_event_cannot_carry_a_token() -> None:
    with pytest.raises(ValueError):
        StreamEvent(done=True, finish_reason="stop", signature=TURN_SIGNATURE)


def test_an_event_token_is_bounded_like_the_call_it_belongs_to() -> None:
    from app.pilot.tool_channel import MAX_TOOL_SIGNATURE_CHARS

    with pytest.raises(ValueError):
        StreamEvent(delta_content="답", signature="x" * (MAX_TOOL_SIGNATURE_CHARS + 1))
    with pytest.raises(ValueError):
        StreamEvent(delta_content="답", signature="   ")
    assert StreamToolCall("call_1", "pc_files", "{}", 0).signature is None
