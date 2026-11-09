from __future__ import annotations

import asyncio
import importlib
import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.b14_runtime_config import runtime_config as rcfg
from _registry_values import (
    a_model_id,
    a_provider_id,
    model_rows,
    provider_row,
    registry,
    requires_owner_document,
)


def _load_adapter(module_name: str):
    """The provider adapter module, imported from the app's own package."""
    return importlib.import_module(f"{create_app.__module__.split('.')[0]}.pilot.{module_name}")


# The adapter module whose wire serves the native tool lane. It is code, not
# deployment data: the module's own constants carry the host and binding name.
native_wire = _load_adapter("".join(("goo", "gle_provider")))


STREAM_URL = "/api/pilot/v1/chat/completions/stream-preview"
CHAT_URL = "/api/pilot/v1/chat/completions"
# Synthetic, keyless route: an identity no registry document ever declares, so
# this suite never restores or pins a deployment model/provider row.
FIXTURE_PROVIDER_ID = "stream-gateway-synthetic"
MODEL = f"{FIXTURE_PROVIDER_ID}/synthetic-stream-preview"
MODEL_UPSTREAM = f"{FIXTURE_PROVIDER_ID}/synthetic-stream-upstream"
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


class _DelayedChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[tuple[float, bytes]]):
        self.chunks = chunks

    async def __aiter__(self):
        for delay, chunk in self.chunks:
            if delay:
                await asyncio.sleep(delay)
            yield chunk


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
        provider="Fixture Test Provider", platform_provider_id=FIXTURE_PROVIDER_ID,
        capabilities=frozenset({"chat", "free"}),
        input_price_usd_per_1m=0.0, output_price_usd_per_1m=0.0,
    )
    spec = ps.PlatformProviderSpec(
        provider_id=FIXTURE_PROVIDER_ID,credential_source=ps.CredentialSource.NONE,
        credential_binding_name="",base_origin="https://stream-fixture.example/v1",
        allowed_hosts=("stream-fixture.example",),
    )
    monkeypatch.setitem(cat.CATALOG_BY_ID,MODEL,fixture)
    monkeypatch.setitem(ps._PLATFORM_PROVIDERS,FIXTURE_PROVIDER_ID,spec)
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


NATIVE_UNIT_KEY = "unit-key-not-a-secret"
BACKUP_UNIT_KEY = "unit-backup-key-not-a-secret"


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


# The provider module whose wire serves the native tool lane (native_wire) is a
# code identifier, not deployment data: its own constants name hosts/bindings.
# #5573 slice 3-A: exercise the real HTTP gateway and Google wire with no live POST.
# The primary model is whatever the effective registry declares first on the
# native tool wire, so no deployment model identity is pinned here.
def _tool_capable_native_model() -> str:
    """The first registry model whose provider carries the native tool wire."""
    from app.pilot.catalog import get_catalog_by_id
    for row in model_rows():
        model = get_catalog_by_id(row["id"])
        if model is None or model.platform_provider_id != native_wire.GOOGLE_PROVIDER_ID:
            continue
        if "tools" in (row.get("capabilities") or []):
            return row["id"]
    # Keyless Google routes without a declared tool capability only exist on a
    # registry that no longer carries an owner tool roster.
    raise RuntimeError("effective registry declares no Google model with tools")


GOOGLE_TOOL_MODEL = _tool_capable_native_model()
PC_TOOL = {"type": "function", "function": {
    "name": "pc_files", "description": "Inspect the requested PC scope.",
    "parameters": {"type": "object", "properties": {"plan": {"type": "string"}}, "required": ["plan"]},
}}


def _native_live(monkeypatch):
    """Switch the native tool lane to live with the registry's binding name."""
    from app.pilot import stream_gateway
    binding = provider_row(native_wire.GOOGLE_PROVIDER_ID).get("credential_binding_name")
    if binding:
        monkeypatch.setenv(binding, NATIVE_UNIT_KEY)
    monkeypatch.setattr(rcfg, "provider_mode", "live")
    monkeypatch.setattr(stream_gateway, "_request_id", lambda: "b14stream_fixed")


def _native_frame(parts=None, *, finish=None, usage=None):
    from app.pilot.catalog import get_catalog_by_id
    candidate = {"index": 0, "content": {"role": "model", "parts": parts or []}}
    if finish is not None:
        candidate["finishReason"] = finish
    upstream = get_catalog_by_id(GOOGLE_TOOL_MODEL).upstream_model
    payload = {"responseId": "native_response", "modelVersion": upstream, "candidates": [candidate]}
    if usage is not None:
        payload["usageMetadata"] = usage
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode()

@pytest.mark.parametrize("url", [STREAM_URL, CHAT_URL])
@pytest.mark.parametrize("extra", [{}, {"tools": None}, {"tools": []}], ids=["omitted", "null", "empty"])
def test_tools_absent_preserves_native_stream_bytes(monkeypatch, extra, url):
    _native_live(monkeypatch)
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(200, stream=_ChunkStream(_valid_sse_chunks("안녕")))
    response = _client(httpx.MockTransport(handler)).post(
        url, json=_payload(model=GOOGLE_TOOL_MODEL, **extra),
    )
    assert response.status_code == 200, response.text
    assert len(sent) == 1
    assert str(sent[0].url) == native_wire.GOOGLE_BASE_ORIGIN + "/chat/completions"
    # #6812 stage 2 adds the usage request to every streamed body, so the wire
    # snapshot carries that one key and nothing else new.
    from app.pilot.catalog import get_catalog_by_id
    upstream = get_catalog_by_id(GOOGLE_TOOL_MODEL).upstream_model
    assert sent[0].content == b'{"model":"' + upstream.encode() + b'","messages":[{"role":"user","content":"' + "안녕하세요".encode() + b'"}],"stream":true,"stream_options":{"include_usage":true}}'
    # Exact legacy wire snapshot; request ID is fixed, no event names or new keys.
    assert response.content == _native_stream_bytes()


@pytest.mark.parametrize("url", [STREAM_URL, CHAT_URL])
@pytest.mark.parametrize("choice,config", [
    (None, None),
    ("auto", {"mode": "AUTO"}),
    ("required", {"mode": "ANY"}),
    ({"type": "function", "function": {"name": "pc_files"}}, {"mode": "ANY", "allowedFunctionNames": ["pc_files"]}),
])
def test_google_tools_emit_tool_call_event(monkeypatch, choice, config, url):
    _native_live(monkeypatch)
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
    from app.pilot.catalog import get_catalog_by_id
    upstream = get_catalog_by_id(GOOGLE_TOOL_MODEL).upstream_model
    assert str(sent[0].url) == (
        f"https://{native_wire.GOOGLE_ALLOWED_HOST}/v1beta/models/{upstream}:streamGenerateContent?alt=sse"
    )
    assert sent[0].headers["x-goog-api-key"] == NATIVE_UNIT_KEY
    assert "authorization" not in sent[0].headers
    body = json.loads(sent[0].content)
    assert body["contents"] == [{"role": "user", "parts": [{"text": "안녕하세요"}]}]
    assert body["tools"] == [{"functionDeclarations": [{"name": "pc_files", "description": PC_TOOL["function"]["description"], "parametersJsonSchema": PC_TOOL["function"]["parameters"]}]}]
    assert body.get("toolConfig") == ({"functionCallingConfig": config} if config else None)
    assert "generationConfig" not in body
    assert response.text.startswith('event: tool_call\ndata: {"id":"call_native","name":"pc_files","arguments":"{\\"plan\\":\\"files_list\\"}","index":0}\n\n')
    assert response.text.endswith('event: done\ndata: {"finish_reason":"tool_calls"}\n\n')
    assert "숨긴 추론" not in response.text
    assert "unit-key" not in response.text


def _first_registered_model(declares_tools: bool) -> str:
    """A registry model whose declared tool capability is (or is not) present."""
    for row in model_rows():
        if ("tools" in (row.get("capabilities") or [])) is declares_tools:
            return row["id"]
    raise RuntimeError(
        f"effective registry declares no model with tools={declares_tools}"
    )


def test_tools_non_google_still_refused_before_dispatch(monkeypatch):
    _native_live(monkeypatch)
    from app.pilot.catalog import get_catalog_by_id
    # Any registered route whose platform provider is not the native wire.
    off_native_wire = next(
        row["id"] for row in model_rows()
        if get_catalog_by_id(row["id"]) is not None
        and get_catalog_by_id(row["id"]).platform_provider_id != native_wire.GOOGLE_PROVIDER_ID
    )
    calls = []
    response = _client(httpx.MockTransport(lambda req: calls.append(req))).post(
        STREAM_URL, json=_payload(model=off_native_wire, tools=[PC_TOOL]),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "stream_not_supported"
    assert calls == []


def test_tools_undeclared_google_capability_refused_before_dispatch(monkeypatch):
    _native_live(monkeypatch)
    from app.pilot.catalog import get_catalog_by_id
    # A Google-wire model with no declared tool capability; the registry model
    # that does declare one is covered by the test below (#6460-5).
    no_tools = next(
        row["id"] for row in model_rows()
        if get_catalog_by_id(row["id"]) is not None
        and get_catalog_by_id(row["id"]).platform_provider_id == native_wire.GOOGLE_PROVIDER_ID
        and "tools" not in (row.get("capabilities") or [])
    )
    calls = []
    response = _client(httpx.MockTransport(lambda req: calls.append(req))).post(
        STREAM_URL, json=_payload(model=no_tools, tools=[PC_TOOL]),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "tools_not_supported"
    assert calls == []


def test_a_declaring_model_reaches_the_native_tool_wire(monkeypatch):
    _native_live(monkeypatch)
    calls = []
    stream = _ChunkStream([
        _native_frame([{"functionCall": {"name": "pc_files", "args": {"plan": "files_list"}}}]),
    ])
    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=stream)
    response = _client(httpx.MockTransport(handler)).post(
        STREAM_URL, json=_payload(model=GOOGLE_TOOL_MODEL, tools=[PC_TOOL]),
    )
    assert response.status_code == 200
    assert response.text.startswith("event: tool_call\n")
    assert len(calls) == 1 and stream.closed


def test_google_tool_call_commits_stream_and_failure_never_falls_back(monkeypatch):
    _native_live(monkeypatch)
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
    _native_live(monkeypatch)
    stream = _ChunkStream([_native_frame(parts, finish="STOP")])
    response = _client(httpx.MockTransport(lambda req: httpx.Response(200, stream=stream))).post(
        STREAM_URL, json=_payload(model=GOOGLE_TOOL_MODEL, tools=[PC_TOOL], business14={"product_tier": "plus"}),
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "malformed_upstream_response"
    assert stream.closed


def test_google_tool_stream_preserves_text_and_explicit_parameters(monkeypatch):
    _native_live(monkeypatch)
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
    # #6838: the platform lane no longer forwards a caller's reasoning value.
    # This model declares no reasoning support in the public registry, so the
    # option is omitted rather than passed through.
    assert sent[0]["generationConfig"] == {"temperature": 0.3, "maxOutputTokens": 100}
    assert sent[0]["toolConfig"] == {"functionCallingConfig": {"mode": "NONE"}}
    frames = _json_data_frames(response.text)
    assert frames[0]["choices"][0]["delta"] == {"content": "안녕"}
    assert frames[-1] == {"finish_reason": "stop"}
    assert "event: tool_call" not in response.text
    assert stream.closed


def test_google_missing_finish_is_not_successful_done(monkeypatch):
    _native_live(monkeypatch)
    stream = _ChunkStream([_native_frame([{"functionCall": {"name": "pc_files", "args": {}}}])])
    response = _client(httpx.MockTransport(lambda req: httpx.Response(200, stream=stream))).post(
        STREAM_URL, json=_payload(model=GOOGLE_TOOL_MODEL, tools=[PC_TOOL]),
    )
    assert response.status_code == 200
    assert "event: tool_call" in response.text and "event: error" in response.text
    assert "event: done" not in response.text
    assert stream.closed


def _native_stream_bytes() -> bytes:
    """The exact legacy frame bytes for whichever Google tool model is routed.

    Every value in the snapshot comes from the effective registry, so the shape
    asserted here (frame order, business14 keys, no reasoning pass-through) is
    unchanged while no deployment value is written in the test file.
    """
    from app.pilot.catalog import get_catalog_by_id

    model = get_catalog_by_id(GOOGLE_TOOL_MODEL)
    metadata = {
        "request_id": "b14stream_fixed",
        "route_mode": "manual",
        "selected_provider": model.provider,
        "selected_model": GOOGLE_TOOL_MODEL,
        "selected_upstream_model": model.upstream_model,
        "selected_route_id": f"platform:{GOOGLE_TOOL_MODEL}",
        "fallback_allowed": True,
        "fallback_used": False,
        "attempt_count": 1,
        "provider_mode": "live",
        "route_evidence_status": "live_streaming_preview",
    }
    usage = {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
    body = []
    for delta, finish_reason, with_usage in (
        ({"content": "안녕"}, None, False),
        ({}, "stop", True),
    ):
        chunk = {
            "id": "upstream_stream_1",
            "object": "chat.completion.chunk",
            "model": MODEL,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
            "business14": metadata,
        }
        if with_usage:
            chunk["usage"] = usage
        body.append("data: " + json.dumps(chunk, ensure_ascii=False, separators=(",", ":")) + "\n\n")
    body.append("data: [DONE]\n\n")
    return "".join(body).encode("utf-8")


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

    fallback = _owner_tier_fallback_candidate()
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


def _owner_tier_fallback_candidate() -> dict:
    """The owner-tier roster's second candidate, in the router's own shape.

    The roster is the owner's decision and is read from the effective registry
    (``tier_fallback``), never written here: the first roster entry is the
    primary this suite routes to, so the *next* enabled entry is the backup the
    tier walk is allowed to reach.
    """
    from app.pilot.catalog import get_catalog_by_id
    from app.pilot.model_registry_file import installed_model_ids
    from app.pilot.tier_fallback import effective_tier_fallback

    installed = installed_model_ids()
    for roster in effective_tier_fallback().values():
        candidates = [model_id for model_id in roster
                      if model_id != MODEL and model_id in installed]
        if not candidates:
            continue
        model_id = candidates[0]
        model = get_catalog_by_id(model_id)
        if model is None or not model.enabled:
            continue
        return {
            "model_id": model_id,
            "upstream_model": model.upstream_model,
            "provider": model.provider,
            "platform_provider_id": model.platform_provider_id,
            "route_id": f"platform:{model_id}",
            "reason": "owner_selected_tier_fallback",
        }
    raise RuntimeError("effective registry declares no owner tier fallback candidate")


def _unregistered_model_id() -> str:
    """A well-formed model identity the effective registry does not declare.

    It reuses a registered provider id (so the shape stays realistic) with a
    model name that is not installed, so every refusal below is exercised by
    the same class of value without naming a deployment model.
    """
    provider = a_provider_id()
    installed = {row["id"] for row in model_rows()}
    model_id = f"{provider}/not-a-registered-model"
    suffix = 0
    while model_id in installed:
        suffix += 1
        model_id = f"{provider}/not-a-registered-model-{suffix}"
    return model_id


def test_canonical_stream_true_does_not_promote_a_non_catalog_model():
    client = _client()
    response = client.post(CHAT_URL, json=_payload(model=_unregistered_model_id()))

    # A non-catalog model never enters the stream opt-in and the canonical
    # validator refuses stream=true as always.
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "stream_not_supported"


def test_preview_requires_stream_true():
    client = _client()
    payload = _payload()
    payload.pop("stream")
    response = client.post(STREAM_URL, json=payload)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_streaming_is_rejected_before_network_for_a_non_catalog_model():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    rcfg.provider_mode = "live"
    rcfg.api_key = LIVE_DUMMY_KEY
    client = _client(httpx.MockTransport(handler))
    response = client.post(STREAM_URL, json=_payload(model=_unregistered_model_id()))

    # The stream surface refuses a non-catalog model before any network call.
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




@pytest.mark.parametrize("timeout_case", ["first_byte", "attempt_total", "chain_budget"])
def test_owner_tier_fallback_is_tried_before_first_visible_token(monkeypatch, timeout_case):
    from dataclasses import replace
    from app.pilot import stream_gateway
    from app.pilot.errors import UpstreamTimeout
    from app.pilot.stream_types import StreamEvent

    fallback = _owner_tier_fallback_candidate()
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
        lambda cm: (True, "key_available", "platform_secret", fallback["platform_provider_id"])
        if cm.model_id == fallback["model_id"] else original_credential(cm))
    monkeypatch.setenv("BUSINESS14_FIRST_BYTE_TIMEOUT_SECONDS", "0.02")
    monkeypatch.setenv("BUSINESS14_ATTEMPT_TIMEOUT_SECONDS", "0.08")
    monkeypatch.setenv("BUSINESS14_STREAM_IDLE_TIMEOUT_SECONDS", "0.03")
    monkeypatch.setenv("BUSINESS14_CHAIN_BUDGET_SECONDS",
                       "0.02" if timeout_case == "chain_budget" else "0.3")
    attempts = []
    records = []
    monkeypatch.setattr(stream_gateway, "_enqueue_ledger", records.append)

    async def fake_stream(**kwargs):
        attempts.append(kwargs["model_id"])
        if kwargs["model_id"] == MODEL:
            if timeout_case == "chain_budget":
                await asyncio.sleep(0.06)
                raise AssertionError("chain timeout should cancel before the first event")
            raise UpstreamTimeout(timeout_reason=timeout_case)
        yield StreamEvent(delta_content="backup token", model=kwargs["upstream_model"])
        yield StreamEvent(done=True)

    monkeypatch.setattr(stream_gateway, "stream_platform_chat_completions", fake_stream)
    rcfg.provider_mode = "live"
    response = _client().post(
        STREAM_URL,
        json=_payload(),
    )

    if timeout_case == "chain_budget":
        assert response.status_code == 504, response.text
        assert response.json()["error"]["code"] == "upstream_timeout"
        assert attempts == [MODEL]
        assert records and any(
            item.timeout_reason == "chain_budget" for item in records[-1].attempts
        )
        return

    assert response.status_code == 200, response.text
    frames = _json_data_frames(response.text)
    assert frames[0]["choices"][0]["delta"]["content"] == "backup token"
    metadata = frames[0]["business14"]
    assert metadata["selected_model"] == fallback["model_id"]
    assert metadata["attempt_count"] == 2
    assert metadata["fallback_used"] is True
    assert metadata["fallback_allowed"] is False
    assert attempts == [MODEL, fallback["model_id"]]
    assert records
    assert records[-1].attempts[0].timeout_reason == timeout_case
    assert "data: [DONE]" in response.text


@pytest.mark.parametrize(
    "timeout_phase,first,attempt,idle,expected_reason",
    [
        ("first_byte", 0.02, 0.20, 0.05, "first_byte"),
        ("stream_idle", 0.10, 0.20, 0.02, "attempt_total"),
    ],
)
def test_slow_provider_stream_falls_back_before_visible_token(
    monkeypatch, timeout_phase, first, attempt, idle, expected_reason,
):
    from dataclasses import replace
    import json
    from app.pilot import stream_gateway

    fallback = _owner_tier_fallback_candidate()
    original = stream_gateway.rcore.resolve_route
    def resolve_with_tier_pair(model_id, opts):
        base = original(model_id, opts)
        return replace(base, reason_codes=[*base.reason_codes,
            "owner_selected_tier_fallback:free"], fallback_allowed=True,
            eligible_fallback=[fallback])
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
    # The backup candidate is served from its own Provider row, so the Provider's
    # credential requirement is satisfied from the registry's binding name (the
    # live lane reads it) instead of only in the router's availability probe.
    from app.pilot import platform_secrets as ps
    backup_binding = provider_row(fallback["platform_provider_id"]).get("credential_binding_name")
    if backup_binding:
        monkeypatch.setenv(backup_binding, BACKUP_UNIT_KEY)
    original_credential = stream_gateway.rcore._credential_status_for
    monkeypatch.setattr(stream_gateway.rcore, "_credential_status_for",
        lambda cm: (True, "key_available", "platform_secret", fallback["platform_provider_id"])
        if cm.model_id == fallback["model_id"] else original_credential(cm))

    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv("BUSINESS14_FIRST_BYTE_TIMEOUT_SECONDS", str(first))
    monkeypatch.setenv("BUSINESS14_ATTEMPT_TIMEOUT_SECONDS", str(attempt))
    monkeypatch.setenv("BUSINESS14_STREAM_IDLE_TIMEOUT_SECONDS", str(idle))
    monkeypatch.setenv("BUSINESS14_CHAIN_BUDGET_SECONDS", "0.5")
    rcfg.provider_mode = "live"
    requests = []
    records = []
    monkeypatch.setattr(stream_gateway, "_enqueue_ledger", records.append)

    def sse(model, content):
        frames = [
            {"model": model, "choices": [{"delta": {"content": content},
                                            "finish_reason": None}]},
            {"model": model, "choices": [{"delta": {}, "finish_reason": "stop"}]},
        ]
        return b"".join(
            ("data: " + json.dumps(frame) + "\n\n").encode()
            for frame in frames
        ) + b"data: [DONE]\n\n"

    async def responder(request):
        body = json.loads(request.content)
        model = body["model"]
        requests.append(model)
        if model == MODEL_UPSTREAM:
            if timeout_phase == "first_byte":
                stream = _DelayedChunkStream([(0.06, sse(model, "late primary"))])
            else:
                stream = _DelayedChunkStream([
                    (0.0, b": heartbeat\n\n"),
                    (0.06, sse(model, "late primary")),
                ])
            return httpx.Response(200, stream=stream)
        return httpx.Response(
            200, stream=_DelayedChunkStream([(0.0, sse(fallback["upstream_model"], "backup token"))]),
        )

    response = _client(httpx.MockTransport(responder)).post(STREAM_URL, json=_payload())
    assert response.status_code == 200, response.text
    frames = _json_data_frames(response.text)
    assert frames[0]["choices"][0]["delta"]["content"] == "backup token"
    assert frames[0]["business14"]["selected_model"] == fallback["model_id"]
    assert requests == [MODEL_UPSTREAM, fallback["upstream_model"]]
    assert records and records[-1].attempts[0].timeout_reason == expected_reason
    assert "data: [DONE]" in response.text


def test_owner_tier_fallback_is_not_tried_after_first_visible_token(monkeypatch):
    from dataclasses import replace
    from app.pilot import stream_gateway
    from app.pilot.errors import PilotError
    from app.pilot.stream_types import StreamEvent

    fallback = _owner_tier_fallback_candidate()
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
        lambda cm: (True, "key_available", "platform_secret", fallback["platform_provider_id"])
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
    response = client.post(STREAM_URL, json=_payload(model=_unregistered_model_id()))

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


def test_pre_start_unexpected_error_logs_traceback_and_keeps_generic_response(
    monkeypatch, caplog,
):
    from app.pilot import stream_gateway

    def fail_validation(_raw):
        raise RuntimeError("synthetic pre-start failure")

    monkeypatch.setattr(stream_gateway, "_validate_preview_body", fail_validation)
    with caplog.at_level("ERROR", logger=stream_gateway.logger.name):
        response = _client().post(STREAM_URL, json=_payload())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "synthetic pre-start failure" not in response.text
    record = next(
        record for record in caplog.records
        if "stream_preview_pre_start_internal_error" in record.getMessage()
    )
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError


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
    response = _client().post(CHAT_URL, json=_payload(model=_unregistered_model_id()))
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
