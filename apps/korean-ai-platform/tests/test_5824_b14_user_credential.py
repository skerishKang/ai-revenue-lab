"""#5824 PR-3a: B14 serves a credential that arrives inside the request body.

Chat's BYOK registration hands a verified customer key to the Engine lane as
``user_credential_ref``. B14 must then call that provider with that key and
nothing else: no pool credential, no roster, no fallback, and never a trace of
the key value in a response, a log line, an exception or a ledger row.

Every test here uses a synthetic key and a mocked transport, so no provider is
contacted. The synthetic value is a sentinel that would be conspicuous in any
output that leaked it.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.factory import create_app
from app.pilot import gateway as gw
from app.pilot import platform as plat
from app.pilot import platform_secrets as psecrets
from app.pilot import router_core as rcore
from app.pilot import stream_gateway as sg
from app.pilot import worker_env
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.deferred_writes import drain
from app.pilot.user_credential import UserCredential, credential_from_body

CHAT_COMPLETIONS = "/api/pilot/v1/chat/completions"
STREAM_PREVIEW = "/api/pilot/v1/chat/completions/stream-preview"
AUTO_PREVIEW = "/api/pilot/v1/chat/completions/auto-stream-preview"

SENTINEL = "sk-b14-synthetic-0123456789abcdef"
UPSTREAM_MODEL = "gpt-4.1-mini"
REQUESTED_MODEL = f"openai/{UPSTREAM_MODEL}"

CREDENTIAL = {
    "provider": "openai",
    "endpoint": "https://api.openai.com/v1",
    "model": UPSTREAM_MODEL,
    "key": SENTINEL,
}


def _reference(document: dict | str | None = CREDENTIAL) -> dict:
    """The exact shape the Engine bridge writes: a JSON string, request-scoped."""
    body = {
        "model": REQUESTED_MODEL,
        "messages": [{"role": "user", "content": "한 마디만"}],
    }
    if document is not None:
        body["user_credential_ref"] = document if isinstance(document, str) else json.dumps(
            document, ensure_ascii=False, separators=(",", ":")
        )
    return body


def _completed(body_text: str = "답", tokens=(3, 4, 7)) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=json.dumps({
            "id": "chatcmpl-synthetic", "object": "chat.completion",
            "model": UPSTREAM_MODEL,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": body_text},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1],
                      "total_tokens": tokens[2]},
        }).encode("utf-8"),
    )


def _sse(text: str = "답") -> httpx.Response:
    frames = [
        f"data: {json.dumps({'id': 'chatcmpl-synthetic', 'model': UPSTREAM_MODEL, 'choices': [{'index': 0, 'delta': {'content': text}, 'finish_reason': None}]})}\n\n",
        f"data: {json.dumps({'id': 'chatcmpl-synthetic', 'model': UPSTREAM_MODEL, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7}})}\n\n",
        "data: [DONE]\n\n",
    ]
    return httpx.Response(
        200, headers={"content-type": "text/event-stream"}, content="".join(frames).encode()
    )


@pytest.fixture()
def live_lane(monkeypatch):
    """Live provider mode, so a request really reaches the (mocked) transport."""
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(runtime_config, "provider_mode", "live")
    yield


@pytest.fixture()
def captured(monkeypatch):
    """The outbound requests and the finished ledger rows of one run."""
    calls: list[httpx.Request] = []
    written: list = []

    async def capture(record):
        written.append(record)
        return "written"

    # Each lane holds its own imported name, so both bindings are captured.
    monkeypatch.setattr(gw, "record_call", capture)
    monkeypatch.setattr(sg, "record_call", capture)
    return calls, written


def _transport(calls: list[httpx.Request], responder) -> httpx.AsyncClient:
    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return responder(request)

    return httpx.MockTransport(respond)


def _app_with(transport):
    app = create_app()
    app.state.stream_transport = transport
    return app


# ---------------------------------------------------------------------------
# 1. the key is used, and it is used nowhere else
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_request_key_is_the_only_credential_sent_and_it_never_returns(
    live_lane, monkeypatch, captured
):
    """Bearer key on the wire, and the value absent from every output surface."""
    calls, written = captured
    monkeypatch.setattr(
        plat, "call_platform_chat_completions",
        lambda **_k: pytest.fail("the pool lane must not be reached"),
    )
    transport = _transport(calls, lambda _request: _completed())
    app = _app_with(transport)

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(CHAT_COMPLETIONS, json=_reference())
        text = response.text
    await drain()

    assert response.status_code == 200, text
    assert response.json()["choices"][0]["message"]["content"] == "답"

    # The outbound request carries the caller's own key to B14's fixed address.
    assert len(calls) == 1
    sent = calls[0]
    assert str(sent.url) == "https://api.openai.com/v1/chat/completions"
    assert sent.headers["authorization"] == f"Bearer {SENTINEL}"
    assert json.loads(sent.content)["model"] == UPSTREAM_MODEL

    # Response body, ledger row and the credential object itself.
    assert SENTINEL not in text
    assert len(written) == 1
    record = written[0]
    assert record.credential_source == "user"
    assert SENTINEL not in json.dumps(record.to_row(), default=str)
    assert SENTINEL not in json.dumps(
        [attempt.to_row() for attempt in record.attempts], default=str
    )
    assert record.attempt_count == 1 and record.fallback_used is False
    assert record.selected_provider == "openai"
    assert record.selected_upstream_model == UPSTREAM_MODEL
    assert record.endpoint == CHAT_COMPLETIONS


@pytest.mark.asyncio
async def test_no_server_owned_credential_binding_is_read_for_a_request_key(
    live_lane, monkeypatch, captured
):
    """The pool plane is not consulted at all, not merely unused afterwards."""
    calls, _written = captured

    def _untouched(*_args, **_kwargs):
        raise AssertionError("the pool credential plane was consulted")

    original_load = worker_env.load_request_secret

    async def _no_provider_binding_load(name, *args, **kwargs):
        # The caller proof is a deployment secret, not a Provider credential.
        # Anything else that reaches this function would be the pool plane.
        if name != "PADIEM_B14_SERVICE_PROOF_SECRET":
            raise AssertionError(f"a server-owned Provider binding was read: {name}")
        return await original_load(name, *args, **kwargs)

    transport = _transport(calls, lambda _request: _completed())
    app = _app_with(transport)

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        # The application build itself may look at platform health; nothing may
        # happen on that plane once the request is in flight.
        monkeypatch.setattr(psecrets, "ensure_route_secrets", _untouched)
        monkeypatch.setattr(psecrets, "resolve_secret", _untouched)
        monkeypatch.setattr(rcore, "resolve_route", _untouched)
        monkeypatch.setattr(plat, "call_platform_chat_completions", _untouched)
        monkeypatch.setattr(worker_env, "load_request_secret", _no_provider_binding_load)

        response = client.post(CHAT_COMPLETIONS, json=_reference())
    await drain()

    assert response.status_code == 200, response.text
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_provider_failure_is_the_answer_and_no_second_candidate_runs(
    live_lane, captured, monkeypatch
):
    """401 from the caller's provider: one attempt, the code passes through."""
    calls, written = captured
    monkeypatch.setattr(
        plat, "call_platform_chat_completions",
        lambda **_k: pytest.fail("a fallback candidate would have been a pool call"),
    )
    transport = _transport(
        calls, lambda _request: httpx.Response(401, json={"error": {"code": "invalid_api_key"}})
    )
    app = _app_with(transport)

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(CHAT_COMPLETIONS, json=_reference())
    await drain()

    payload = response.json()
    assert response.status_code == 401
    assert payload["error"]["code"] == "upstream_auth_failed"
    assert payload["error"]["attempt_count"] == 1
    assert payload["error"]["fallback_used"] is False
    assert len(calls) == 1, "a second outbound call would be a fallback"

    assert len(written) == 1
    record = written[0]
    assert (record.outcome, record.error_code, record.credential_source) == (
        "error", "upstream_auth_failed", "user",
    )
    assert record.fallback_used is False and record.fallback_depth == 0


@pytest.mark.asyncio
async def test_the_gateway_answers_an_internal_error_without_the_key(
    live_lane, captured, monkeypatch
):
    """The unexpected-exception branch, observed through the handler itself."""
    _calls, written = captured

    async def explode(**_kwargs):
        raise RuntimeError(f"provider refused: Bearer {SENTINEL}")

    monkeypatch.setattr(plat, "call_user_credential_chat_completions", explode)

    from starlette.testclient import TestClient

    app = create_app()
    with TestClient(app) as client:
        response = client.post(CHAT_COMPLETIONS, json=_reference())
    await drain()

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert SENTINEL not in response.text
    assert len(written) == 1
    record = written[0]
    assert record.error_code == "internal_error"
    assert record.credential_source == "user"
    assert SENTINEL not in json.dumps(record.to_row(), default=str)


@pytest.mark.asyncio
async def test_the_credential_value_never_reaches_a_log_line(
    live_lane, captured, caplog
):
    """Every log record on a user-credential call is checked for the value."""
    calls, _written = captured
    transport = _transport(calls, lambda _request: _completed())
    app = _app_with(transport)

    from starlette.testclient import TestClient

    with caplog.at_level("DEBUG"):
        with TestClient(app) as client:
            response = client.post(CHAT_COMPLETIONS, json=_reference())
            client.post(  # and the failure path, which is the louder one
                CHAT_COMPLETIONS,
                json=_reference({**CREDENTIAL, "key": "sk-b14-synthetic-999988887777"}),
            )
    await drain()

    assert response.status_code == 200
    rendered = "\n".join([record.getMessage() for record in caplog.records])
    assert SENTINEL not in rendered
    assert "sk-b14-synthetic-999988887777" not in rendered


# ---------------------------------------------------------------------------
# 2. the lane boundary: what is refused, and what stays exactly as it was
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unsupported_wire_is_refused_before_any_call(live_lane, captured):
    """anthropic stays on the caller's direct path; B14 names the reason."""
    calls, written = captured
    app = _app_with(_transport(calls, lambda _r: _completed()))

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(CHAT_COMPLETIONS, json=_reference({
            "provider": "anthropic", "endpoint": "https://api.anthropic.com/v1",
            "model": "claude-sonnet-4-5", "key": SENTINEL,
        }))
    await drain()

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "user_credential_unsupported_via_b14"
    assert calls == [] and written == []


@pytest.mark.asyncio
async def test_an_arbitrary_endpoint_is_never_contacted(live_lane, captured):
    """The caller's endpoint string is a claim, not an address B14 dials."""
    calls, _written = captured
    app = _app_with(_transport(calls, lambda _r: _completed()))

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(CHAT_COMPLETIONS, json=_reference({
            "provider": "openai", "endpoint": "https://attacker.example.com/v1",
            "model": UPSTREAM_MODEL, "key": SENTINEL,
        }))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "user_credential_endpoint_unsupported"
    assert calls == []


@pytest.mark.asyncio
async def test_a_malformed_credential_is_refused_without_quoting_it(
    live_lane, captured
):
    """A broken document is a shape problem; the value stays unprinted."""
    calls, _written = captured
    app = _app_with(_transport(calls, lambda _r: _completed()))
    broken = '{"provider": "openai", "model": "gpt-4.1-mini", "key": "' + SENTINEL + '"}'

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        missing_field = client.post(CHAT_COMPLETIONS, json=_reference(broken))
        not_json = client.post(CHAT_COMPLETIONS, json=_reference(SENTINEL + " not json"))
        placeholder = client.post(CHAT_COMPLETIONS, json=_reference({
            **CREDENTIAL, "key": "sk-your-key-here-1234567890"
        }))
    await drain()

    assert missing_field.json()["error"]["code"] == "user_credential_invalid"
    assert not_json.json()["error"]["code"] == "user_credential_invalid"
    assert placeholder.json()["error"]["code"] == "placeholder_key_rejected"
    for response in (missing_field, not_json, placeholder):
        assert SENTINEL not in response.text
    assert calls == []


@pytest.mark.asyncio
async def test_b14_auto_is_an_opaque_caller_model_under_a_request_key(live_lane, captured):
    """B7: no automatic route exists. Under a request credential the retired id
    is an opaque model name passed to the caller's own provider — the platform
    contributes no routing of its own."""
    calls, _written = captured
    app = _app_with(_transport(calls, lambda _r: _completed()))

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(
            CHAT_COMPLETIONS,
            json={**_reference(), "model": "b14/auto"},
        )
    assert response.status_code == 200
    assert len(calls) == 1
    assert SENTINEL not in response.text


@pytest.mark.asyncio
async def test_the_auto_stream_lane_is_gone_for_a_credential_holder(
    live_lane, captured
):
    """B7: a credential cannot borrow the platform's own auto roster because
    the auto surface no longer exists and the retired id is refused outright."""
    calls, _written = captured
    app = _app_with(_transport(calls, lambda _r: _sse()))

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        auto_preview = client.post(
            AUTO_PREVIEW, json={**_reference(), "stream": True, "model": REQUESTED_MODEL}
        )
        auto_model = client.post(
            CHAT_COMPLETIONS, json={**_reference(), "model": "b14/auto"}
        )
    await drain()

    assert auto_preview.status_code == 404
    # The retired id under a credential is an opaque caller model now: the
    # request is dispatched to the caller's own provider (this fake answers an
    # SSE body on the completed path, so the bounded 502 is the provider's
    # answer) and no platform auto surface answers it.
    assert auto_model.status_code == 502
    for response in (auto_preview, auto_model):
        assert SENTINEL not in response.text
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_mock_mode_never_sends_the_key_and_leaves_no_execution_row(
    captured, monkeypatch
):
    """Mock mode is the developer default: zero provider calls, zero ledger rows.

    The same rule the catalog lane holds — a simulated answer is not an act of
    consumption — applies here, and a caller key stays inside the process.
    """
    calls, written = captured
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    monkeypatch.setattr(runtime_config, "provider_mode", "mock")

    def _forbidden(_request):
        raise AssertionError("mock mode must not reach the transport")

    app = _app_with(_transport(calls, _forbidden))

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(CHAT_COMPLETIONS, json=_reference())
    await drain()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["business14"]["credential_source"] == "user"
    assert payload["business14"]["provider_mode"] == "mock"
    assert SENTINEL not in response.text
    assert calls == []
    assert written == []


def test_a_request_without_a_credential_keeps_the_exact_body_contract():
    """The pool lane's normalized body has the key set it had before #5824.

    A field that only the credential lane uses must not appear in every parsed
    body: that would widen the contract of the lane that did not change.
    """
    body = gw._validate_body({
        "model": REQUESTED_MODEL,
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.2,
    })
    assert set(body) == {
        "model", "messages", "temperature", "max_tokens", "model_parameters",
        "tools", "tool_choice", "business14",
    }
    assert "user_credential" not in body


@pytest.mark.asyncio
async def test_the_platform_lane_still_labels_its_own_row_pool(
    live_lane, captured, monkeypatch
):
    """The column defaults, and the catalog lane never claims a caller credential.

    A row that says ``pool`` is the platform's own consumption; adding the label
    must not turn an ordinary catalog call into something it was not.
    """
    from app.pilot.tier_fallback import TIER_DEFAULT_B14_MODEL

    _calls, written = captured

    async def answered(**_kwargs):
        return {
            "id": "cmpl_pool", "object": "chat.completion", "model": "upstream-pool",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "_live": True, "_requested_upstream_model": "upstream-pool",
            "_actual_response_model": "upstream-pool",
        }

    monkeypatch.setattr(plat, "call_platform_chat_completions", answered)
    monkeypatch.setattr(
        rcore, "_credential_status_for",
        lambda cm: (True, "present", "platform_secret", cm.platform_provider_id),
    )
    monkeypatch.setattr(rcore, "_platform_secret_present", lambda cm: True)

    body = gw._validate_body({
        "model": TIER_DEFAULT_B14_MODEL,
        "messages": [{"role": "user", "content": "hi"}],
    })
    response = await gw._handle_alpha_chat("b14req_pool01", body)
    await drain()

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert "credential_source" not in payload["business14"]
    assert len(written) == 1
    assert written[0].credential_source == "pool"


@pytest.mark.asyncio
async def test_a_tool_declaration_is_refused_for_a_key_B14_has_no_record_of(
    live_lane, captured
):
    """#5536's rule holds on the new lane instead of being silently dropped."""
    calls, _written = captured
    app = _app_with(_transport(calls, lambda _r: _completed()))
    payload = _reference()
    payload["tools"] = [{
        "type": "function",
        "function": {"name": "lookup", "parameters": {"type": "object", "properties": {}}},
    }]

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(CHAT_COMPLETIONS, json=payload)
    await drain()

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "tools_not_supported"
    assert calls == []


# ---------------------------------------------------------------------------
# 3. the streaming lane
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_stream_preview_lane_uses_the_request_key_with_one_attempt(
    live_lane, captured, monkeypatch
):
    """Preview streaming is the same boundary: caller key, no roster, no switch."""
    calls, written = captured

    async def _no_pool(**_kwargs):
        raise AssertionError("the streaming pool lane was reached")

    monkeypatch.setattr(plat, "stream_platform_chat_completions", _no_pool)
    monkeypatch.setattr(rcore, "resolve_route", _no_pool)
    transport = _transport(calls, lambda _request: _sse())
    app = _app_with(transport)

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        with client.stream(
            "POST", STREAM_PREVIEW, json={**_reference(), "stream": True}
        ) as stream:
            body = "".join(stream.iter_text())
    await drain()

    assert "답" in body
    first_frame = json.loads(body.split("data: ")[1].split("\n\n")[0])
    assert first_frame["business14"]["credential_source"] == "user"
    assert SENTINEL not in body
    assert len(calls) == 1
    assert calls[0].headers["authorization"] == f"Bearer {SENTINEL}"

    assert len(written) == 1
    record = written[0]
    assert record.streaming is True
    assert record.credential_source == "user"
    assert record.attempt_count == 1 and record.fallback_used is False
    assert record.protocol == "chat/completions"


@pytest.mark.asyncio
async def test_a_streaming_provider_failure_never_switches_route(
    live_lane, captured
):
    """A 429 before the first token is the answer, not a hand-off."""
    calls, written = captured
    transport = _transport(
        calls, lambda _request: httpx.Response(429, json={"error": {"message": "slow down"}})
    )
    app = _app_with(transport)

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(STREAM_PREVIEW, json={**_reference(), "stream": True})
    await drain()

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "upstream_rate_limited"
    assert len(calls) == 1
    assert len(written) == 1
    assert written[0].credential_source == "user"
    assert written[0].outcome == "error"


# ---------------------------------------------------------------------------
# 4. the resolved route is B14's, whatever the caller spelled
# ---------------------------------------------------------------------------


def test_the_alias_and_the_trailing_slash_resolve_to_b14s_own_address():
    """One provider, one address; the caller's spelling decides nothing."""
    from urllib.parse import urlparse

    google = credential_from_body({
        "user_credential": {
            "provider": "gemini",
            "endpoint": "https://generativelanguage.googleapis.com/v1beta/",
            "model": "gemini-2.5-flash",
            "key": "AIza-synthetic-value-1234567890",
        }
    })
    assert isinstance(google, UserCredential)
    assert google.provider_id == "google"
    assert google.chat_completions_url == (
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    assert urlparse(google.origin).hostname == "generativelanguage.googleapis.com"

    openai = credential_from_body({"user_credential": CREDENTIAL})
    assert openai.chat_completions_url == "https://api.openai.com/v1/chat/completions"
    assert openai.allowed_hosts == ("api.openai.com",)


def test_the_credential_object_does_not_render_its_own_key():
    credential = credential_from_body({"user_credential": CREDENTIAL})
    assert SENTINEL not in repr(credential)
    assert SENTINEL not in str(credential)
    assert SENTINEL not in str({"body": {"user_credential": credential}})


@pytest.mark.asyncio
async def test_opencode_go_user_key_uses_fixed_origin_and_user_ledger(live_lane, captured):
    from starlette.testclient import TestClient
    calls, written = captured
    app = _app_with(_transport(calls, lambda _request: _completed()))
    credential = {"provider": "opencode-go",
                  "endpoint": "https://opencode.ai/inference/go/v1",
                  "model": "beam-free", "key": SENTINEL}
    body = _reference(credential)
    body["model"] = "opencode-go/beam-free"
    with TestClient(app) as client:
        response = client.post(CHAT_COMPLETIONS, json=body)
    await drain()
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert str(calls[0].url) == "https://opencode.ai/inference/go/v1/chat/completions"
    assert json.loads(calls[0].content)["model"] == "beam-free"
    assert calls[0].headers["authorization"] == "Bearer " + SENTINEL
    assert len(written) == 1 and written[0].credential_source == "user"
    assert SENTINEL not in response.text
    assert SENTINEL not in json.dumps(written[0].to_row(), default=str)


def test_opencode_go_user_key_rejects_noncanonical_endpoint():
    from app.pilot.errors import PilotError
    with pytest.raises(PilotError) as error:
        credential_from_body({"user_credential": {
            "provider": "opencode-go", "endpoint": "https://example.invalid/v1",
            "model": "beam-free", "key": SENTINEL,
        }})
    assert error.value.code == "user_credential_endpoint_unsupported"
