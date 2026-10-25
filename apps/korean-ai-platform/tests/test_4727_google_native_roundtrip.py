"""Google native tool-call roundtrip on Business 14 (#4727).

The first-turn call already existed. This suite covers the half that did not:
an assistant call and its result are replayed as ``functionCall`` /
``functionResponse`` parts, and the provider's opaque thought signature travels
back with the call it belongs to. Gemini 3 refuses a replay that drops it.

Every outbound request here uses a synthetic MockTransport. No credential is
spent and no provider is reached; this is mock/static evidence only.
"""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.b14_runtime_config import runtime_config as rcfg
from app.pilot.errors import StreamNotSupported, ToolsNotSupported
from app.pilot.google_provider import _google_tool_body, _GoogleToolStream
from app.pilot.platform import _openai_compatible_messages
from app.pilot.tool_channel import (
    InvalidToolDeclaration,
    require_stream_tool_wire,
)

GOOGLE_TOOL_MODEL = "google/gemini-3.1-flash-lite"
UPSTREAM_MODEL = "gemini-3.1-flash-lite"
STREAM_URL = "/api/pilot/v1/chat/completions/stream-preview"
CHAT_URL = "/api/pilot/v1/chat/completions"
SIGNATURE = "sig_native_abc123"

PC_TOOL = {"type": "function", "function": {
    "name": "pc_files", "description": "Inspect the requested PC scope.",
    "parameters": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
}}


class _ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_runtime_config(monkeypatch):
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    rcfg.provider_mode = "mock"
    yield
    rcfg.provider_mode = "mock"


def _google_live(monkeypatch):
    from app.pilot import stream_gateway

    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_05", "unit-google-key-not-a-secret")
    monkeypatch.setattr(rcfg, "provider_mode", "live")
    monkeypatch.setattr(stream_gateway, "_request_id", lambda: "b14stream_fixed")


def _client(transport: httpx.AsyncBaseTransport | None = None) -> TestClient:
    app = create_app()
    if transport is not None:
        app.state.stream_transport = transport
    return TestClient(app)


def _payload(**overrides):
    payload = {
        "model": GOOGLE_TOOL_MODEL,
        "messages": [{"role": "user", "content": "안녕하세요"}],
        "stream": True,
    }
    payload.update(overrides)
    return payload


def _native_frame(parts=None, *, finish=None):
    candidate = {"index": 0, "content": {"role": "model", "parts": parts or []}}
    if finish is not None:
        candidate["finishReason"] = finish
    payload = {
        "responseId": "native_response",
        "modelVersion": UPSTREAM_MODEL,
        "candidates": [candidate],
    }
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode()


def _call(call_id, *, name="pc_files", arguments='{"path":"a.txt"}', signature=None):
    call = {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }
    if signature is not None:
        call["signature"] = signature
    return call


def _body(messages, *, tools=(PC_TOOL,), tool_choice="auto"):
    return _google_tool_body(
        messages=list(messages), tools=list(tools), tool_choice=tool_choice,
        temperature=None, max_tokens=None, model_parameters=None,
    )


# ---------------------------------------------------------------------------
# A call and its result become native parts
# ---------------------------------------------------------------------------


def test_a_followup_replays_the_call_and_its_result_with_the_signature() -> None:
    body = _body([
        {"role": "system", "content": "시스템"},
        {"role": "user", "content": "파일 내용을 알려줘"},
        {"role": "assistant", "content": None, "tool_calls": [
            _call("call_1", signature=SIGNATURE),
        ]},
        {"role": "tool", "tool_call_id": "call_1", "name": "pc_files", "content": "hello"},
    ])

    assert body["systemInstruction"] == {"parts": [{"text": "시스템"}]}
    assert body["contents"] == [
        {"role": "user", "parts": [{"text": "파일 내용을 알려줘"}]},
        {"role": "model", "parts": [{
            "functionCall": {
                "id": "call_1", "name": "pc_files", "args": {"path": "a.txt"},
            },
            "thoughtSignature": SIGNATURE,
        }]},
        {"role": "user", "parts": [{
            "functionResponse": {
                "id": "call_1", "name": "pc_files",
                "response": {"result": "hello"},
            },
        }]},
    ]
    # The neutral field never leaks into the provider body.
    assert "signature" not in json.dumps(body)


def test_parallel_calls_keep_call_order_and_only_the_issued_signature() -> None:
    body = _body([
        {"role": "user", "content": "두 파일을 알려줘"},
        {"role": "assistant", "content": None, "tool_calls": [
            _call("call_1", signature=SIGNATURE),
            _call("call_2", arguments='{"path":"b.txt"}'),
        ]},
        # Results arrive in execution order, not call order.
        {"role": "tool", "tool_call_id": "call_2", "content": "second"},
        {"role": "tool", "tool_call_id": "call_1", "content": "first"},
    ])

    model_parts = body["contents"][1]["parts"]
    assert [part["functionCall"]["id"] for part in model_parts] == ["call_1", "call_2"]
    assert model_parts[0]["thoughtSignature"] == SIGNATURE
    assert "thoughtSignature" not in model_parts[1]
    responses = body["contents"][2]["parts"]
    assert [part["functionResponse"]["id"] for part in responses] == ["call_1", "call_2"]
    assert [part["functionResponse"]["response"]["result"] for part in responses] == [
        "first", "second",
    ]


def test_a_result_with_no_signature_stays_unsigned() -> None:
    body = _body([
        {"role": "user", "content": "파일"},
        {"role": "assistant", "content": None, "tool_calls": [_call("call_1")]},
        {"role": "tool", "tool_call_id": "call_1", "content": "hello"},
    ])

    assert "thoughtSignature" not in json.dumps(body)


def test_assistant_text_before_a_call_travels_in_the_same_model_turn() -> None:
    body = _body([
        {"role": "user", "content": "파일"},
        {"role": "assistant", "content": "읽어 보겠습니다.", "tool_calls": [_call("call_1")]},
        {"role": "tool", "tool_call_id": "call_1", "content": "hello"},
    ])

    assert body["contents"][1]["parts"] == [
        {"text": "읽어 보겠습니다."},
        {"functionCall": {"id": "call_1", "name": "pc_files", "args": {"path": "a.txt"}}},
    ]


# ---------------------------------------------------------------------------
# A replay that does not match the declaration is refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("messages,reason", [
    (
        [
            {"role": "user", "content": "파일"},
            {"role": "tool", "tool_call_id": "call_1", "content": "hello"},
        ],
        "a result with no preceding call",
    ),
    (
        [
            {"role": "user", "content": "파일"},
            {"role": "assistant", "content": None, "tool_calls": [
                _call("call_1"), _call("call_2", arguments='{"path":"b.txt"}'),
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": "hello"},
        ],
        "one call left unanswered",
    ),
    (
        [
            {"role": "user", "content": "파일"},
            {"role": "assistant", "content": None, "tool_calls": [_call("call_1")]},
            {"role": "tool", "tool_call_id": "call_9", "content": "hello"},
        ],
        "a result for an unknown call",
    ),
    (
        [
            {"role": "user", "content": "파일"},
            {"role": "assistant", "content": None, "tool_calls": [_call("call_1")]},
            {"role": "tool", "tool_call_id": "call_1", "content": "first"},
            {"role": "tool", "tool_call_id": "call_1", "content": "second"},
        ],
        "a call answered twice",
    ),
    (
        [
            {"role": "user", "content": "파일"},
            {"role": "assistant", "content": None, "tool_calls": [
                _call("call_1", name="drop_everything"),
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": "hello"},
        ],
        "a historical call for an undeclared tool",
    ),
    (
        [
            {"role": "user", "content": "파일"},
            {"role": "assistant", "content": None, "tool_calls": [
                _call("call_1", arguments="not-json"),
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": "hello"},
        ],
        "arguments that do not encode an object",
    ),
    (
        [
            {"role": "user", "content": "파일"},
            {"role": "assistant", "content": None, "tool_calls": [
                _call("call_1"), _call("call_1"),
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": "hello"},
        ],
        "a duplicated call id in one turn",
    ),
    (
        [
            {"role": "user", "content": "파일"},
            {"role": "assistant", "content": None, "tool_calls": [
                _call("call_1", signature=""),
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": "hello"},
        ],
        "an empty signature",
    ),
])
def test_a_mismatched_replay_is_refused(messages, reason) -> None:
    assert reason
    with pytest.raises(InvalidToolDeclaration):
        _body(messages)


def test_a_result_name_must_match_the_call_it_answers() -> None:
    with pytest.raises(InvalidToolDeclaration):
        _body([
            {"role": "user", "content": "파일"},
            {"role": "assistant", "content": None, "tool_calls": [_call("call_1")]},
            {"role": "tool", "tool_call_id": "call_1", "name": "other", "content": "x"},
        ])


# ---------------------------------------------------------------------------
# The native stream relays the signature; a broken one is not relayed
# ---------------------------------------------------------------------------


def test_the_native_stream_relays_the_thought_signature(monkeypatch) -> None:
    _google_live(monkeypatch)
    stream = _ChunkStream([
        _native_frame([{
            "functionCall": {"id": "call_native", "name": "pc_files",
                             "args": {"path": "a.txt"}},
            "thoughtSignature": SIGNATURE,
        }]),
        _native_frame(finish="STOP"),
    ])
    response = _client(httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream),
    )).post(STREAM_URL, json=_payload(tools=[PC_TOOL]))

    assert response.status_code == 200, response.text
    assert response.text.startswith(
        'event: tool_call\ndata: {"id":"call_native","name":"pc_files",'
        '"arguments":"{\\"path\\":\\"a.txt\\"}","index":0,'
        f'"signature":"{SIGNATURE}"}}\n\n'
    )
    assert response.text.endswith('event: done\ndata: {"finish_reason":"tool_calls"}\n\n')


def test_a_malformed_thought_signature_is_not_relayed(monkeypatch) -> None:
    _google_live(monkeypatch)
    stream = _ChunkStream([
        _native_frame([{
            "functionCall": {"id": "call_native", "name": "pc_files",
                             "args": {"path": "a.txt"}},
            "thoughtSignature": 1234,
        }]),
    ])
    response = _client(httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream),
    )).post(STREAM_URL, json=_payload(tools=[PC_TOOL]))

    # The malformed part is the first output, so the stream never starts. The
    # caller gets a handled 502, never a fabricated call with no signature.
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "malformed_upstream_response"


# ---------------------------------------------------------------------------
# The completed Google compatible lane carries the same value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completed_google_response_signature_becomes_canonical(monkeypatch) -> None:
    from app.pilot.platform import call_platform_chat_completions
    from app.pilot.platform_secrets import get_platform_provider

    _google_live(monkeypatch)
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={
            "model": UPSTREAM_MODEL,
            "choices": [{
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "pc_files", "arguments": '{"path":"a.txt"}'},
                        "extra_content": {"google": {"thought_signature": SIGNATURE}},
                    }],
                },
            }],
        })

    answer = await call_platform_chat_completions(
        model_id=GOOGLE_TOOL_MODEL, upstream_model=UPSTREAM_MODEL,
        provider="Google AI Studio", platform_provider_id="google",
        messages=[
            {"role": "user", "content": "파일"},
            {"role": "assistant", "content": None, "tool_calls": [
                _call("call_1", signature=SIGNATURE),
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": "hello"},
        ],
        tools=[PC_TOOL], transport=httpx.MockTransport(handler),
    )

    # The request carried the signature in Google's compatible shape, not in
    # B14's neutral field.
    sent_call = seen[0]["messages"][1]["tool_calls"][0]
    assert "signature" not in sent_call
    assert sent_call["extra_content"] == {"google": {"thought_signature": SIGNATURE}}

    # The answer is canonicalized for the consumer, keeping the id/arguments.
    call = answer["choices"][0]["message"]["tool_calls"][0]
    assert call["signature"] == SIGNATURE
    assert "extra_content" not in call
    assert call["id"] == "call_1"
    assert call["function"] == {"name": "pc_files", "arguments": '{"path":"a.txt"}'}


def test_a_non_google_wire_never_receives_the_opaque_signature() -> None:
    messages = [{
        "role": "assistant", "content": None,
        "tool_calls": [_call("call_1", signature=SIGNATURE)],
    }]

    projected = _openai_compatible_messages(messages, "tokenharbor")

    assert "signature" not in projected[0]["tool_calls"][0]
    assert "extra_content" not in projected[0]["tool_calls"][0]
    # The caller's message is not mutated by the projection.
    assert messages[0]["tool_calls"][0]["signature"] == SIGNATURE


# ---------------------------------------------------------------------------
# Capability is still the registry's, not the wire's or the docs'
# ---------------------------------------------------------------------------


def test_the_two_registered_gemini_routes_open_the_tool_wire() -> None:
    require_stream_tool_wire(GOOGLE_TOOL_MODEL, "google")
    require_stream_tool_wire("google/gemini-3.5-flash-lite", "google")


@pytest.mark.parametrize("model_id", [
    "google/gemma-4-26b-a4b-it",
    "google/gemma-4-31b-it",
])
def test_an_untagged_google_model_is_refused_before_dispatch(model_id) -> None:
    with pytest.raises(ToolsNotSupported):
        require_stream_tool_wire(model_id, "google")


def test_a_non_google_provider_keeps_its_existing_refusal() -> None:
    with pytest.raises(StreamNotSupported):
        require_stream_tool_wire(GOOGLE_TOOL_MODEL, "tokenharbor")


# ---------------------------------------------------------------------------
# The whole round trip over the real route, not over the translator alone
# ---------------------------------------------------------------------------


def _answer_transport(seen: list) -> httpx.MockTransport:
    """Serve a plain text answer and record the exact outbound native request."""
    def handler(request):
        seen.append((str(request.url), json.loads(request.content)))
        return httpx.Response(
            200,
            stream=_ChunkStream([
                _native_frame([{"text": "파일 내용은 hello 입니다."}]),
                _native_frame(finish="STOP"),
            ]),
            headers={"Content-Type": "text/event-stream"},
        )

    return httpx.MockTransport(handler)


def _replay(messages) -> tuple[str, dict]:
    """Send a follow-up turn through the route and return the outbound request."""
    seen: list = []
    response = _client(_answer_transport(seen)).post(
        STREAM_URL, json=_payload(tools=[PC_TOOL], messages=messages)
    )
    assert response.status_code == 200, response.text
    assert "파일 내용은 hello 입니다." in response.text
    assert len(seen) == 1
    return seen[0]


def _followup_turn(call_entry) -> list:
    return [
        {"role": "user", "content": "파일 내용을 알려줘"},
        {"role": "assistant", "content": None, "tool_calls": [call_entry]},
        {"role": "tool", "tool_call_id": "call_native", "name": "pc_files",
         "content": "hello"},
    ]


def test_the_replayed_call_reaches_the_native_endpoint_still_signed(monkeypatch) -> None:
    _google_live(monkeypatch)
    url, body = _replay(_followup_turn(_call("call_native", signature=SIGNATURE)))

    # The tool turn is served by the native wire, not the compatible endpoint.
    assert url.startswith("https://generativelanguage.googleapis.com/v1beta/models/")
    assert ":streamGenerateContent" in url
    model_part = body["contents"][1]["parts"][0]
    assert model_part["functionCall"] == {
        "id": "call_native", "name": "pc_files", "args": {"path": "a.txt"},
    }
    assert model_part["thoughtSignature"] == SIGNATURE
    assert body["contents"][2]["parts"][0]["functionResponse"]["response"] == {
        "result": "hello",
    }


def test_a_caller_echoing_the_compatible_field_replays_the_same_body(monkeypatch) -> None:
    """A consumer that returns the provider's own field verbatim is accepted."""
    _google_live(monkeypatch)
    echoed = {
        "id": "call_native", "type": "function",
        "function": {"name": "pc_files", "arguments": '{"path":"a.txt"}'},
        "extra_content": {"google": {"thought_signature": SIGNATURE}},
    }
    _url, body = _replay(_followup_turn(echoed))

    assert body["contents"][1]["parts"][0]["thoughtSignature"] == SIGNATURE
    assert "signature" not in json.dumps(body)


def test_a_denied_tool_is_replayed_as_the_result_the_executor_returned(monkeypatch) -> None:
    """Refusal is data the model reads, never a success the gateway asserts."""
    _google_live(monkeypatch)
    messages = _followup_turn(_call("call_native", signature=SIGNATURE))
    messages[2] = {"role": "tool", "tool_call_id": "call_native",
                   "name": "pc_files", "content": "사용자가 승인을 거부했습니다."}
    _url, body = _replay(messages)

    part = body["contents"][2]["parts"][0]["functionResponse"]
    assert part["response"] == {"result": "사용자가 승인을 거부했습니다."}
    assert part["id"] == "call_native" and part["name"] == "pc_files"


def test_korean_arguments_and_results_reach_the_wire_unchanged(monkeypatch) -> None:
    """A call the model asked for in Korean is replayed and decoded in Korean."""
    _google_live(monkeypatch)
    path = "문서/견적 3분기.txt"
    messages = _followup_turn(
        _call("call_native", arguments=json.dumps({"path": path}, ensure_ascii=False),
              signature=SIGNATURE)
    )
    messages[2]["content"] = "한글 결과 ∑ ✓"
    _url, body = _replay(messages)

    assert body["contents"][1]["parts"][0]["functionCall"]["args"] == {"path": path}
    assert body["contents"][2]["parts"][0]["functionResponse"]["response"] == {
        "result": "한글 결과 ∑ ✓",
    }

    decoded = _GoogleToolStream({"pc_files"}).decode(_native_frame([{
        "functionCall": {"id": "call_native", "name": "pc_files", "args": {"path": path}},
        "thoughtSignature": "생각 서명",
    }]))[0].tool_call
    assert json.loads(decoded.arguments) == {"path": path}
    assert decoded.signature == "생각 서명"
