from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.b14_runtime_config import runtime_config as rcfg


STREAM_URL = "/api/pilot/v1/chat/completions/stream-preview"
CHAT_URL = "/api/pilot/v1/chat/completions"
MODEL = "test-fixture/kilo-stream-gateway"
MODEL_UPSTREAM = "test-fixture/kilo-stream-response"
LIVE_DUMMY_KEY = "unit-live-key-abcdef1234567890"


class _ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes], *, error_after: Exception | None = None):
        self.chunks = chunks
        self.error_after = error_after
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.error_after is not None:
            raise self.error_after

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _synthetic_catalog_stream_route(monkeypatch):
    """Isolated synthetic keyless fixture; NEVER restore owner-deleted Kilo IDs."""
    from dataclasses import replace
    import app.pilot.catalog as cat
    from app.pilot import platform_secrets as ps
    base = next(iter(cat.CATALOG_BY_ID.values()))
    fixture = replace(
        base, model_id=MODEL, upstream_model=MODEL_UPSTREAM,
        display_name="Synthetic SSE test-only model",
        provider="Fixture Test Provider", platform_provider_id="test-fixture",
        capabilities=frozenset({"chat", "free"}),
        input_price_usd_per_1m=0.0, output_price_usd_per_1m=0.0,
    )
    spec = ps.PlatformProviderSpec(
        provider_id="test-fixture",credential_source=ps.CredentialSource.NONE,
        credential_binding_name="",base_origin="https://stream-fixture.example/v1",
        allowed_hosts=("stream-fixture.example",),
    )
    monkeypatch.setitem(cat.CATALOG_BY_ID,MODEL,fixture)
    monkeypatch.setitem(ps._PLATFORM_PROVIDERS,"test-fixture",spec)
    yield


@pytest.fixture(autouse=True)
def _reset_runtime_config(monkeypatch):
    monkeypatch.delenv("KILO_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    saved = {
        "provider_mode": rcfg.provider_mode,
        "max_response_bytes": rcfg.max_response_bytes,
    }
    rcfg.provider_mode = "mock"
    rcfg.max_response_bytes = 1024 * 1024
    yield
    rcfg.provider_mode = saved["provider_mode"]
    rcfg.max_response_bytes = saved["max_response_bytes"]


def _payload(**overrides):
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "안녕하세요"}],
        "stream": True,
    }
    payload.update(overrides)
    return payload


def _client(transport: httpx.AsyncBaseTransport | None = None) -> TestClient:
    app = create_app()
    if transport is not None:
        app.state.stream_transport = transport
    return TestClient(app)


def _json_data_frames(text: str) -> list[dict]:
    frames: list[dict] = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        value = line[6:]
        if value == "[DONE]":
            continue
        frames.append(json.loads(value))
    return frames


def _valid_sse_chunks(content: str = "실제처럼 보이는 테스트") -> list[bytes]:
    first = {
        "id": "upstream_stream_1",
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content},
                "finish_reason": None,
            }
        ],
    }
    finish = {
        "id": "upstream_stream_1",
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 3,
            "completion_tokens": 4,
            "total_tokens": 7,
        },
    }
    return [
        f"data: {json.dumps(first)}\n\n".encode(),
        f"data: {json.dumps(finish)}\n\n".encode(),
        b"data: [DONE]\n\n",
    ]


# #5573 slice 3-A: exercise the real HTTP gateway and Google wire with no live POST.
GOOGLE_TOOL_MODEL = "google/gemini-3.1-flash-lite"
PC_TOOL = {"type": "function", "function": {
    "name": "pc_files", "description": "Inspect the requested PC scope.",
    "parameters": {"type": "object", "properties": {"plan": {"type": "string"}}, "required": ["plan"]},
}}


def _google_live(monkeypatch):
    from app.pilot import stream_gateway
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_05", "unit-google-key-not-a-secret")
    monkeypatch.setattr(rcfg, "provider_mode", "live")
    monkeypatch.setattr(stream_gateway, "_request_id", lambda: "b14stream_fixed")


def _native_frame(parts=None, *, finish=None, usage=None):
    candidate = {"index": 0, "content": {"role": "model", "parts": parts or []}}
    if finish is not None:
        candidate["finishReason"] = finish
    payload = {"responseId": "native_response", "modelVersion": "gemini-3.1-flash-lite", "candidates": [candidate]}
    if usage is not None:
        payload["usageMetadata"] = usage
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode()


@pytest.mark.parametrize("url", [STREAM_URL, CHAT_URL])
@pytest.mark.parametrize("extra", [{}, {"tools": None}, {"tools": []}], ids=["omitted", "null", "empty"])
def test_tools_absent_preserves_google_stream_bytes(monkeypatch, extra, url):
    _google_live(monkeypatch)
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(200, stream=_ChunkStream(_valid_sse_chunks("안녕")))
    response = _client(httpx.MockTransport(handler)).post(
        url, json=_payload(model=GOOGLE_TOOL_MODEL, **extra),
    )
    assert response.status_code == 200, response.text
    assert len(sent) == 1
    assert str(sent[0].url) == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert sent[0].content == b'{"model":"gemini-3.1-flash-lite","messages":[{"role":"user","content":"' + "안녕하세요".encode() + b'"}],"stream":true}'
    # Exact legacy wire snapshot; request ID is fixed, no event names or new keys.
    assert response.content == LEGACY_GOOGLE_STREAM_BYTES


@pytest.mark.parametrize("url", [STREAM_URL, CHAT_URL])
@pytest.mark.parametrize("choice,config", [
    (None, None),
    ("auto", {"mode": "AUTO"}),
    ("required", {"mode": "ANY"}),
    ({"type": "function", "function": {"name": "pc_files"}}, {"mode": "ANY", "allowedFunctionNames": ["pc_files"]}),
])
def test_google_tools_emit_tool_call_event(monkeypatch, choice, config, url):
    _google_live(monkeypatch)
    sent = []
    stream = _ChunkStream([
        _native_frame([{"text": "숨긴 추론", "thought": True}]),
        _native_frame([{"functionCall": {"id": "call_native", "name": "pc_files", "args": {"plan": "files_list"}}}]),
        _native_frame(finish="STOP", usage={"promptTokenCount": 3, "candidatesTokenCount": 4, "totalTokenCount": 7}),
    ])
    def handler(request):
        sent.append(request)
        return httpx.Response(200, stream=stream)
    response = _client(httpx.MockTransport(handler)).post(
        url, json=_payload(model=GOOGLE_TOOL_MODEL, tools=[PC_TOOL], tool_choice=choice),
    )
    assert response.status_code == 200, response.text
    assert len(sent) == 1 and stream.closed
    assert str(sent[0].url) == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:streamGenerateContent?alt=sse"
    assert sent[0].headers["x-goog-api-key"] == "unit-google-key-not-a-secret"
    assert "authorization" not in sent[0].headers
    body = json.loads(sent[0].content)
    assert body["contents"] == [{"role": "user", "parts": [{"text": "안녕하세요"}]}]
    assert body["tools"] == [{"functionDeclarations": [{"name": "pc_files", "description": PC_TOOL["function"]["description"], "parametersJsonSchema": PC_TOOL["function"]["parameters"]}]}]
    assert body.get("toolConfig") == ({"functionCallingConfig": config} if config else None)
    assert "generationConfig" not in body
    assert response.text.startswith('event: tool_call\ndata: {"id":"call_native","name":"pc_files","arguments":"{\\"plan\\":\\"files_list\\"}","index":0}\n\n')
    assert response.text.endswith('event: done\ndata: {"finish_reason":"tool_calls"}\n\n')
    assert "숨긴 추론" not in response.text
    assert "unit-google-key" not in response.text


def test_tools_non_google_still_refused_before_dispatch(monkeypatch):
    _google_live(monkeypatch)
    calls = []
    response = _client(httpx.MockTransport(lambda req: calls.append(req))).post(
        STREAM_URL, json=_payload(model="tokenharbor/deepseek-v4.1-flash:free", tools=[PC_TOOL]),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "stream_not_supported"
    assert calls == []


def test_tools_undeclared_google_capability_refused_before_dispatch(monkeypatch):
    _google_live(monkeypatch)
    calls = []
    # Gemma 26B declares no tools; the owner-decided 31B does (#6460-5).
    response = _client(httpx.MockTransport(lambda req: calls.append(req))).post(
        STREAM_URL, json=_payload(model="google/gemma-4-26b-a4b-it", tools=[PC_TOOL]),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "tools_not_supported"
    assert calls == []


def test_gemma_31b_tools_reach_the_google_native_wire(monkeypatch):
    _google_live(monkeypatch)
    calls = []
    stream = _ChunkStream([
        _native_frame([{"functionCall": {"name": "pc_files", "args": {"plan": "files_list"}}}]),
    ])
    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=stream)
    response = _client(httpx.MockTransport(handler)).post(
        STREAM_URL, json=_payload(model="google/gemma-4-31b-it", tools=[PC_TOOL]),
    )
    assert response.status_code == 200
    assert response.text.startswith("event: tool_call\n")
    assert len(calls) == 1 and stream.closed


def test_google_tool_call_commits_stream_and_failure_never_falls_back(monkeypatch):
    _google_live(monkeypatch)
    calls = []
    stream = _ChunkStream([
        _native_frame([{"functionCall": {"name": "pc_files", "args": {"plan": "files_list"}}}]),
    ], error_after=httpx.ReadTimeout("synthetic timeout"))
    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=stream)
    response = _client(httpx.MockTransport(handler)).post(
        STREAM_URL, json=_payload(model=GOOGLE_TOOL_MODEL, tools=[PC_TOOL]),
    )
    assert response.status_code == 200
    assert response.text.startswith("event: tool_call\n")
    assert "event: error" in response.text
    assert '"after_stream_start":true' in response.text
    assert "event: done" not in response.text and "[DONE]" not in response.text
    assert len(calls) == 1 and stream.closed


@pytest.mark.parametrize("parts", [
    [{"functionCall": {"name": "not_declared", "args": {}}}],
    [{"functionCall": {"name": "pc_files", "args": "partial"}}],
    [{"functionCall": {"id": "unsafe id", "name": "pc_files", "args": {}}}],
    [{"functionCall": {"name": "pc_files", "partialArgs": []}}],
])
def test_google_invalid_tool_response_is_an_upstream_error(monkeypatch, parts):
    _google_live(monkeypatch)
    stream = _ChunkStream([_native_frame(parts, finish="STOP")])
    response = _client(httpx.MockTransport(lambda req: httpx.Response(200, stream=stream))).post(
        STREAM_URL, json=_payload(model=GOOGLE_TOOL_MODEL, tools=[PC_TOOL], business14={"product_tier": "plus"}),
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "malformed_upstream_response"
    assert stream.closed


def test_google_tool_stream_preserves_text_and_explicit_parameters(monkeypatch):
    _google_live(monkeypatch)
    sent = []
    wire = _native_frame([{"text": "안녕"}]) + _native_frame(finish="STOP")
    stream = _ChunkStream([wire[:7], wire[7:80], wire[80:81], wire[81:]])
    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, stream=stream)
    response = _client(httpx.MockTransport(handler)).post(STREAM_URL, json=_payload(
        model=GOOGLE_TOOL_MODEL, tools=[PC_TOOL], tool_choice="none",
        messages=[{"role": "system", "content": "System instruction"},
                  {"role": "user", "content": "Question"}, {"role": "assistant", "content": "Prior answer"},
                  {"role": "user", "content": "Next question"}],
        temperature=0.3, max_tokens=100, reasoning_effort="low",
    ))
    assert response.status_code == 200, response.text
    assert sent[0]["systemInstruction"] == {"parts": [{"text": "System instruction"}]}
    assert [item["role"] for item in sent[0]["contents"]] == ["user", "model", "user"]
    assert sent[0]["generationConfig"] == {"temperature": 0.3, "maxOutputTokens": 100, "thinkingConfig": {"thinkingLevel": "LOW"}}
    assert sent[0]["toolConfig"] == {"functionCallingConfig": {"mode": "NONE"}}
    frames = _json_data_frames(response.text)
    assert frames[0]["choices"][0]["delta"] == {"content": "안녕"}
    assert frames[-1] == {"finish_reason": "stop"}
    assert "event: tool_call" not in response.text
    assert stream.closed


def test_google_missing_finish_is_not_successful_done(monkeypatch):
    _google_live(monkeypatch)
    stream = _ChunkStream([_native_frame([{"functionCall": {"name": "pc_files", "args": {}}}])])
    response = _client(httpx.MockTransport(lambda req: httpx.Response(200, stream=stream))).post(
        STREAM_URL, json=_payload(model=GOOGLE_TOOL_MODEL, tools=[PC_TOOL]),
    )
    assert response.status_code == 200
    assert "event: tool_call" in response.text and "event: error" in response.text
    assert "event: done" not in response.text
    assert stream.closed


LEGACY_GOOGLE_STREAM_BYTES = (
    'data: {"id":"upstream_stream_1","object":"chat.completion.chunk","model":"test-fixture/kilo-stream-gateway","choices":[{"index":0,"delta":{"content":"안녕"},"finish_reason":null}],"business14":{"request_id":"b14stream_fixed","route_mode":"manual","selected_provider":"Google AI Studio","selected_model":"google/gemini-3.1-flash-lite","selected_upstream_model":"gemini-3.1-flash-lite","selected_route_id":"platform:google/gemini-3.1-flash-lite","fallback_allowed":true,"fallback_used":false,"attempt_count":1,"provider_mode":"live","route_evidence_status":"live_streaming_preview"}}\n\n'
    'data: {"id":"upstream_stream_1","object":"chat.completion.chunk","model":"test-fixture/kilo-stream-gateway","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"business14":{"request_id":"b14stream_fixed","route_mode":"manual","selected_provider":"Google AI Studio","selected_model":"google/gemini-3.1-flash-lite","selected_upstream_model":"gemini-3.1-flash-lite","selected_route_id":"platform:google/gemini-3.1-flash-lite","fallback_allowed":true,"fallback_used":false,"attempt_count":1,"provider_mode":"live","route_evidence_status":"live_streaming_preview"},"usage":{"prompt_tokens":3,"completion_tokens":4,"total_tokens":7}}\n\n'
    'data: [DONE]\n\n'
).encode("utf-8")


def test_mock_preview_is_sse_manual_route_with_done_and_metadata():
    client = _client()
    response = client.post(STREAM_URL, json=_payload())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-store"
    assert "data: [DONE]" in response.text

    frames = _json_data_frames(response.text)
    assert frames
    first = frames[0]
    assert first["object"] == "chat.completion.chunk"
    assert first["choices"][0]["delta"]["content"].startswith("이것은 Mock 스트리밍 응답")
    metadata = first["business14"]
    assert metadata["route_mode"] == "manual"
    assert metadata["selected_model"] == MODEL
    assert metadata["fallback_allowed"] is False
    assert metadata["fallback_used"] is False
    assert metadata["attempt_count"] == 1
    assert metadata["provider_mode"] == "mock"
    assert metadata["route_evidence_status"] == "mock_no_upstream_call"


def test_a_caller_cannot_narrow_the_tier_fallback_with_an_attempt_count(monkeypatch):
    """#4317: the candidate list decides, so an attempt count narrows nothing.

    The route advertises the owner-tier fallback and the caller cannot pin it
    away with a number. The primary still answers here, so the attempt count
    is 1, but the fallback stays available for a recoverable primary failure.
    """
    from dataclasses import replace
    from app.pilot import stream_gateway

    fallback = {
        "model_id": "test-fixture/fallback",
        "upstream_model": "test-fixture/fallback-upstream",
        "provider": "Fixture Backup Provider",
        "platform_provider_id": "test-fixture",
        "route_id": "platform:test-fixture/fallback",
        "reason": "owner_selected_tier_fallback",
    }
    original = stream_gateway.rcore.resolve_route

    def resolve_with_tier_pair(model_id, opts):
        base = original(model_id, opts)
        return replace(
            base,
            reason_codes=[*base.reason_codes, "owner_selected_tier_fallback:free"],
            fallback_allowed=True,
            eligible_fallback=[fallback],
        )

    monkeypatch.setattr(stream_gateway.rcore, "resolve_route", resolve_with_tier_pair)
    response = _client().post(STREAM_URL, json=_payload())
    assert response.status_code == 200, response.text
    frames = _json_data_frames(response.text)
    assert frames and "data: [DONE]" in response.text
    assert frames[0]["business14"]["attempt_count"] == 1
    assert frames[0]["business14"]["fallback_used"] is False
    # The tier fallback is still advertised: no caller option can narrow the
    # owner roster (B4/B5 removed the retired knobs outright).
    assert frames[0]["business14"]["fallback_allowed"] is True


def test_canonical_stream_true_does_not_promote_auto_route():
    client = _client()
    response = client.post(CHAT_URL, json=_payload(model="b14/auto"))

    # B7: the retired id has no special case anywhere — a non-catalog model
    # never enters the stream opt-in and the canonical validator refuses
    # stream=true as always.
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "stream_not_supported"


def test_preview_requires_stream_true():
    client = _client()
    payload = _payload()
    payload.pop("stream")
    response = client.post(STREAM_URL, json=payload)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize(
    "payload_update",
    [
        {"model": "b14/auto"},
    ],
)
def test_auto_or_external_fallback_streaming_is_rejected_before_network(payload_update):
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    rcfg.provider_mode = "live"
    rcfg.api_key = LIVE_DUMMY_KEY
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload(**payload_update))

    # B7: the retired auto id is an unknown model now — the stream surface
    # refuses it before any network call.
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_model"
    assert calls == 0


@pytest.mark.asyncio
async def test_external_fallback_value_on_stream_preview_is_dropped_in_grace():
    """B5 grace: a caller still sending the retired knob gets the value logged
    and dropped; the stream proceeds as one manual attempt with no fallback."""
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"".join(_valid_sse_chunks()),
        )

    rcfg.provider_mode = "live"
    rcfg.api_key = LIVE_DUMMY_KEY
    client = _client(httpx.MockTransport(handler))
    response = client.post(
        STREAM_URL, json=_payload(business14={"allow_external_fallback": True})
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    # The dropped value cannot enable any fallback walk: the manual stream ran
    # exactly once against the single declared route.
    assert calls == 1




def test_owner_tier_fallback_is_tried_before_first_visible_token(monkeypatch):
    from dataclasses import replace
    from app.pilot import stream_gateway
    from app.pilot.errors import PilotError
    from app.pilot.stream_types import StreamEvent

    fallback = {
        "model_id": "test-fixture/fallback",
        "upstream_model": "test-fixture/fallback-upstream",
        "provider": "Fixture Backup Provider",
        "platform_provider_id": "test-fixture",
        "route_id": "platform:test-fixture/fallback",
        "reason": "owner_selected_tier_fallback",
    }
    original = stream_gateway.rcore.resolve_route

    def resolve_with_tier_pair(model_id, opts):
        base = original(model_id, opts)
        return replace(
            base,
            reason_codes=[*base.reason_codes, "owner_selected_tier_fallback:free"],
            fallback_allowed=True,
            eligible_fallback=[fallback],
        )

    monkeypatch.setattr(stream_gateway.rcore, "resolve_route", resolve_with_tier_pair)
    from types import SimpleNamespace
    original_catalog = stream_gateway.get_catalog_by_id
    def fixture_catalog(model_id):
        if model_id == fallback["model_id"]:
            return SimpleNamespace(model_id=fallback["model_id"], enabled=True,
                provider=fallback["provider"], upstream_model=fallback["upstream_model"],
                platform_provider_id=fallback["platform_provider_id"])
        return original_catalog(model_id)
    monkeypatch.setattr(stream_gateway, "get_catalog_by_id", fixture_catalog)
    original_credential = stream_gateway.rcore._credential_status_for
    monkeypatch.setattr(stream_gateway.rcore, "_credential_status_for",
        lambda cm: (True, "key_available", "platform_secret", "test-fixture")
        if cm.model_id == fallback["model_id"] else original_credential(cm))
    attempts = []

    async def fake_stream(**kwargs):
        attempts.append(kwargs["model_id"])
        if kwargs["model_id"] == MODEL:
            raise PilotError("upstream_server_error", "temporary upstream failure", 502)
        yield StreamEvent(delta_content="backup token", model=kwargs["upstream_model"])
        yield StreamEvent(done=True)

    monkeypatch.setattr(stream_gateway, "stream_platform_chat_completions", fake_stream)
    rcfg.provider_mode = "live"
    response = _client().post(
        STREAM_URL,
        json=_payload(),
    )

    assert response.status_code == 200, response.text
    frames = _json_data_frames(response.text)
    assert frames[0]["choices"][0]["delta"]["content"] == "backup token"
    metadata = frames[0]["business14"]
    assert metadata["selected_model"] == fallback["model_id"]
    assert metadata["attempt_count"] == 2
    assert metadata["fallback_used"] is True
    assert metadata["fallback_allowed"] is False
    assert attempts == [MODEL, fallback["model_id"]]
    assert "data: [DONE]" in response.text


def test_owner_tier_fallback_is_not_tried_after_first_visible_token(monkeypatch):
    from dataclasses import replace
    from app.pilot import stream_gateway
    from app.pilot.errors import PilotError
    from app.pilot.stream_types import StreamEvent

    fallback = {
        "model_id": "test-fixture/fallback",
        "upstream_model": "test-fixture/fallback-upstream",
        "provider": "Fixture Backup Provider",
        "platform_provider_id": "test-fixture",
        "route_id": "platform:test-fixture/fallback",
        "reason": "owner_selected_tier_fallback",
    }
    original = stream_gateway.rcore.resolve_route

    def resolve_with_tier_pair(model_id, opts):
        base = original(model_id, opts)
        return replace(
            base,
            reason_codes=[*base.reason_codes, "owner_selected_tier_fallback:free"],
            fallback_allowed=True,
            eligible_fallback=[fallback],
        )

    monkeypatch.setattr(stream_gateway.rcore, "resolve_route", resolve_with_tier_pair)
    from types import SimpleNamespace
    original_catalog = stream_gateway.get_catalog_by_id
    def fixture_catalog(model_id):
        if model_id == fallback["model_id"]:
            return SimpleNamespace(model_id=fallback["model_id"], enabled=True,
                provider=fallback["provider"], upstream_model=fallback["upstream_model"],
                platform_provider_id=fallback["platform_provider_id"])
        return original_catalog(model_id)
    monkeypatch.setattr(stream_gateway, "get_catalog_by_id", fixture_catalog)
    original_credential = stream_gateway.rcore._credential_status_for
    monkeypatch.setattr(stream_gateway.rcore, "_credential_status_for",
        lambda cm: (True, "key_available", "platform_secret", "test-fixture")
        if cm.model_id == fallback["model_id"] else original_credential(cm))
    attempts = []

    async def fake_stream(**kwargs):
        attempts.append(kwargs["model_id"])
        yield StreamEvent(delta_content="primary token", model=kwargs["upstream_model"])
        raise PilotError("upstream_server_error", "temporary upstream failure", 502)

    monkeypatch.setattr(stream_gateway, "stream_platform_chat_completions", fake_stream)
    rcfg.provider_mode = "live"
    response = _client().post(
        STREAM_URL,
        json=_payload(),
    )

    assert response.status_code == 200, response.text
    assert "primary token" in response.text
    assert "event: error" in response.text
    assert '"after_stream_start":true' in response.text
    assert attempts == [MODEL]
    assert "data: [DONE]" not in response.text


def test_legacy_non_catalog_route_is_rejected_before_network():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    rcfg.provider_mode = "live"
    rcfg.api_key = LIVE_DUMMY_KEY
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload(model="legacy-provider-model"))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_model"
    assert calls == 0


@pytest.mark.parametrize(
    ("upstream_status", "expected_status", "expected_code"),
    [
        (401, 401, "upstream_auth_failed"),
        (403, 401, "upstream_auth_failed"),
        # The Kilo Gateway route reports its own quota code for 429.
        (429, 429, "upstream_rate_limited"),
        (500, 502, "upstream_server_error"),
        (400, 502, "malformed_upstream_response"),
        (422, 502, "upstream_client_error"),
    ],
)
def test_pre_start_upstream_errors_keep_json_http_status(
    upstream_status: int,
    expected_status: int,
    expected_code: str,
):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream_status, content=b"bounded error")

    rcfg.provider_mode = "live"
    rcfg.api_key = LIVE_DUMMY_KEY
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload())

    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == expected_code


def test_malformed_first_event_fails_before_sse_200():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data: not-json\n\n")

    rcfg.provider_mode = "live"
    rcfg.api_key = LIVE_DUMMY_KEY
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload())

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "malformed_upstream_response"


def test_post_start_pilot_error_emits_bounded_error_event_without_done():
    first = _valid_sse_chunks("첫 토큰")[0]
    stream = _ChunkStream([first, b"data: not-json\n\n"])

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    rcfg.provider_mode = "live"
    rcfg.api_key = LIVE_DUMMY_KEY
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload())

    assert response.status_code == 200
    assert "첫 토큰" in response.text
    assert "event: error" in response.text
    assert '"code":"malformed_upstream_response"' in response.text
    assert '"after_stream_start":true' in response.text
    assert "data: [DONE]" not in response.text
    assert stream.closed is True


def test_post_start_unexpected_error_is_generic_and_secret_free():
    secret_marker = "DO-NOT-EXPOSE-SECRET-MARKER"
    first = _valid_sse_chunks("첫 토큰")[0]
    stream = _ChunkStream([first], error_after=RuntimeError(secret_marker))

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    rcfg.provider_mode = "live"
    rcfg.api_key = LIVE_DUMMY_KEY
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload())

    assert response.status_code == 200
    assert "event: error" in response.text
    assert '"code":"internal_error"' in response.text
    assert secret_marker not in response.text
    assert "data: [DONE]" not in response.text
    assert stream.closed is True


def test_live_preview_keyless_route_sends_no_key(monkeypatch):
    """Keyless Kilo route: no Authorization header, no key leakage.

    The Kilo provider spec is CredentialSource.NONE, so the legacy
    OpenRouter key plane is never forwarded to it.
    """
    stale_key = "unit-live-secret-abcdef1234567890"
    monkeypatch.setenv("KILO_API_KEY", stale_key)
    seen_authorization = None
    stream = _ChunkStream(_valid_sse_chunks("안전한 청크"))

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_authorization
        seen_authorization = request.headers.get("authorization")
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["model"] == MODEL_UPSTREAM
        return httpx.Response(200, stream=stream)

    rcfg.provider_mode = "live"
    rcfg.api_key = stale_key  # must stay on the OpenRouter plane
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload())

    assert response.status_code == 200
    assert seen_authorization is None
    assert stale_key not in response.text
    assert "안전한 청크" in response.text
    assert "data: [DONE]" in response.text


def test_live_preview_missing_key_is_anonymous_with_zero_key_material():
    """Keyless Kilo route: a missing key is not an error.

    Decision #1933 removed every secret-backed route, so the contract is
    "zero key material": exactly one anonymous call, no Authorization
    header, nothing returned to the client. The secret-required
    fail-closed path stays covered by
    test_platform_provider_credential_plane.py (Agnes).
    """
    calls = 0
    seen_authorization = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls, seen_authorization
        calls += 1
        seen_authorization = request.headers.get("authorization")
        return httpx.Response(200, stream=_ChunkStream(_valid_sse_chunks("익명 청크")))

    rcfg.provider_mode = "live"
    rcfg.api_key = ""
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload())

    assert response.status_code == 200
    assert calls == 1
    assert seen_authorization is None
    assert "data: [DONE]" in response.text


# #4379 owner rule: normal long generation uses a streaming-capable route
# instead of silently rejecting a healthy answer at the completed JSON buffer.

def test_canonical_stream_true_manual_route_works_without_json_materialization():
    rcfg.provider_mode = "mock"
    response = _client().post(CHAT_URL, json=_payload())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data: [DONE]" in response.text
    frames = _json_data_frames(response.text)
    assert frames[0]["object"] == "chat.completion.chunk"
    assert frames[0]["business14"]["fallback_used"] is False


def test_canonical_stream_true_above_completed_json_budget_not_rejected():
    from app.pilot.platform import MAX_COMPLETED_RESPONSE_BYTES

    rcfg.provider_mode = "live"
    piece = "S" * (32 * 1024)
    frames_needed = MAX_COMPLETED_RESPONSE_BYTES // len(piece) + 16
    model_frames = _valid_sse_chunks(piece)
    assert len(model_frames) == 3
    # Each individual frame is memory safe; total generated text exceeds 8MiB.
    body = model_frames[0] * frames_needed + model_frames[1] + model_frames[2]
    assert len(body) > MAX_COMPLETED_RESPONSE_BYTES
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(
            200, content=body,
            headers={"content-type": "text/event-stream"},
        )

    response = _client(httpx.MockTransport(handler)).post(CHAT_URL, json=_payload())
    assert response.status_code == 200
    assert "data: [DONE]" in response.text
    assert response.text.count('"object":"chat.completion.chunk"') >= frames_needed
    assert len(seen) == 1
    assert json.loads(seen[0].content)["stream"] is True



def test_canonical_stream_false_remains_completed_json():
    rcfg.provider_mode = "mock"
    response = _client().post(CHAT_URL, json=_payload(stream=False))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["choices"][0]["message"]["content"]


def test_canonical_stream_true_does_not_enable_fallback_or_extra_calls():
    rcfg.provider_mode = "mock"
    response = _client().post(CHAT_URL, json=_payload(
        business14={"allow_external_fallback": True},
    ))
    # B5 grace: the retired knob is logged and dropped, so the canonical stream
    # opt-in still serves the manual route with no fallback semantics.
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")


def test_canonical_stream_true_does_not_enable_byok_without_secret():
    response = _client().post(CHAT_URL, json=_payload(model="some-byok-model"))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "stream_not_supported"



def test_canonical_stream_reuses_asgi_parsed_body_without_request_json(monkeypatch):
    from starlette.requests import Request

    async def reject_convenience_json(self):
        raise AssertionError("Python Worker request.json must not be used on canonical path")

    monkeypatch.setattr(Request, "json", reject_convenience_json)
    rcfg.provider_mode = "mock"
    response = _client().post(CHAT_URL, json=_payload())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data: [DONE]" in response.text
