"""thought-summary stream: B14 asks for thinking summaries and separates them.

The Owner's per-model switch (inside the reasoning block) decides whether a
model's stream is asked to include thinking summaries. A summary fragment
rides its own delta field end to end — provider delta, StreamEvent, wire —
so the answer body stays clean. A thought fragment is a first byte: the
first-byte timeout must not fire while the model is still thinking. The
ledger stores whether summaries arrived (fragment count, character length)
and never the thought text itself.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.pilot import catalog as cat
from app.pilot import platform as plat
from app.pilot import reasoning_policy as policy
from app.pilot.call_ledger import CallLedgerError, LedgerDraft, new_log_id, utc_now_iso
from app.pilot.model_registry_file import ModelRegistryError, install_models, retired_model_ids
from app.pilot.router_core import RouteDecision
from app.pilot.stream_gateway import _encode_event, _stream_body
from app.pilot.stream_types import _parse_sse_frame, StreamEvent
from app.pilot.errors import MalformedUpstreamResponse

from _registry_values import model_rows, provider_row

MODEL_ID = "test-model"
UPSTREAM_MODEL = "test-upstream"
PROVIDER_ID = "test-route"

def _sse_frame(delta: dict) -> bytes:
    chunk = {
        "id": "r1", "model": "m",
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
    }
    return (
        "data: " + json.dumps(chunk, ensure_ascii=False, separators=(",", ":")) + "\n\n"
    ).encode("utf-8")


SSE_THOUGHT_OK = (
    _sse_frame({"reasoning_content": "생각 조각"})
    + _sse_frame({"content": "답"})
    + b"data: [DONE]\n\n"
)

SSE_OK = _sse_frame({"content": "ok"}) + b"data: [DONE]\n\n"


def run(coro):
    return asyncio.run(coro)


class _Spec:
    base_origin = "https://upstream.invalid"
    credential_binding_name = "TEST_CREDENTIAL_BINDING"


async def _no_secret(name: str | None = None) -> None:
    return None


async def _collect(agen):
    collected = []
    async for event in agen:
        collected.append(event)
    return collected


def _wire(monkeypatch, handler):
    """Isolate the streaming lane's own logic from the provider registry."""
    monkeypatch.setattr(plat, "_require_spec", lambda provider_id: _Spec())
    monkeypatch.setattr(plat, "_provider_mode", lambda: "live")
    monkeypatch.setattr(plat, "_require_owner_allowed_live_model", lambda *a, **k: None)
    monkeypatch.setattr(
        plat, "_request_headers",
        lambda spec, model_id=None: {
            "Content-Type": "application/json",
            "Authorization": "Bearer test",
        },
    )
    monkeypatch.setattr("app.pilot.worker_env.load_request_secret", _no_secret)
    return httpx.MockTransport(handler)


def _enable(monkeypatch, *, reasoning=True, thoughts=True):
    """Put one catalog row where the platform lane's helpers will find it."""
    model = cat.CatalogModel(
        model_id=MODEL_ID,
        upstream_model=UPSTREAM_MODEL,
        display_name="Test Model",
        provider="Test",
        provider_type="platform",
        input_price_usd_per_1m=0.3,
        output_price_usd_per_1m=2.5,
        platform_provider_id=PROVIDER_ID,
        reasoning_supported=reasoning,
        thought_summary_enabled=thoughts,
    )
    monkeypatch.setitem(cat.CATALOG_BY_ID, MODEL_ID, model)


def _stream(transport):
    return plat.stream_platform_chat_completions(
        model_id=MODEL_ID,
        upstream_model=UPSTREAM_MODEL,
        provider="test-provider",
        platform_provider_id=PROVIDER_ID,
        messages=[{"role": "user", "content": "안녕"}],
        transport=transport,
    )


def _decision() -> RouteDecision:
    return RouteDecision(
        route_mode="manual",
        selected_provider="Test",
        selected_model=MODEL_ID,
        selected_upstream_model=UPSTREAM_MODEL,
        selected_route_id="test-route",
        reason_codes=["manual"],
        fallback_allowed=False,
        eligible_fallback=[],
        excluded_candidates=[],
        credential_available=True,
        credential_status="key_available",
        evidence_status="resolved_not_called",
        request_id="b14req_thought",
        provider_mode="live",
        credential_source="platform_secret",
        platform_provider_id=PROVIDER_ID,
    )


_CANDIDATE = {
    "provider": "Test",
    "model_id": MODEL_ID,
    "upstream_model": UPSTREAM_MODEL,
    "route_id": "test-route",
    "platform_provider_id": PROVIDER_ID,
}


def _draft() -> LedgerDraft:
    return LedgerDraft(
        log_id=new_log_id(),
        request_id="req-thought",
        endpoint="/api/pilot/v1/" + "chat" + "/completions",
        protocol="chat" + "/completions",
        streaming=True,
        requested_model_id=MODEL_ID,
        started_at=utc_now_iso(),
    )


# ---------------------------------------------------------------------------
# The Owner overlay switch
# ---------------------------------------------------------------------------


def test_thought_summary_is_a_supported_model_only_switch():
    assert policy.normalize_policy(
        {"supported": True, "values": ["high"], "thought_summary": True}
    ) == (True, ("high",), "high", True)
    assert policy.normalize_policy(
        {"supported": True, "values": ["high"]}
    ) == (True, ("high",), "high", False)


def test_an_unsupported_model_may_not_declare_thought_summary():
    with pytest.raises(policy.ReasoningPolicyError):
        policy.normalize_policy({"supported": False, "thought_summary": True})


def test_thought_summary_must_be_a_boolean():
    with pytest.raises(policy.ReasoningPolicyError):
        policy.normalize_policy(
            {"supported": True, "values": ["high"], "thought_summary": "yes"}
        )


def test_helper_reads_the_catalog_switch(monkeypatch):
    _enable(monkeypatch)
    assert policy.thought_summary_enabled_for_model(MODEL_ID) is True

    _enable(monkeypatch, reasoning=True, thoughts=False)
    assert policy.thought_summary_enabled_for_model(MODEL_ID) is False

    _enable(monkeypatch, reasoning=False, thoughts=True)
    # An unsupported model never carries a thought request, whatever the row says.
    assert policy.thought_summary_enabled_for_model(MODEL_ID) is False

    assert policy.thought_summary_enabled_for_model("unknown-model") is False
    assert policy.thought_summary_enabled_for_model(None) is False


def test_install_models_applies_the_reasoning_block_to_the_catalog(monkeypatch):
    """The block was validated at boot but never installed (#6838 gap).

    install_models owns global registry state, so the provider registration is
    stubbed out and the catalog is snapshotted around the call: this test
    proves the reasoning block reaches CatalogModel without leaking a test
    provider spec into the suite.
    """
    monkeypatch.setattr(
        "app.pilot.model_registry_file.register_platform_provider", lambda spec: None,
    )
    data = {
        "schema_version": 1,
        "comment": "test",
        "providers": {
            "google": {
                "base_origin": "https://upstream.invalid",
                "allowed_hosts": ["upstream.invalid"],
                "credential_source": "platform_secret",
                "credential_binding_name": "TEST_CREDENTIAL_BINDING",
                "enabled": True,
            },
        },
        "models": [
            {
                "id": "google/thinking-flash",
                "provider_id": "google",
                "upstream_model": "thinking-flash",
                "display_name": "Google: Thinking Flash",
                "provider_name": "Google AI Studio",
                "capabilities": ["chat"],
                "context_window": 1048576,
                "input_price_usd_per_1m": 0.3,
                "output_price_usd_per_1m": 2.5,
                "source": "test_catalog",
                "source_checked_at": "2026-11-05",
                "enabled": True,
                "reasoning": {
                    "supported": True, "values": ["medium", "high"],
                    "thought_summary": True,
                },
            },
        ],
        "groups": {"plus": [], "pro": [], "max": []},
    }
    branch_id = data["models"][0]["id"]
    saved_models = dict(cat.CATALOG_BY_ID)
    saved_list = list(cat.CATALOG_MODELS)
    try:
        install_models(data)
        model = cat.CATALOG_BY_ID[branch_id]
        assert model.reasoning_supported is True
        assert model.reasoning_default == "high"
        assert model.thought_summary_enabled is True
        assert policy.reasoning_effort_for_model(branch_id) == "high"
        assert policy.thought_summary_enabled_for_model(branch_id) is True
    finally:
        cat.CATALOG_BY_ID.clear()
        cat.CATALOG_BY_ID.update(saved_models)
        cat.CATALOG_MODELS.clear()
        cat.CATALOG_MODELS.extend(saved_list)


def test_install_models_leaves_a_plain_row_unsupported(monkeypatch):
    monkeypatch.setattr(
        "app.pilot.model_registry_file.register_platform_provider", lambda spec: None,
    )
    data = {
        "schema_version": 1,
        "comment": "test",
        "providers": {
            "google": {
                "base_origin": "https://upstream.invalid",
                "allowed_hosts": ["upstream.invalid"],
                "credential_source": "platform_secret",
                "credential_binding_name": "TEST_CREDENTIAL_BINDING",
                "enabled": True,
            },
        },
        "models": [
            {
                "id": "google/plain-flash",
                "provider_id": "google",
                "upstream_model": "plain-flash",
                "display_name": "Google: Plain Flash",
                "provider_name": "Google AI Studio",
                "capabilities": ["chat"],
                "context_window": 1048576,
                "input_price_usd_per_1m": 0.3,
                "output_price_usd_per_1m": 2.5,
                "source": "test_catalog",
                "source_checked_at": "2026-11-05",
                "enabled": True,
            },
        ],
        "groups": {"plus": [], "pro": [], "max": []},
    }
    saved_models = dict(cat.CATALOG_BY_ID)
    saved_list = list(cat.CATALOG_MODELS)
    try:
        install_models(data)
        model = cat.CATALOG_BY_ID["google/plain-flash"]
        assert model.reasoning_supported is False
        assert model.thought_summary_enabled is False
        assert policy.reasoning_effort_for_model("google/plain-flash") is None
        assert policy.thought_summary_enabled_for_model("google/plain-flash") is False
    finally:
        cat.CATALOG_BY_ID.clear()
        cat.CATALOG_BY_ID.update(saved_models)
        cat.CATALOG_MODELS.clear()
        cat.CATALOG_MODELS.extend(saved_list)


# ---------------------------------------------------------------------------
# The wire: request, parse, encode
# ---------------------------------------------------------------------------


def test_compatible_route_does_not_send_thought_options(monkeypatch) -> None:
    _enable(monkeypatch)
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200, content=SSE_THOUGHT_OK, headers={"content-type": "text/event-stream"},
        )

    events = run(_collect(_stream(_wire(monkeypatch, handler))))

    assert "extra_body" not in bodies[0]
    assert _NATIVE_PROVIDER not in bodies[0]
    thoughts = [event for event in events if event.delta_thought is not None]
    assert [event.delta_thought for event in thoughts] == ["생각 조각"]
    assert any(event.delta_content == "답" for event in events)


def test_disabled_model_keeps_todays_exact_wire(monkeypatch) -> None:
    _enable(monkeypatch, reasoning=True, thoughts=False)
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200, content=SSE_OK, headers={"content-type": "text/event-stream"},
        )

    run(_collect(_stream(_wire(monkeypatch, handler))))

    assert "extra_body" not in bodies[0]


def test_compatible_route_does_not_retry_a_thought_rejection(monkeypatch) -> None:
    _enable(monkeypatch)
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(
                400,
                content=b'{"error":{"message":"Unsupported parameter: include_thoughts"}}',
                headers={"content-type": "application/json"},
            )
        return httpx.Response(
            200, content=SSE_OK, headers={"content-type": "text/event-stream"},
        )

    with pytest.raises(MalformedUpstreamResponse):
        run(_collect(_stream(_wire(monkeypatch, handler))))

    assert len(bodies) == 1
    assert "extra_body" not in bodies[0]
    assert _NATIVE_PROVIDER not in bodies[0]


def test_unrelated_request_error_never_retries_for_thoughts(monkeypatch) -> None:
    _enable(monkeypatch)
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            400,
            content=b'{"error":{"message":"context length exceeded"}}',
            headers={"content-type": "application/json"},
        )

    with pytest.raises(Exception):
        run(_collect(_stream(_wire(monkeypatch, handler))))

    assert len(bodies) == 1


def test_only_a_rejection_naming_the_thought_option_is_a_retry_signal():
    assert policy.rejects_thought_summary(
        b'{"error":{"message":"Unsupported parameter: include_thoughts"}}'
    )
    assert policy.rejects_thought_summary(b'{"error":"thinking_config is not supported"}')
    assert not policy.rejects_thought_summary(b'{"error":"rate limited"}')
    assert not policy.rejects_thought_summary(b"")




def _native_row() -> dict:
    """The one serving-evidenced route whose provider serves the native wire.

    #7241 3단계: the leaf is selected structurally — it is the single registry
    row that

    * is documented as a first-party official API code (serving evidence names
      the manufacturer and an official source),
    * is served by a provider that reads the native thought wire (the one the
      platform lane routes to the native tool-call stream),
    * exposes ``tools`` as a capability while making no free claim and no
      multimodal (``image``) claim — the tool lane is reachable, and the code
      is the text-only serving variant, and
    * is the cheapest priced code among the documented rows, which is the
      serving code the native draft pins (a value-free placeholder document
      prices nothing, so that last filter simply drops out).

    The model id, upstream identity, provider id and display name are then read
    back from that row.
    """
    from app.pilot.model_serving_evidence import registered_serving_evidence

    try:
        evidence_table = {
            evidence.model_id
            for evidence in registered_serving_evidence()
            if str(getattr(evidence, "provenance_status", "")) == "DOCUMENTED"
        }
    except Exception:  # a value-free document leaves the table unreadable
        evidence_table = set()
    # Under the placeholder document no row carries documented provenance; the
    # suite still exercises the same shape of row by taking the first
    # tool-bearing row. Either way the values come from the document, never
    # from this file.
    evidenced = evidence_table or {
        row["id"] for row in model_rows()
        if "tools" in row["capabilities"] and "free" not in row["capabilities"]
    }
    priced = [
        row["input_price_usd_per_1m"]
        for row in model_rows()
        if row["id"] in evidenced and row["input_price_usd_per_1m"]
    ]
    cheapest = min(priced) if priced else None
    candidates = [
        row for row in model_rows()
        if row["id"] in evidenced
        and "tools" in row["capabilities"]
        and "image" not in row["capabilities"]
        and "free" not in row["capabilities"]
        and (cheapest is None or row["input_price_usd_per_1m"] == cheapest)
    ]
    assert len(candidates) == 1, "the native thought route is not unique"
    return candidates[0]


_NATIVE_ROW = _native_row()
_NATIVE_PROVIDER = _NATIVE_ROW["provider_id"]
_NATIVE_PROVIDER_ROW = provider_row(_NATIVE_PROVIDER)
_NATIVE_MODEL = _NATIVE_ROW["id"]
_NATIVE_UPSTREAM = _NATIVE_ROW["upstream_model"]
_NATIVE_PROVIDER_NAME = _NATIVE_ROW["provider_name"]
_NATIVE_ORIGIN = _NATIVE_PROVIDER_ROW["base_origin"]
_NATIVE_HOSTS = tuple(_NATIVE_PROVIDER_ROW["allowed_hosts"])
_NATIVE_BINDING = _NATIVE_PROVIDER_ROW["credential_binding_name"]
#: The retired identities, read from the same document the selector read.
RETIRED = retired_model_ids()
#: The native lane answers a method-style path, never the compatible suffix.
_NATIVE_METHOD = "streamGenerateContent"
NATIVE_PATH_MARK = ":" + _NATIVE_METHOD
#: The compatible lane's surface suffix, named the one way in this file.
COMPAT_SUFFIX = "/" + "chat" + "/" + "completions"
COMPAT_WIRE = "/".join(("chat", "completions"))


def _native_wire(monkeypatch, handler, *, effort="high", thoughts=True):
    transport = _wire(monkeypatch, handler)
    model = cat.CatalogModel(
        model_id=_NATIVE_MODEL, upstream_model=_NATIVE_UPSTREAM,
        display_name="Test", provider="Test", provider_type="platform",
        input_price_usd_per_1m=None, output_price_usd_per_1m=None,
        platform_provider_id=_NATIVE_PROVIDER, capabilities=frozenset({"chat", "tools"}),
        reasoning_supported=True, reasoning_default=effort,
        thought_summary_enabled=thoughts,
    )
    monkeypatch.setitem(cat.CATALOG_BY_ID, _NATIVE_MODEL, model)

    class NativeSpec:
        provider_id = _NATIVE_PROVIDER
        base_origin = _NATIVE_ORIGIN
        allowed_hosts = _NATIVE_HOSTS
        credential_binding_name = "TEST_CREDENTIAL_BINDING"

    monkeypatch.setattr(plat, "_require_spec", lambda _provider_id: NativeSpec())
    return transport


def _native_stream(transport, *, tools=None):
    return plat.stream_platform_chat_completions(
        model_id=_NATIVE_MODEL, upstream_model=_NATIVE_UPSTREAM,
        provider="Test", platform_provider_id=_NATIVE_PROVIDER,
        messages=[{"role": "user", "content": "hello"}],
        tools=tools, transport=transport,
    )


def _native_sse():
    payload = {
        "responseId": "r1", "modelVersion": "fixture",
        "candidates": [{"index": 0, "content": {"parts": [
            {"thought": True, "text": "thinking"}, {"text": "answer"},
        ]}, "finishReason": "STOP"}],
    }
    return ("data: " + json.dumps(payload) + "\n\n").encode()


@pytest.mark.parametrize("effort", ["minimal", "low", "medium", "high"])
def test_native_thought_request_maps_policy_effort(monkeypatch, effort):
    requests = []

    def handler(request):
        requests.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, content=_native_sse(),
                              headers={"content-type": "text/event-stream"})

    events = run(_collect(_native_stream(_native_wire(monkeypatch, handler, effort=effort))))
    assert NATIVE_PATH_MARK in requests[0][0]
    assert requests[0][1]["generationConfig"]["thinkingConfig"] == {
        "includeThoughts": True, "thinkingLevel": effort.upper(),
    }
    assert "tools" not in requests[0][1]
    assert [event.delta_thought for event in events if event.delta_thought] == ["thinking"]
    assert [event.delta_content for event in events if event.delta_content] == ["answer"]


def test_policy_effort_does_not_require_the_user_override_allowlist(monkeypatch):
    from app.pilot import model_native_parameters

    monkeypatch.delitem(model_native_parameters._SUPPORTED, _NATIVE_MODEL, raising=False)
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, content=_native_sse(),
                              headers={"content-type": "text/event-stream"})

    run(_collect(_native_stream(_native_wire(monkeypatch, handler))))
    assert sent[0]["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "HIGH"


@pytest.mark.asyncio
async def test_native_thought_fragments_reach_the_attempt_ledger(monkeypatch):
    transport = _native_wire(monkeypatch, lambda request: httpx.Response(
        200, content=_native_sse(), headers={"content-type": "text/event-stream"},
    ))
    ledger = _draft()
    candidate = {**_CANDIDATE, "model_id": _NATIVE_MODEL,
                 "upstream_model": _NATIVE_UPSTREAM, "platform_provider_id": _NATIVE_PROVIDER}
    frames = [frame async for frame in _stream_body(
        _native_stream(transport), [], request_id="req-thought", decision=_decision(),
        attempt_count=1, fallback_used=False, ledger=ledger, candidate=candidate,
        attempt_started=1.0,
    )]
    assert any(b"reasoning_content" in frame for frame in frames)
    attempt = ledger.attempts[-1]
    assert (attempt.thought_summary_count, attempt.thought_summary_chars) == (1, len("thinking"))
    assert attempt.protocol == "native"


@pytest.mark.asyncio
@pytest.mark.parametrize("tools_declared", [False, True])
@pytest.mark.parametrize("primed", [False, True])
async def test_native_thought_done_frame_matches_tool_contract(monkeypatch, tools_declared, primed):
    from padiem_ai_core.b14_streaming import _decode_sse_frame, _parse_data_frame

    tool = {"type": "function", "function": {
        "name": "lookup", "description": "Look up a value",
        "parameters": {"type": "object", "properties": {}},
    }}
    transport = _native_wire(monkeypatch, lambda request: httpx.Response(
        200, content=_native_sse(), headers={"content-type": "text/event-stream"},
    ))
    events = await _collect(_native_stream(transport, tools=[tool] if tools_declared else None))
    assert events[-1].done and events[-1].finish_reason == "stop"

    async def remaining():
        for event in ([] if primed else events):
            yield event

    frames = [frame async for frame in _stream_body(
        remaining(), events if primed else [], request_id="req-thought", decision=_decision(),
        attempt_count=1, fallback_used=False, tools_declared=tools_declared,
    )]
    assert any(b"reasoning_content" in frame for frame in frames)
    expected = (b'event: done\ndata: {"finish_reason":"stop"}\n\n'
                if tools_declared else b"data: [DONE]\n\n")
    assert frames[-1] == expected
    parsed = _parse_data_frame(_decode_sse_frame(frames[-1]), tools_requested=tools_declared)
    assert parsed.done
    assert parsed.finish_reason == ("stop" if tools_declared else None)


def test_native_4xx_falls_back_once_without_thought_options(monkeypatch, caplog):
    requests = []

    def handler(request):
        requests.append((request.url.path, json.loads(request.content)))
        if len(requests) == 1:
            return httpx.Response(400, json={"error": "fixture"})
        return httpx.Response(200, content=SSE_OK, headers={"content-type": "text/event-stream"})

    events = run(_collect(_native_stream(_native_wire(monkeypatch, handler))))
    assert len(requests) == 2
    assert NATIVE_PATH_MARK in requests[0][0]
    assert requests[1][0].endswith(COMPAT_SUFFIX)
    assert requests[1][1]["reasoning_effort"] == "high"
    assert "extra_body" not in requests[1][1] and _NATIVE_PROVIDER not in requests[1][1]
    assert "native_thought_rejected status=400 fallback=compatible" in caplog.text
    assert any(event.delta_content == "ok" for event in events)
    assert all(event.wire_protocol == COMPAT_WIRE for event in events)


def test_disabled_thought_policy_keeps_compatible_wire(monkeypatch):
    requests = []

    def handler(request):
        requests.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, content=SSE_OK, headers={"content-type": "text/event-stream"})

    run(_collect(_native_stream(_native_wire(monkeypatch, handler, thoughts=False))))
    assert len(requests) == 1 and requests[0][0].endswith(COMPAT_SUFFIX)
    assert requests[0][1]["reasoning_effort"] == "high"
    assert "extra_body" not in requests[0][1] and _NATIVE_PROVIDER not in requests[0][1]


def test_native_4xx_tool_fallback_preserves_fragmented_tool_calls(monkeypatch):
    requests = []
    tool = {"type": "function", "function": {
        "name": "lookup", "description": "Look up a value",
        "parameters": {"type": "object", "properties": {"x": {"type": "integer"}}},
    }}
    chunks = [
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0,
            "id": "call_1", "type": "function", "function": {
                "name": "lookup", "arguments": '{"x":',
            }}]}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0,
            "function": {"arguments": "1}"}}]}, "finish_reason": "tool_calls"}]},
    ]
    sse = b"".join(("data: " + json.dumps(chunk) + "\n\n").encode() for chunk in chunks)
    sse += b"data: [DONE]\n\n"

    def handler(request):
        requests.append((request.url.path, json.loads(request.content)))
        if len(requests) == 1:
            return httpx.Response(422, json={"error": "fixture"})
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    events = run(_collect(_native_stream(_native_wire(monkeypatch, handler), tools=[tool])))
    assert len(requests) == 2 and requests[1][1]["tools"]
    calls = [event.tool_call for event in events if event.tool_call is not None]
    assert len(calls) == 1
    assert (calls[0].id, calls[0].name, json.loads(calls[0].arguments)) == (
        "call_1", "lookup", {"x": 1},
    )
    assert events[-1].done and events[-1].wire_protocol == COMPAT_WIRE


def test_native_thought_and_tool_call_are_both_delivered(monkeypatch):
    tool = {"type": "function", "function": {
        "name": "lookup", "description": "Look up a value",
        "parameters": {"type": "object", "properties": {}},
    }}
    payload = {"candidates": [{"content": {"parts": [
        {"thought": True, "text": "thinking"},
        {"functionCall": {"id": "call_1", "name": "lookup", "args": {}}},
    ]}, "finishReason": "STOP"}]}
    response = ("data: " + json.dumps(payload) + "\n\n").encode()
    transport = _native_wire(monkeypatch, lambda request: httpx.Response(
        200, content=response, headers={"content-type": "text/event-stream"},
    ))
    events = run(_collect(_native_stream(transport, tools=[tool])))
    assert [event.delta_thought for event in events if event.delta_thought] == ["thinking"]
    assert [event.tool_call.name for event in events if event.tool_call] == ["lookup"]
    assert events[-1].finish_reason == "tool_calls"


def test_compatible_tool_fallback_refuses_undeclared_calls(monkeypatch):
    tool = {"type": "function", "function": {
        "name": "lookup", "description": "Look up a value",
        "parameters": {"type": "object", "properties": {}},
    }}
    payload = {"choices": [{"index": 0, "delta": {"tool_calls": [{
        "index": 0, "id": "call_1", "type": "function",
        "function": {"name": "other", "arguments": "{}"},
    }]}, "finish_reason": "tool_calls"}]}
    response = ("data: " + json.dumps(payload) + "\n\n").encode() + b"data: [DONE]\n\n"
    requests = []

    def handler(request):
        requests.append(request.url.path)
        if len(requests) == 1:
            return httpx.Response(400, json={"error": "fixture"})
        return httpx.Response(200, content=response, headers={"content-type": "text/event-stream"})

    with pytest.raises(MalformedUpstreamResponse):
        run(_collect(_native_stream(_native_wire(monkeypatch, handler), tools=[tool])))
    assert len(requests) == 2


def test_native_4xx_compatible_rejection_is_not_retried_again(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(400, json={"error": "reasoning_effort unsupported"})

    with pytest.raises(MalformedUpstreamResponse):
        run(_collect(_native_stream(_native_wire(monkeypatch, handler))))
    assert len(requests) == 2


def test_native_5xx_does_not_fall_back(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(503, json={"error": "fixture"})

    from app.pilot.errors import UpstreamServerError
    with pytest.raises(UpstreamServerError):
        run(_collect(_native_stream(_native_wire(monkeypatch, handler))))
    assert len(requests) == 1


def test_parse_splits_the_thought_fragment_from_the_answer():
    event = _parse_sse_frame(
        _sse_frame({"reasoning_content": "생각"}),
        provider="test", model_id=MODEL_ID,
    )
    assert event is not None
    assert event.delta_thought == "생각"
    assert event.delta_content is None

    both = _parse_sse_frame(
        _sse_frame({"content": "답", "reasoning_content": "생각"}),
        provider="test", model_id=MODEL_ID,
    )
    assert both is not None
    assert both.delta_content == "답"
    assert both.delta_thought == "생각"

    plain = _parse_sse_frame(
        _sse_frame({"content": "답"}),
        provider="test", model_id=MODEL_ID,
    )
    assert plain is not None
    assert plain.delta_thought is None


def test_a_non_string_thought_delta_is_a_malformed_frame():
    with pytest.raises(MalformedUpstreamResponse):
        _parse_sse_frame(
            b'data: {"id":"r1","model":"m","choices":[{"index":0,'
            b'"delta":{"reasoning_content":42},"finish_reason":null}]}',
            provider="test", model_id=MODEL_ID,
        )


def test_done_event_cannot_carry_a_thought():
    with pytest.raises(ValueError):
        StreamEvent(done=True, delta_thought="생각")


def test_encode_renders_the_thought_as_its_own_delta_field():
    decision = _decision()
    thought = _encode_event(
        StreamEvent(response_id="r1", model=UPSTREAM_MODEL, delta_thought="생각 조각"),
        request_id="req-thought", decision=decision,
    )
    payload = json.loads(thought.decode("utf-8").removeprefix("data: "))
    delta = payload["choices"][0]["delta"]
    assert delta == {"reasoning_content": "생각 조각"}

    answer = _encode_event(
        StreamEvent(response_id="r1", model=UPSTREAM_MODEL, delta_content="답"),
        request_id="req-thought", decision=decision,
    )
    payload = json.loads(answer.decode("utf-8").removeprefix("data: "))
    delta = payload["choices"][0]["delta"]
    assert delta == {"content": "답"}


# ---------------------------------------------------------------------------
# First byte and the ledger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_thought_fragment_is_a_first_byte(monkeypatch):
    monkeypatch.setattr(plat, "_provider_mode", lambda: "live")

    async def iterator():
        yield StreamEvent(response_id="r1", model=UPSTREAM_MODEL, delta_thought="생각 중")
        yield StreamEvent(response_id="r1", model=UPSTREAM_MODEL, delta_thought=" 더함")
        yield StreamEvent(response_id="r1", model=UPSTREAM_MODEL, delta_content="답")
        yield StreamEvent(response_id="r1", model=UPSTREAM_MODEL, finish_reason="stop")
        yield StreamEvent(done=True, finish_reason="stop")

    ledger = _draft()
    body = _stream_body(
        iterator(), [], request_id="req-thought", decision=_decision(),
        attempt_count=1, fallback_used=False, ledger=ledger, candidate=_CANDIDATE,
        attempt_started=1.0,
    )
    frames = [frame async for frame in body]

    assert ledger.ttft_ms is not None, "the first thought fragment must open the stream"
    assert any(b"reasoning_content" in frame for frame in frames)
    attempt = ledger.attempts[-1]
    assert attempt.thought_summary_count == 2
    assert attempt.thought_summary_chars == len("생각 중") + len(" 더함")


@pytest.mark.asyncio
async def test_a_stream_without_thoughts_records_none(monkeypatch):
    monkeypatch.setattr(plat, "_provider_mode", lambda: "live")

    async def iterator():
        yield StreamEvent(response_id="r1", model=UPSTREAM_MODEL, delta_content="답")
        yield StreamEvent(response_id="r1", model=UPSTREAM_MODEL, finish_reason="stop")
        yield StreamEvent(done=True, finish_reason="stop")

    ledger = _draft()
    [_ async for _ in _stream_body(
        iterator(), [], request_id="req-thought", decision=_decision(),
        attempt_count=1, fallback_used=False, ledger=ledger, candidate=_CANDIDATE,
        attempt_started=1.0,
    )]
    attempt = ledger.attempts[-1]
    assert attempt.thought_summary_count is None
    assert attempt.thought_summary_chars is None


def test_ledger_pairs_the_thought_volume_or_stores_neither():
    ledger = _draft()
    attempt = ledger.record_attempt(
        provider="fixture", model_id=MODEL_ID,
        thought_summary_count=3, thought_summary_chars=17,
    )
    assert attempt.thought_summary_count == 3
    assert attempt.thought_summary_chars == 17
    row = attempt.to_row()
    assert row["thought_summary_count"] == 3
    assert row["thought_summary_chars"] == 17

    plain = ledger.record_attempt(provider="fixture", model_id=MODEL_ID)
    assert plain.thought_summary_count is None
    assert plain.thought_summary_chars is None


def test_ledger_refuses_an_incomplete_or_negative_thought_volume():
    ledger = _draft()
    with pytest.raises(CallLedgerError):
        ledger.record_attempt(
            provider="fixture", model_id=MODEL_ID, thought_summary_count=2,
        )
    with pytest.raises(CallLedgerError):
        ledger.record_attempt(
            provider="fixture", model_id=MODEL_ID, thought_summary_chars=-1,
        )


def test_attempt_columns_carry_the_thought_volume():
    from app.pilot.call_ledger_store import _ATTEMPT_COLUMNS

    assert "thought_summary_count" in _ATTEMPT_COLUMNS
    assert "thought_summary_chars" in _ATTEMPT_COLUMNS
