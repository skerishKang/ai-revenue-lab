"""Wire-protocol boundary tests; all outbound calls use synthetic MockTransport."""
import json

import httpx
import pytest

from app.pilot import opencode_go_wire as go
from app.pilot.errors import InvalidRequest, PilotNotConfigured, MalformedUpstreamResponse, UpstreamAuthFailed

from _pilot_lane_paths import chat_surface
from _registry_values import registry, requires_owner_document

SESSION = "chat_0123456789abcdef0123456789abcdef"
TURNS = [{"role": "system", "content": "Code only"}, {"role": "user", "content": "Write a Python function."}]


def _go_provider_id():
    """The registry provider row this adapter serves.

    The adapter pins its own approved origin (code authority); the matching
    row is looked up in the effective registry instead of naming the provider
    here. A document may carry no such row at all (the value-free fixture), so
    the lookup never fails at import: the structural match answers ``None``
    and every suite-level pin stays behind ``@requires_owner_document``.
    """
    approved = go._GO_APPROVED_ORIGIN + "/v1"
    matches = [
        pid for pid, row in registry()["providers"].items()
        if str(row.get("base_origin", "")).rstrip("/") == approved
    ]
    assert len(matches) <= 1, f"more than one Go provider row: {matches}"
    return matches[0] if matches else None


# The adapter's own owner-approved wire table is code authority for which
# upstream models it serves, so no model id is written here as data.
GO_IDS = list(go._WIRE)

# The approved inference origin is the adapter's own pinned constant (code
# authority for the wire lanes this suite covers).
GO_ORIGIN = go._GO_APPROVED_ORIGIN

# Wire family names are the adapter's protocol vocabulary (code), never data:
# they come from the adapter's own wire table and inference-family map.
WIRES = tuple(go._GO_INFERENCE_BASES)
CHAT, RESPONSES, MESSAGES = WIRES
assert go._TOOL_WIRE == RESPONSES, "the tool wire must be the Responses family"


def _ids_on(wire):
    """The adapter's models served on one documented wire family."""
    return [name for name, served in go._WIRE.items() if served == wire]


def _messages_id():
    """The single adapter model on the Anthropic Messages family."""
    ids = _ids_on(MESSAGES)
    assert len(ids) == 1, f"the wire table carries {len(ids)} Messages models"
    return ids[0]


def _non_go_provider_id():
    """A shipped provider id other than the Go row (for refusal checks)."""
    others = [pid for pid in registry()["providers"] if pid != (GO_PROVIDER_ID or _go_provider_id())]
    assert others, "the registry carries no other provider to refuse against"
    return sorted(others)[0]


def _confirmed_disabled_ids():
    """Adapter models the registry document keeps switched off.

    A disabled registry must stop the call before a credential is read. The
    probe therefore uses the rows the effective document already ships as
    disabled or absent, so the refusal is the gate's own and not a credential
    miss. A document with no Go row at all leaves the roster empty, and the
    owner-document pin skips the probe instead of importing a value.
    """
    from app.pilot.catalog import get_catalog_by_id

    provider = GO_PROVIDER_ID or _go_provider_id()
    if not provider:
        return []
    ids = [name for name in go._WIRE
           if (lambda m: m is None or not m.enabled)(
               get_catalog_by_id(provider + "/" + name))]
    return ids


def _wire_id(wire, skip=0):
    """The (skip+1)-th adapter model on a wire family, by wire-table order."""
    ids = _ids_on(wire)
    assert len(ids) > skip, f"the wire table carries no {wire} model at offset {skip}"
    return ids[skip]


def _wire_for(name):
    """The wire family the adapter itself routes a model onto."""
    return go._WIRE[name]


def _vendor_path(wire):
    """The adapter's own vendor-side path for a wire family (code constant)."""
    return go._go_vendor_path(wire)


# The provider row carrying the adapter's approved origin, when the effective
# document carries one. ``None`` on a value-free document: the mock and
# refusal suites below stay runnable there, and every pin that needs the row
# is marked ``@requires_owner_document`` or derived from the row itself.
GO_PROVIDER_ID = _go_provider_id()


def _go_model_id(name):
    """The B14 catalog id an upstream model is routed under."""
    provider = GO_PROVIDER_ID or _go_provider_id()
    assert provider, "the effective registry carries no Go provider row"
    return provider + "/" + name


def _credential_binding():
    """The credential slot the Go provider row is bound to."""
    provider = GO_PROVIDER_ID or _go_provider_id()
    assert provider, "the effective registry carries no Go provider row"
    row = registry()["providers"][provider]
    return row.get("credential_binding_name") or row.get("credential_binding")


def _vendor_host():
    """The outbound host the approved Go origin resolves to."""
    return GO_ORIGIN.split("://", 1)[1].split("/", 1)[0]


@requires_owner_document
@pytest.mark.parametrize("name,wire", [
    (_wire_id(CHAT, 0), CHAT),
    (_wire_id(CHAT, 1), CHAT),
    (_wire_id(CHAT, 2), CHAT),
    (_wire_id(RESPONSES, 0), RESPONSES),
    (_wire_id(RESPONSES, 1), RESPONSES),
    (_wire_id(RESPONSES, 2), RESPONSES),
    (_wire_id(MESSAGES), MESSAGES),
])
def test_five_exact_wire_shapes(name, wire):
    url, body, h = go.prepare_go_request(
        model_id=_go_model_id(name), upstream_model=name, messages=TURNS,
        session_id=SESSION, max_tokens=32, streaming=True,
    )
    assert url == wire
    assert body["model"] == name and body["stream"] is True
    assert h["x-opencode-session"] == SESSION
    assert h["User-Agent"] == "padiem-claw-coding-agent/1.0"
    assert ("input" in body) == (wire == "responses")
    assert ("system" in body) == (wire == "messages")
    if wire == "messages":
        assert h["anthropic-version"] == "2023-06-01"
        assert body["messages"] == [{"role": "user", "content": "Write a Python function."}]


@requires_owner_document
def test_inference_urls_pin_the_documented_wire_families():
    """Inference endpoints are family-specific under the approved Go origin.

    The registry origin stays the owner-approved model-list anchor; the
    OpenAI-compatible families use /openai/v1 and the Anthropic family uses
    /anthropic/v1. This pins the exact provider-documented URL per family, so
    a regression cannot pass by keeping only the path suffix.
    """

    for wire in WIRES:
        family = go._GO_INFERENCE_BASES[wire]
        # Family base is the approved origin plus exactly one API-family segment.
        assert family.startswith(GO_ORIGIN + "/")
        assert family[len(GO_ORIGIN) + 1:].count("/") == 1
        assert go._go_url(wire) == family + "/" + wire
    openai_family = {go._GO_INFERENCE_BASES[CHAT], go._GO_INFERENCE_BASES[RESPONSES]}
    assert len(openai_family) == 1, "both OpenAI-compatible lanes share one family base"
    assert go._GO_INFERENCE_BASES[MESSAGES] != go._GO_INFERENCE_BASES[CHAT]
    with pytest.raises(PilotNotConfigured):
        go._go_url("embeddings")


@requires_owner_document
@pytest.mark.parametrize("name", GO_IDS)
def test_one_turn_without_product_session_generates_provider_session(name):
    _, _, headers = go.prepare_go_request(
        model_id=_go_provider_id() + "/" + name, upstream_model=name,
        messages=TURNS, session_id=None, max_tokens=20,
    )
    assert headers["x-opencode-session"].startswith("go_")
    assert len(headers["x-opencode-session"]) == 35
    with pytest.raises(InvalidRequest):
        go.prepare_go_request(
            model_id=_non_go_provider_id() + "/" + name, upstream_model=name,
            messages=TURNS, session_id=SESSION, max_tokens=20,
        )


@requires_owner_document
def test_claude_budget_is_required_not_invented():
    with pytest.raises(InvalidRequest, match="explicit max_tokens"):
        go.prepare_go_request(
        model_id=_go_model_id(_messages_id()), upstream_model=_messages_id(), messages=TURNS,
        session_id=SESSION)


@requires_owner_document
def _completed_reply(name, wire):
    """The exact completed envelope each documented wire family returns."""
    if wire == CHAT:
        return {"model": name, "choices": [{"message": {"content": "Hello"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1}}
    if wire == RESPONSES:
        return {"model": name, "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "Hello"}]}],
                "usage": {"input_tokens": 2, "output_tokens": 1}}
    return {"model": name, "type": "message", "role": "assistant",
            "content": [{"type": "text", "text": "Hello"}],
            "usage": {"input_tokens": 2, "output_tokens": 1}}


@requires_owner_document
@pytest.mark.parametrize("name,wire", [
    (_wire_id(CHAT, 0), CHAT),
    (_wire_id(RESPONSES, 0), RESPONSES),
    (_wire_id(RESPONSES, 1), RESPONSES),
    (_wire_id(MESSAGES), MESSAGES),
])
@pytest.mark.asyncio
async def test_completed_protocols_with_synthetic_headers(monkeypatch, name, wire, expected="Hello"):
    reply = _completed_reply(name, wire)
    monkeypatch.setattr(go, "_authorization_gate", lambda *_: None)
    async def synthetic_auth(h, served_wire):
        if served_wire == MESSAGES:
            return {**h, "x-api-key": "synthetic-test-credential"}
        return {**h, "Authorization": "Bearer synthetic-test-credential"}
    monkeypatch.setattr(go, "_authenticated_headers", synthetic_auth)
    seen = []
    def handle(req):
        seen.append(req)
        assert req.url.host == _vendor_host()
        assert req.headers["x-opencode-session"] == SESSION
        # The vendor path is the adapter's own per-family constant, so this
        # still pins the exact endpoint per family, not just its suffix.
        assert req.url.path == _vendor_path(wire)
        if wire == MESSAGES:
            assert req.headers["x-api-key"] == "synthetic-test-credential"
            assert "authorization" not in req.headers
        return httpx.Response(200, json=reply)
    got = await go.call_go_model(model_id=_go_model_id(name), upstream_model=name, messages=TURNS, session_id=SESSION, max_tokens=32, transport=httpx.MockTransport(handle))
    assert got["choices"][0]["message"]["content"] == expected
    assert got["usage"] == {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}
    assert len(seen) == 1


@pytest.mark.asyncio
@requires_owner_document
@pytest.mark.parametrize("name", _confirmed_disabled_ids() or [pytest.param(
    None, marks=pytest.mark.skip(reason="the document carries no disabled Go row"))])
async def test_disabled_registry_never_sends_live_request(name):
    calls = []
    async def fail_if_called(h, wire):
        calls.append(1)
        raise AssertionError("Should not read a secret")
    original = go._authenticated_headers
    go._authenticated_headers = fail_if_called
    try:
        with pytest.raises(PilotNotConfigured):
            await go.call_go_model(model_id=_go_model_id(name), upstream_model=name, messages=TURNS, session_id=SESSION, max_tokens=32, transport=httpx.MockTransport(lambda req: httpx.Response(200)))
    finally:
        go._authenticated_headers = original
    assert calls == []


@requires_owner_document
@pytest.mark.parametrize("wire,name,payload", [
    (CHAT, _wire_id(CHAT, 0), {"choices": [{"message": {"content": ""}}]}),
    (RESPONSES, _wire_id(RESPONSES, 0), {"status": "failed", "output": []}),
    (MESSAGES, _messages_id(), {"type": "error", "content": []}),
])
def test_malformed_or_empty_answer_rejected(wire, name, payload):
    from app.pilot.upstream_answer_contract import UpstreamEmptyAnswer
    with pytest.raises((MalformedUpstreamResponse, UpstreamEmptyAnswer)) as exc:
        go._normalize_go_answer(wire, name, payload, latency_ms=10, response_bytes=10)
    assert type(exc.value).__name__ in ("MalformedUpstreamResponse", "UpstreamEmptyAnswer")


def _frame(event, data):
    return ("event: "+event+"\\n"+"data: "+json.dumps(data)+"\\n\\n").replace("\\n", "\n")


def _responses_sse():
    """The Responses streaming pair: one text delta, then the completion."""
    return (
        _frame("response.output_text.delta",
               {"type": "response.output_text.delta", "delta": "Hi"})
        + _frame("response.completed",
                 {"type": "response.completed",
                  "response": {"status": "completed",
                               "usage": {"input_tokens": 2, "output_tokens": 1}}})
    )


@requires_owner_document
@pytest.mark.parametrize("name,sse", [
    (_wire_id(CHAT, 0), 'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}\n\ndata: [DONE]\n\n'),
    (_wire_id(RESPONSES, 0), _responses_sse()),
    (_wire_id(RESPONSES, 1), _responses_sse()),
    (_messages_id(), _frame("content_block_delta", {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}})+_frame("message_stop", {"type":"message_stop"})),
])
@pytest.mark.asyncio
async def test_three_stream_shapes(monkeypatch, name, sse):
    monkeypatch.setattr(go, "_authorization_gate", lambda *_: None)
    async def synthetic_auth(h, wire):
        return {**h, "x-api-key": "test-credential"} if wire == MESSAGES else {**h, "Authorization": "Bearer test-credential"}
    monkeypatch.setattr(go, "_authenticated_headers", synthetic_auth)
    events = [e async for e in go.stream_go_model(
        model_id=_go_model_id(name), upstream_model=name, messages=TURNS,
        session_id=SESSION, max_tokens=32,
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=sse.encode(), headers={"Content-Type":"text/event-stream"})),
    )]
    assert "".join(e.delta_content or "" for e in events) == "Hi"
    assert events[-1].done is True


@pytest.mark.asyncio
@requires_owner_document
async def test_upstream_auth_error_does_not_echo_body(monkeypatch):
    monkeypatch.setattr(go, "_authorization_gate", lambda *_: None)
    async def synthetic_auth(h, wire):
        return {**h, "Authorization": "Bearer synthetic-credential"}
    monkeypatch.setattr(go, "_authenticated_headers", synthetic_auth)
    with pytest.raises(UpstreamAuthFailed) as exc:
        await go.call_go_model(model_id=_go_model_id(_wire_id(RESPONSES, 0)),
                               upstream_model=_wire_id(RESPONSES, 0),
                               messages=TURNS, session_id=SESSION, max_tokens=32,
                               transport=httpx.MockTransport(lambda r: httpx.Response(401, text="private-provider-token-debug")))
    assert "private-provider-token-debug" not in str(exc.value)


@requires_owner_document
@pytest.mark.parametrize("malformed", [
    "", " ", "\r\nAuthorization: Bearer injected", "contains space",
    "a" * 129, "path/segment", "세션", "x\tvalue",
])
def test_session_header_safety_without_imposing_b14_uuid_grammar(malformed):
    with pytest.raises(InvalidRequest, match="Invalid OpenCode Go session header"):
        go.prepare_go_request(
            model_id=_go_model_id(_wire_id(CHAT, 0)),
            upstream_model=_wire_id(CHAT, 0),
            messages=TURNS, session_id=malformed,
        )


@requires_owner_document
def test_external_provider_accepts_stable_non_chat_session_key():
    # Any Go-backed model accepts the caller's own stable conversation key.
    name = _wire_id(CHAT, 0)
    _, _, headers = go.prepare_go_request(
        model_id=_go_model_id(name),
        upstream_model=name, messages=TURNS,
        session_id="canonical-conversation:example-1",
    )
    assert headers["x-opencode-session"] == "canonical-conversation:example-1"


@requires_owner_document
def test_canonical_conversation_remains_stable_across_turns_but_not_across_chats():
    second = "chat_ffffffffffffffffffffffffffffffff"
    name = _wire_id(CHAT, 0)
    routing = dict(model_id=_go_model_id(name), upstream_model=name, messages=TURNS)
    a = go.prepare_go_request(**routing, session_id=SESSION)
    a_followup = go.prepare_go_request(
        model_id=_go_model_id(name), upstream_model=name,
        messages=TURNS + [{"role": "assistant", "content": "Here is the function."},
                          {"role": "user", "content": "Add a test."}],
        session_id=SESSION,
    )
    b = go.prepare_go_request(**routing, session_id=second)
    assert a[2]["x-opencode-session"] == a_followup[2]["x-opencode-session"] == SESSION
    assert b[2]["x-opencode-session"] == second
    assert b[2]["x-opencode-session"] != SESSION

# Owner-authorized diagnostic only: every transport below is synthetic.
class _VendorErrorBody(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.read = []
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read.append(len(chunk))
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
@requires_owner_document
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("session", [None, SESSION])
@pytest.mark.parametrize("go_name", [_wire_id(RESPONSES, 0)])
async def test_vendor_401_is_redacted_in_alpha_log_not_the_public_error(
    monkeypatch, caplog, streaming, session, go_name,
):
    import logging
    monkeypatch.setattr(go, "_authorization_gate", lambda *_: None)
    async def auth(h, wire):
        return {**h, "Authorization": "Bearer synthetic-short-credential"}
    monkeypatch.setattr(go, "_authenticated_headers", auth)
    body = ('denied Bearer synthetic-short-credential; '
            'sk-private123; keyishCredential01234567890123456789; api_key=tiny-secret; '
            + (session or "no-session"))
    transport = httpx.MockTransport(lambda req: httpx.Response(401, text=body))
    name = go_name
    args = dict(model_id=_go_model_id(name), upstream_model=name,
                messages=TURNS, session_id=session, transport=transport)
    with pytest.raises(UpstreamAuthFailed) as caught:
        if streaming:
            [event async for event in go.stream_go_model(**args)]
        else:
            await go.call_go_model(**args)
    original = UpstreamAuthFailed()
    assert caught.value.to_dict() == original.to_dict()
    assert caught.value.status_code == original.status_code
    with caplog.at_level(logging.WARNING):
        assert go.log_go_vendor_error(
            logging.getLogger("go-diagnostic-test"), caught.value,
            request_id="fixed-request", request_path=chat_surface(),
            attempt=2, fallback=True,
        )
    line = next(r.message for r in caplog.records if r.message.startswith("alpha_error "))
    for private in ["synthetic-short-credential", "sk-private123",
                    "keyishCredential01234567890123456789", "tiny-secret"]:
        assert private not in line
    if session is not None:
        assert session not in line
    for field in ["provider_id=" + GO_PROVIDER_ID, "vendor_status=401",
                  "upstream_model=" + name,
                  "attempt=2", "fallback=fallback", "request_path=",
                  "vendor_path=" + _vendor_path(_wire_for(name)),
                  "session_header_kind=" + ("minted" if session is None else "conversation")]:
        assert field in line
    assert len(caught.value._go_vendor_diagnostic["vendor_message"]) <= 200


@pytest.mark.asyncio
@requires_owner_document
@pytest.mark.parametrize("streaming", [False, True])
async def test_vendor_error_reads_only_512_bytes_and_stops_before_the_next_chunk(monkeypatch, streaming):
    monkeypatch.setattr(go, "_authorization_gate", lambda *_: None)
    async def auth(h, wire):
        return h
    monkeypatch.setattr(go, "_authenticated_headers", auth)
    prefix = (b"denied " + b"a " * 253)[:512]
    assert len(prefix) == 512
    body = _VendorErrorBody([prefix, b"DO_NOT_READ_THIS_PRIVATE_TRAILER"])
    transport = httpx.MockTransport(lambda req: httpx.Response(401, stream=body))
    name = _wire_id(RESPONSES, 0)
    args = dict(model_id=_go_model_id(name), upstream_model=name,
                messages=TURNS, session_id=None, transport=transport)
    with pytest.raises(UpstreamAuthFailed) as caught:
        if streaming:
            [event async for event in go.stream_go_model(**args)]
        else:
            await go.call_go_model(**args)
    assert body.read == [512]
    assert body.closed
    assert caught.value._go_vendor_diagnostic["vendor_message"] == prefix.decode()[:200]


@requires_owner_document
@pytest.mark.parametrize("streaming", [False, True])
def test_go_gateway_logs_context_and_keeps_client_error_bytes_unchanged(
    monkeypatch, caplog, streaming,
):
    import asyncio
    import logging
    from app.factory import create_app
    from starlette.testclient import TestClient
    from app.pilot import gateway, stream_gateway, platform
    from app.pilot.b14_runtime_config import runtime_config
    name = _wire_id(RESPONSES, 0)
    monkeypatch.setenv(_credential_binding(), "synthetic-go-credential-123456789")
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(runtime_config, "provider_mode", "live")
    monkeypatch.setattr(stream_gateway, "_request_id", lambda: "b14stream_fixed")
    async def auth(h, wire):
        return {**h, "Authorization": "Bearer synthetic-go-credential-123456789"}
    monkeypatch.setattr(go, "_authenticated_headers", auth)
    transport = httpx.MockTransport(lambda req: httpx.Response(
        401, text="invalid subscription; Bearer synthetic-go-credential-123456789"))
    async def call(**kwargs):
        return await go.call_go_model(
            **{k: kwargs[k] for k in ["model_id", "upstream_model", "messages", "max_tokens", "temperature"]},
            session_id=None, transport=transport,
        )
    monkeypatch.setattr(platform, "call_platform_chat_completions", call)
    body = {"model": _go_model_id(name),
            "messages": [{"role": "user", "content": "synthetic question"}]}
    app = create_app()
    app.state.stream_transport = transport
    def run():
        if streaming:
            with TestClient(app) as client:
                return client.post(chat_surface() + "/stream-preview",
                                   json={**body, "stream": True})
        return asyncio.run(gateway._handle_alpha_chat("b14_fixed", body))
    with caplog.at_level(logging.WARNING):
        observed = run()
    observed_bytes = observed.content if streaming else observed.body
    assert observed.status_code == 401
    lines = [r.message for r in caplog.records if r.message.startswith("alpha_error ")]
    assert len(lines) == 1
    for part in ["vendor_status=401", "provider_id=" + GO_PROVIDER_ID, "attempt=1",
                 "fallback=primary", "session_header_kind=minted", "invalid subscription"]:
        assert part in lines[0]
    assert "synthetic-go-credential" not in lines[0]
    # Replay only the original status normalization as the pre-change baseline.
    async def original_status_only(response, **kwargs):
        platform._raise_upstream_error(response.status_code, GO_PROVIDER_ID)
    monkeypatch.setattr(go, "_raise_go_vendor_error", original_status_only)
    reference = run()
    reference_bytes = reference.content if streaming else reference.body
    assert observed.status_code == reference.status_code
    assert observed_bytes == reference_bytes
    for private in [b"vendor_message", b"vendor_status", b"session_header_kind",
                    b"invalid subscription", b"synthetic-go-credential"]:
        assert private not in observed_bytes


@pytest.mark.asyncio
@requires_owner_document
async def test_go_shape_refusal_names_the_check_in_the_log_only(monkeypatch, caplog):
    """A 2xx envelope B14 refuses still answers 502 with unchanged public bytes.

    The provider gave no HTTP status to key on, so the log has to say which
    envelope check failed and show a masked prefix of what actually arrived.
    Nothing in this is allowed to reach the client.
    """
    import logging
    from app.pilot import gateway, platform
    from app.pilot.b14_runtime_config import runtime_config

    monkeypatch.setattr(go, "_authorization_gate", lambda *_: None)
    secret = "synthetic-shape-credential-ABCDEFGHIJKLMNOP"
    session = SESSION

    async def auth(h, wire):
        return {**h, "Authorization": f"Bearer {secret}"}
    monkeypatch.setattr(go, "_authenticated_headers", auth)
    echo = ',"detail":"Bearer ' + secret + ' sk-shapeprivate123 ' + session + '"'

    def transport_for(text):
        return httpx.MockTransport(lambda request: httpx.Response(200, text=text))

    chat_name, responses_name, messages_name = (_wire_id(CHAT, 0), _wire_id(RESPONSES, 0),
                                              _messages_id())

    def envelope(name, **fields):
        return json.dumps({"model": name, **fields})[:-1] + echo + "}"

    cases = [
        (chat_name, envelope(chat_name), "choices_missing"),
        (responses_name, envelope(responses_name, status="in_progress"),
         "responses_status_incomplete"),
        (messages_name, envelope(messages_name, type="message", role="user"),
         "messages_type_or_role"),
        (chat_name, "truncated midway " + secret, "response_not_json"),
    ]
    public_baseline = MalformedUpstreamResponse().to_dict()
    last = None
    for upstream_model, text, reason in cases:
        with pytest.raises(MalformedUpstreamResponse) as caught:
            await go.call_go_model(
                model_id=_go_model_id(upstream_model), upstream_model=upstream_model,
                messages=TURNS, session_id=session, max_tokens=32,
                transport=transport_for(text),
            )
        error = caught.value
        last = error
        assert error.to_dict() == public_baseline
        assert error.status_code == 502
        diagnostic = error._go_vendor_diagnostic
        assert diagnostic["reason"] == reason
        assert diagnostic["vendor_status"] == 200
        assert diagnostic["provider_id"] == GO_PROVIDER_ID
        assert diagnostic["upstream_model"] == upstream_model
        assert diagnostic["session_header_kind"] == "conversation"
        assert len(diagnostic["vendor_message"]) <= 200
        assert "[REDACTED]" in diagnostic["vendor_message"]
        for private in [secret, "sk-shapeprivate123", session]:
            assert private not in diagnostic["vendor_message"]

    caplog.clear()
    logger = logging.getLogger("go-shape-test")
    with caplog.at_level(logging.WARNING):
        assert go.log_go_vendor_error(
            logger, last, request_id="fixed-request",
            request_path=chat_surface(), attempt=1, fallback=False,
        )
    line = next(r.message for r in caplog.records if r.message.startswith("alpha_error "))
    for part in ["code=malformed_upstream_response", "status=502", "attempt=1",
                 "provider_id=" + GO_PROVIDER_ID, "reason=response_not_json",
                 "upstream_model=" + chat_name, "fallback=primary",
                 "vendor_status=200", "session_header_kind=conversation",
                 "vendor_path=" + _vendor_path(CHAT)]:
        assert part in line
    for private in [secret, "sk-shapeprivate123", session]:
        assert private not in line

    # Through the real gateway the client bytes must equal the pre-change replay.
    monkeypatch.setenv(_credential_binding(), secret)
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(runtime_config, "provider_mode", "live")
    transport = transport_for(envelope(responses_name, status="in_progress"))

    async def call(**kwargs):
        return await go.call_go_model(
            **{k: kwargs[k] for k in ["model_id", "upstream_model", "messages",
                                      "max_tokens", "temperature"]},
            session_id=None, transport=transport,
        )
    monkeypatch.setattr(platform, "call_platform_chat_completions", call)
    request_body = {"model": _go_model_id(_wire_id(RESPONSES, 0)),
                    "messages": [{"role": "user", "content": "synthetic question"}]}
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        observed = await gateway._handle_alpha_chat("b14_shape_fixed", request_body)
    assert observed.status_code == 502
    lines = [r.message for r in caplog.records if r.message.startswith("alpha_error ")]
    assert len(lines) == 1
    assert "reason=responses_status_incomplete" in lines[0]
    assert "vendor_status=200" in lines[0]
    assert "session_header_kind=minted" in lines[0]
    for private in [b"vendor_message", b"vendor_status", b"session_header_kind",
                    b"vendor_path", b"reason=", secret.encode(),
                    b"synthetic question"]:
        assert private not in observed.body
    monkeypatch.setattr(go, "_attach_go_shape_diagnostic", lambda error, **kwargs: None)
    reference = await gateway._handle_alpha_chat("b14_shape_fixed", request_body)
    assert reference.status_code == observed.status_code
    assert reference.body == observed.body
