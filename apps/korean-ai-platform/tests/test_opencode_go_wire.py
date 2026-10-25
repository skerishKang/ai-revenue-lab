"""Wire-protocol boundary tests; all outbound calls use synthetic MockTransport."""
import json

import httpx
import pytest

from app.pilot import opencode_go_wire as go
from app.pilot.errors import InvalidRequest, PilotNotConfigured, MalformedUpstreamResponse, UpstreamAuthFailed

SESSION = "chat_0123456789abcdef0123456789abcdef"
TURNS = [{"role": "system", "content": "Code only"}, {"role": "user", "content": "Write a Python function."}]
GO_IDS = ["cat-jam-free", "longcat-2.5-preview-free", "step-5-preview-free", "muse-spark-1.3-contributor", "muse-spark-1.2-contributor", "gpt-6-luna", "claude-haiku-5-5"]


@pytest.mark.parametrize("name,wire", [
    ("cat-jam-free", "chat/completions"),
    ("longcat-2.5-preview-free", "chat/completions"),
    ("step-5-preview-free", "chat/completions"),
    ("muse-spark-1.3-contributor", "responses"),
    ("muse-spark-1.2-contributor", "responses"),
    ("gpt-6-luna", "responses"),
    ("claude-haiku-5-5", "messages"),
])
def test_five_exact_wire_shapes(name, wire):
    url, body, h = go.prepare_go_request(
        model_id="opencode-go/" + name, upstream_model=name, messages=TURNS,
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


def test_inference_urls_pin_the_documented_wire_families():
    """Inference endpoints are family-specific under the approved Go origin.

    The registry origin stays the owner-approved model-list anchor; the
    OpenAI-compatible families use /openai/v1 and the Anthropic family uses
    /anthropic/v1. This pins the exact provider-documented URL per family, so
    a regression cannot pass by keeping only the path suffix.
    """

    assert go._go_url("chat/completions") == (
        "https://opencode.ai/inference/go/openai/v1/chat/completions"
    )
    assert go._go_url("responses") == (
        "https://opencode.ai/inference/go/openai/v1/responses"
    )
    assert go._go_url("messages") == (
        "https://opencode.ai/inference/go/anthropic/v1/messages"
    )
    with pytest.raises(PilotNotConfigured):
        go._go_url("embeddings")


@pytest.mark.parametrize("name", GO_IDS)
def test_one_turn_without_product_session_generates_provider_session(name):
    _, _, headers = go.prepare_go_request(
        model_id="opencode-go/" + name, upstream_model=name,
        messages=TURNS, session_id=None, max_tokens=20,
    )
    assert headers["x-opencode-session"].startswith("go_")
    assert len(headers["x-opencode-session"]) == 35
    with pytest.raises(InvalidRequest):
        go.prepare_go_request(
            model_id="zanslab/" + name, upstream_model=name,
            messages=TURNS, session_id=SESSION, max_tokens=20,
        )


def test_claude_budget_is_required_not_invented():
    with pytest.raises(InvalidRequest, match="explicit max_tokens"):
        go.prepare_go_request(model_id="opencode-go/claude-haiku-5-5", upstream_model="claude-haiku-5-5", messages=TURNS, session_id=SESSION)


@pytest.mark.parametrize("name,reply,expected", [
    ("longcat-2.5-preview-free", {"model": "longcat-2.5-preview-free", "choices": [{"message": {"content": "Hello"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 2, "completion_tokens": 1}}, "Hello"),
    ("gpt-6-luna", {"model": "gpt-6-luna", "status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Hello"}]}], "usage": {"input_tokens": 2, "output_tokens": 1}}, "Hello"),
    ("muse-spark-1.2-contributor", {"model": "muse-spark-1.2-contributor", "status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Hello"}]}], "usage": {"input_tokens": 2, "output_tokens": 1}}, "Hello"),
    ("claude-haiku-5-5", {"model": "claude-haiku-5-5", "type": "message", "role": "assistant", "content": [{"type": "text", "text": "Hello"}], "usage": {"input_tokens": 2, "output_tokens": 1}}, "Hello"),
])
@pytest.mark.asyncio
async def test_completed_protocols_with_synthetic_headers(monkeypatch, name, reply, expected):
    monkeypatch.setattr(go, "_authorization_gate", lambda *_: None)
    async def synthetic_auth(h, wire):
        if wire == "messages":
            return {**h, "x-api-key": "synthetic-test-credential"}
        return {**h, "Authorization": "Bearer synthetic-test-credential"}
    monkeypatch.setattr(go, "_authenticated_headers", synthetic_auth)
    seen = []
    def handle(req):
        seen.append(req)
        assert req.url.host == "opencode.ai"
        assert req.headers["x-opencode-session"] == SESSION
        if name.startswith("claude"):
            assert req.url.path == "/inference/go/anthropic/v1/messages"
            assert req.headers["x-api-key"] == "synthetic-test-credential"
            assert "authorization" not in req.headers
        elif name.startswith(("gpt", "muse")):
            assert req.url.path == "/inference/go/openai/v1/responses"
        else:
            assert req.url.path == "/inference/go/openai/v1/chat/completions"
        return httpx.Response(200, json=reply)
    got = await go.call_go_model(model_id="opencode-go/"+name, upstream_model=name, messages=TURNS, session_id=SESSION, max_tokens=32, transport=httpx.MockTransport(handle))
    assert got["choices"][0]["message"]["content"] == expected
    assert got["usage"] == {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["gpt-6-luna", "step-5-preview-free"])
async def test_disabled_registry_never_sends_live_request(name):
    calls = []
    async def fail_if_called(h, wire):
        calls.append(1)
        raise AssertionError("Should not read a secret")
    original = go._authenticated_headers
    go._authenticated_headers = fail_if_called
    try:
        with pytest.raises(PilotNotConfigured):
            await go.call_go_model(model_id="opencode-go/"+name, upstream_model=name, messages=TURNS, session_id=SESSION, max_tokens=32, transport=httpx.MockTransport(lambda req: httpx.Response(200)))
    finally:
        go._authenticated_headers = original
    assert calls == []


@pytest.mark.parametrize("wire,name,payload", [
    ("chat/completions", "longcat-2.5-preview-free", {"choices": [{"message": {"content": ""}}]}),
    ("responses", "gpt-6-luna", {"status": "failed", "output": []}),
    ("messages", "claude-haiku-5-5", {"type": "error", "content": []}),
])
def test_malformed_or_empty_answer_rejected(wire, name, payload):
    from app.pilot.upstream_answer_contract import UpstreamEmptyAnswer
    with pytest.raises((MalformedUpstreamResponse, UpstreamEmptyAnswer)) as exc:
        go._normalize_go_answer(wire, name, payload, latency_ms=10, response_bytes=10)
    assert type(exc.value).__name__ in ("MalformedUpstreamResponse", "UpstreamEmptyAnswer")


def _frame(event, data):
    return ("event: "+event+"\\n"+"data: "+json.dumps(data)+"\\n\\n").replace("\\n", "\n")


@pytest.mark.parametrize("name,sse", [
    ("step-5-preview-free", 'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}\n\ndata: [DONE]\n\n'),
    ("muse-spark-1.3-contributor", _frame("response.output_text.delta", {"type":"response.output_text.delta","delta":"Hi"})+_frame("response.completed", {"type":"response.completed","response":{"status":"completed","usage":{"input_tokens":2,"output_tokens":1}}})),
    ("muse-spark-1.2-contributor", _frame("response.output_text.delta", {"type":"response.output_text.delta","delta":"Hi"})+_frame("response.completed", {"type":"response.completed","response":{"status":"completed","usage":{"input_tokens":2,"output_tokens":1}}})),
    ("claude-haiku-5-5", _frame("content_block_delta", {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}})+_frame("message_stop", {"type":"message_stop"})),
])
@pytest.mark.asyncio
async def test_three_stream_shapes(monkeypatch, name, sse):
    monkeypatch.setattr(go, "_authorization_gate", lambda *_: None)
    async def synthetic_auth(h, wire):
        return {**h, "x-api-key": "test-credential"} if wire == "messages" else {**h, "Authorization": "Bearer test-credential"}
    monkeypatch.setattr(go, "_authenticated_headers", synthetic_auth)
    events = [e async for e in go.stream_go_model(
        model_id="opencode-go/"+name, upstream_model=name, messages=TURNS,
        session_id=SESSION, max_tokens=32,
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=sse.encode(), headers={"Content-Type":"text/event-stream"})),
    )]
    assert "".join(e.delta_content or "" for e in events) == "Hi"
    assert events[-1].done is True


@pytest.mark.asyncio
async def test_upstream_auth_error_does_not_echo_body(monkeypatch):
    monkeypatch.setattr(go, "_authorization_gate", lambda *_: None)
    async def synthetic_auth(h, wire):
        return {**h, "Authorization": "Bearer synthetic-credential"}
    monkeypatch.setattr(go, "_authenticated_headers", synthetic_auth)
    with pytest.raises(UpstreamAuthFailed) as exc:
        await go.call_go_model(model_id="opencode-go/gpt-6-luna", upstream_model="gpt-6-luna", messages=TURNS, session_id=SESSION, max_tokens=32,
                               transport=httpx.MockTransport(lambda r: httpx.Response(401, text="private-provider-token-debug")))
    assert "private-provider-token-debug" not in str(exc.value)


@pytest.mark.parametrize("malformed", [
    "", " ", "\r\nAuthorization: Bearer injected", "contains space",
    "a" * 129, "path/segment", "세션", "x\tvalue",
])
def test_session_header_safety_without_imposing_b14_uuid_grammar(malformed):
    with pytest.raises(InvalidRequest, match="Invalid OpenCode Go session header"):
        go.prepare_go_request(
            model_id="opencode-go/longcat-2.5-preview-free",
            upstream_model="longcat-2.5-preview-free",
            messages=TURNS, session_id=malformed,
        )


def test_external_provider_accepts_stable_non_chat_session_key():
    _, _, headers = go.prepare_go_request(
        model_id="opencode-go/cat-jam-free",
        upstream_model="cat-jam-free", messages=TURNS,
        session_id="canonical-conversation:example-1",
    )
    assert headers["x-opencode-session"] == "canonical-conversation:example-1"


def test_canonical_conversation_remains_stable_across_turns_but_not_across_chats():
    second = "chat_ffffffffffffffffffffffffffffffff"
    a = go.prepare_go_request(
        model_id="opencode-go/step-5-preview-free",
        upstream_model="step-5-preview-free",
        messages=TURNS, session_id=SESSION,
    )
    a_followup = go.prepare_go_request(
        model_id="opencode-go/step-5-preview-free",
        upstream_model="step-5-preview-free",
        messages=TURNS + [{"role": "assistant", "content": "Here is the function."},
                          {"role": "user", "content": "Add a test."}],
        session_id=SESSION,
    )
    b = go.prepare_go_request(
        model_id="opencode-go/step-5-preview-free",
        upstream_model="step-5-preview-free",
        messages=TURNS, session_id=second,
    )
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
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("session", [None, SESSION])
async def test_vendor_401_is_redacted_in_alpha_log_not_the_public_error(
    monkeypatch, caplog, streaming, session,
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
    args = dict(model_id="opencode-go/muse-spark-1.3-contributor",
                upstream_model="muse-spark-1.3-contributor",
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
            request_id="fixed-request", request_path="/api/pilot/v1/chat/completions",
            attempt=2, fallback=True,
        )
    line = next(r.message for r in caplog.records if r.message.startswith("alpha_error "))
    for private in ["synthetic-short-credential", "sk-private123",
                    "keyishCredential01234567890123456789", "tiny-secret"]:
        assert private not in line
    if session is not None:
        assert session not in line
    for field in ["provider_id=opencode-go", "vendor_status=401",
                  "upstream_model=muse-spark-1.3-contributor",
                  "attempt=2", "fallback=fallback", "request_path=",
                  "vendor_path=/inference/go/openai/v1/responses",
                  "session_header_kind=" + ("minted" if session is None else "conversation")]:
        assert field in line
    assert len(caught.value._go_vendor_diagnostic["vendor_message"]) <= 200


@pytest.mark.asyncio
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
    args = dict(model_id="opencode-go/muse-spark-1.3-contributor",
                upstream_model="muse-spark-1.3-contributor",
                messages=TURNS, session_id=None, transport=transport)
    with pytest.raises(UpstreamAuthFailed) as caught:
        if streaming:
            [event async for event in go.stream_go_model(**args)]
        else:
            await go.call_go_model(**args)
    assert body.read == [512]
    assert body.closed
    assert caught.value._go_vendor_diagnostic["vendor_message"] == prefix.decode()[:200]


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
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_11", "synthetic-go-credential-123456789")
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
    body = {"model": "opencode-go/muse-spark-1.3-contributor",
            "messages": [{"role": "user", "content": "synthetic question"}]}
    app = create_app()
    app.state.stream_transport = transport
    def run():
        if streaming:
            with TestClient(app) as client:
                return client.post("/api/pilot/v1/chat/completions/stream-preview",
                                   json={**body, "stream": True})
        return asyncio.run(gateway._handle_alpha_chat("b14_fixed", body))
    with caplog.at_level(logging.WARNING):
        observed = run()
    observed_bytes = observed.content if streaming else observed.body
    assert observed.status_code == 401
    lines = [r.message for r in caplog.records if r.message.startswith("alpha_error ")]
    assert len(lines) == 1
    for part in ["vendor_status=401", "provider_id=opencode-go", "attempt=1",
                 "fallback=primary", "session_header_kind=minted", "invalid subscription"]:
        assert part in lines[0]
    assert "synthetic-go-credential" not in lines[0]
    # Replay only the original status normalization as the pre-change baseline.
    async def original_status_only(response, **kwargs):
        platform._raise_upstream_error(response.status_code, "opencode-go")
    monkeypatch.setattr(go, "_raise_go_vendor_error", original_status_only)
    reference = run()
    reference_bytes = reference.content if streaming else reference.body
    assert observed.status_code == reference.status_code
    assert observed_bytes == reference_bytes
    for private in [b"vendor_message", b"vendor_status", b"session_header_kind",
                    b"invalid subscription", b"synthetic-go-credential"]:
        assert private not in observed_bytes


@pytest.mark.asyncio
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

    cases = [
        ("cat-jam-free", '{"model":"cat-jam-free"' + echo + "}", "choices_missing"),
        ("muse-spark-1.3-contributor",
         '{"model":"muse-spark-1.3-contributor","status":"in_progress"' + echo + "}",
         "responses_status_incomplete"),
        ("claude-haiku-5-5",
         '{"model":"claude-haiku-5-5","type":"message","role":"user"' + echo + "}",
         "messages_type_or_role"),
        ("cat-jam-free", "truncated midway " + secret, "response_not_json"),
    ]
    public_baseline = MalformedUpstreamResponse().to_dict()
    last = None
    for upstream_model, text, reason in cases:
        with pytest.raises(MalformedUpstreamResponse) as caught:
            await go.call_go_model(
                model_id="opencode-go/" + upstream_model, upstream_model=upstream_model,
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
        assert diagnostic["provider_id"] == "opencode-go"
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
            request_path="/api/pilot/v1/chat/completions", attempt=1, fallback=False,
        )
    line = next(r.message for r in caplog.records if r.message.startswith("alpha_error "))
    for part in ["code=malformed_upstream_response", "status=502", "attempt=1",
                 "provider_id=opencode-go", "reason=response_not_json",
                 "upstream_model=cat-jam-free", "fallback=primary",
                 "vendor_status=200", "session_header_kind=conversation",
                 "vendor_path=/inference/go/openai/v1/chat/completions"]:
        assert part in line
    for private in [secret, "sk-shapeprivate123", session]:
        assert private not in line

    # Through the real gateway the client bytes must equal the pre-change replay.
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_11", secret)
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(runtime_config, "provider_mode", "live")
    transport = transport_for('{"model":"muse-spark-1.3-contributor",'
                              '"status":"in_progress"' + echo + "}")

    async def call(**kwargs):
        return await go.call_go_model(
            **{k: kwargs[k] for k in ["model_id", "upstream_model", "messages",
                                      "max_tokens", "temperature"]},
            session_id=None, transport=transport,
        )
    monkeypatch.setattr(platform, "call_platform_chat_completions", call)
    request_body = {"model": "opencode-go/muse-spark-1.3-contributor",
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
