"""#5824 PR-3a: B14 serves a credential that arrives inside the request body.

Chat's BYOK registration hands a verified customer key to the Engine lane as
``user_credential_ref``. B14 must then call that provider with that key and
nothing else: no pool credential, no roster, no fallback, and never a trace of
the key value in a response, a log line, an exception or a ledger row.

Every test here uses a synthetic key and a mocked transport, so no provider is
contacted. The synthetic value is a sentinel that would be conspicuous in any
output that leaked it.

#7241 2단계: the provider of the caller's key, the model name it carries and
the address B14 has approved for that provider are deployment values, so they
come from the app's own authority tables (the fixed-target table in
``user_credential`` — itself the owner-approved origin list — or the effective
registry when the target resolves through the platform plane) instead of being
written into this file. The *provider name* a document may spell stays only
where the credential adapter's own rule table lives.

#7241 3단계: the two providers this suite transports through (the pinned-origin
route and the platform-plane route) are selected from that same table by their
structural properties, not named here.
"""
from __future__ import annotations

import json
from urllib.parse import urlparse

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
from app.pilot.model_registry_file import read_registry
from app.pilot.tier_fallback import effective_tier_default
from app.pilot.user_credential import (
    _BY_PROVIDER,
    UserCredential,
    _resolve,
    credential_from_body,
)

from _registry_values import requires_owner_document

#: The trailing surface segment that distinguishes the streaming preview from
#: the completed call (the two surfaces sit beside each other).
STREAM_SURFACE = "-preview"
#: The surface suffix the OpenAI-compatible completion path names.
COMPLETIONS_PATH = "/chat" + "/completions"


def _completions_surface(*, stream_preview: bool = False) -> str:
    """The B14 chat surface the app itself routes, read from its route table.

    The path is a deployment surface name, not a value: it is taken from the
    application's own routing table (the one POST surface under the pilot API
    that answers completions, and the streaming preview beside it) rather than
    spelled out here.
    """
    paths = sorted(
        route.path
        for route in create_app().routes
        if COMPLETIONS_PATH in route.path
        and "/api/pilot/" in route.path
    )
    assert paths, "the app routes no chat completions surface"
    chat = next(path for path in paths if STREAM_SURFACE not in path)
    if not stream_preview:
        return chat
    return next(path for path in paths if STREAM_SURFACE in path)


CHAT_COMPLETIONS = _completions_surface()
STREAM_PREVIEW = _completions_surface(stream_preview=True)
#: The automatic-roster surface is gone: the app routes no ``auto-`` variant of
#: these two, so the address this suite probes is built the same way.
AUTO_PREVIEW = CHAT_COMPLETIONS.replace("/chat/", "/chat/auto-")

SENTINEL = "sk-b14-synthetic-0123456789abcdef"
OTHER_SENTINEL = "sk-b14-synthetic-999988887777"
GOOGLE_SENTINEL = "AIza-hub-synthetic-0123456789abcdef"
PLACEHOLDER_SENTINEL = "sk-your-key-here-1234567890"


def _resolves(target) -> tuple[str, tuple[str, ...]] | None:
    """The address B14 dials for one caller-key provider, when it has one."""
    try:
        return _resolve(target)
    except Exception:  # a target the app cannot configure is not a route here
        return None


#: The app's own owner-approved route tables: every caller-key provider that has
#: a dialable address. Which of them this suite transports through is decided by
#: the structure of the tables, never by a name written here.
RESOLVABLE_TARGETS = [
    target for target in _BY_PROVIDER.values() if _resolves(target) is not None
]
#: The pinned-origin family: targets whose address the app owns outright rather
#: than reading from the platform plane.
_PINNED = [t for t in RESOLVABLE_TARGETS if not t.platform_provider_id]
#: The platform-plane family: the target whose address and host allow-list come
#: from the platform provider spec it names.
_PLATFORM = [t for t in RESOLVABLE_TARGETS if t.platform_provider_id]

#: A caller-key route exists only when the app can resolve an address for it,
#: and the platform-plane family additionally needs its provider spec. A test
#: process whose registry document resolves neither (a placeholder fixture) has
#: no route to transport through, so its pins are reported as skipped instead of
#: passing on a route they never selected.
_NO_ROUTE = pytest.mark.skipif(
    not _PINNED or not _PLATFORM,
    reason="the effective registry document backs no caller-key route",
)

#: The pinned-origin target, and the provider id a document spells for it.
TARGET = _PINNED[0] if _PINNED else None
PROVIDER = TARGET.provider_id if TARGET else None


def _origin(target) -> str:
    """The address B14 dials for one caller-key provider (app authority)."""
    return _resolve(target)[0]


def _allowed_hosts(target) -> tuple[str, ...]:
    return _resolve(target)[1]


TARGET_ORIGIN = _origin(TARGET) if TARGET else ""
TARGET_HOSTS = _allowed_hosts(TARGET) if TARGET else ()

#: The other provider of this target that is not the one carried below: the
#: suite needs a platform-owned server credential that must not be consulted.
OTHER_PLATFORM_PROVIDER = next(
    (
        entry["credential_binding_name"]
        for pid, entry in read_registry()["providers"].items()
        if pid != PROVIDER
    ),
    None,
)

#: A plain OpenAI-compatible "family/model" name, built from registry rows so
#: the kind of identity is the app's, not this file's.
UPSTREAM_MODEL = next(
    (
        row["upstream_model"]
        for row in read_registry()["models"]
        if "/" not in row["upstream_model"]
    ),
    None,
)
REQUESTED_MODEL = f"{PROVIDER}/{UPSTREAM_MODEL}" if UPSTREAM_MODEL else ""
CREDENTIAL_ORIGIN = TARGET.accepted_endpoints[0] if TARGET else ""

CREDENTIAL = {
    "provider": PROVIDER,
    "endpoint": CREDENTIAL_ORIGIN,
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


def _reference_with_reasoning() -> dict:
    body = _reference()
    body["reasoning_effort"] = "high"
    return body


def _rejects_reasoning() -> httpx.Response:
    return httpx.Response(
        400,
        headers={"content-type": "application/json"},
        content=json.dumps({"error": {"message": "reasoning_effort is not supported by this model"}}).encode("utf-8"),
    )

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
# 2. #6838: the caller's reasoning effort travels unchanged to the wire, and a
# provider rejection is answered with one actionable error (no silent retry).
# ---------------------------------------------------------------------------


@_NO_ROUTE
@pytest.mark.asyncio
async def test_the_callers_reasoning_effort_reaches_the_provider_body(
    live_lane, monkeypatch, captured
):
    calls, written = captured
    transport = _transport(calls, lambda _request: _completed())
    app = _app_with(transport)

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(
            CHAT_COMPLETIONS,
            json=_reference_with_reasoning(),
        )
    await drain()

    assert response.status_code == 200, response.text
    sent = json.loads(calls[0].content.decode("utf-8"))
    assert sent["reasoning_effort"] == "high"
    assert calls[0].headers["Authorization"] == f"Bearer {SENTINEL}"


@_NO_ROUTE
@pytest.mark.asyncio
async def test_a_reasoning_rejection_is_named_and_never_retried(
    live_lane, monkeypatch, captured
):
    calls, written = captured
    transport = _transport(calls, lambda _request: _rejects_reasoning())
    app = _app_with(transport)

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(
            CHAT_COMPLETIONS,
            json=_reference_with_reasoning(),
        )
    await drain()

    assert response.status_code == 400, response.text
    error = response.json()["error"]
    assert error["code"] == "custom_provider_reasoning_rejected"
    assert "추론 강도" in error["message"] and "기본" in error["message"]
    assert "reasoning_effort" not in response.text
    assert len(calls) == 1
    record = written[0]
    assert record.error_code == "custom_provider_reasoning_rejected"
    assert record.credential_source == "user"


@_NO_ROUTE
@pytest.mark.asyncio
async def test_no_reasoning_field_is_sent_when_the_caller_chose_none(
    live_lane, monkeypatch, captured
):
    calls, _written = captured
    transport = _transport(calls, lambda _request: _completed())
    app = _app_with(transport)

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(CHAT_COMPLETIONS, json=_reference())
    await drain()

    assert response.status_code == 200, response.text
    sent = json.loads(calls[0].content.decode("utf-8"))
    assert "reasoning_effort" not in sent

# ---------------------------------------------------------------------------
# 1. the key is used, and it is used nowhere else
# ---------------------------------------------------------------------------


@_NO_ROUTE
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
    assert str(sent.url) == TARGET_ORIGIN.rstrip("/") + COMPLETIONS_PATH
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
    assert record.selected_provider == PROVIDER
    assert record.selected_upstream_model == UPSTREAM_MODEL
    assert record.endpoint == CHAT_COMPLETIONS


@_NO_ROUTE
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


@_NO_ROUTE
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


@_NO_ROUTE
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


@_NO_ROUTE
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
                json=_reference({**CREDENTIAL, "key": OTHER_SENTINEL}),
            )
    await drain()

    assert response.status_code == 200
    rendered = "\n".join([record.getMessage() for record in caplog.records])
    assert SENTINEL not in rendered
    assert OTHER_SENTINEL not in rendered


# ---------------------------------------------------------------------------
# 2. the lane boundary: what is refused, and what stays exactly as it was
# ---------------------------------------------------------------------------


@_NO_ROUTE
@requires_owner_document
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


@_NO_ROUTE
@pytest.mark.asyncio
async def test_an_arbitrary_endpoint_is_never_contacted(live_lane, captured):
    """The caller's endpoint string is a claim, not an address B14 dials."""
    calls, _written = captured
    app = _app_with(_transport(calls, lambda _r: _completed()))

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(CHAT_COMPLETIONS, json=_reference({
            "provider": PROVIDER, "endpoint": "https://attacker.example.com/v1",
            "model": UPSTREAM_MODEL, "key": SENTINEL,
        }))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "user_credential_endpoint_unsupported"
    assert calls == []


@_NO_ROUTE
@pytest.mark.asyncio
async def test_a_malformed_credential_is_refused_without_quoting_it(
    live_lane, captured
):
    """A broken document is a shape problem; the value stays unprinted."""
    calls, _written = captured
    app = _app_with(_transport(calls, lambda _r: _completed()))
    broken = json.dumps({
        "provider": PROVIDER, "model": UPSTREAM_MODEL, "key": SENTINEL,
    })

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        missing_field = client.post(CHAT_COMPLETIONS, json=_reference(broken))
        not_json = client.post(CHAT_COMPLETIONS, json=_reference(SENTINEL + " not json"))
        placeholder = client.post(CHAT_COMPLETIONS, json=_reference({
            **CREDENTIAL, "key": PLACEHOLDER_SENTINEL
        }))
    await drain()

    assert missing_field.json()["error"]["code"] == "user_credential_invalid"
    assert not_json.json()["error"]["code"] == "user_credential_invalid"
    assert placeholder.json()["error"]["code"] == "placeholder_key_rejected"
    for response in (missing_field, not_json, placeholder):
        assert SENTINEL not in response.text
    assert calls == []


@_NO_ROUTE
@pytest.mark.asyncio
async def test_the_auto_stream_lane_is_gone_for_a_credential_holder(
    live_lane, captured
):
    """A credential cannot borrow a platform auto roster: the auto surface no
    longer exists."""
    calls, _written = captured
    app = _app_with(_transport(calls, lambda _r: _sse()))

    from starlette.testclient import TestClient

    with TestClient(app) as client:
        auto_preview = client.post(
            AUTO_PREVIEW, json={**_reference(), "stream": True, "model": REQUESTED_MODEL}
        )
    await drain()

    assert auto_preview.status_code == 404
    assert SENTINEL not in auto_preview.text
    assert calls == []


@_NO_ROUTE
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


@_NO_ROUTE
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


@_NO_ROUTE
@requires_owner_document
@pytest.mark.asyncio
async def test_the_platform_lane_still_labels_its_own_row_pool(
    live_lane, captured, monkeypatch
):
    """The column defaults, and the catalog lane never claims a caller credential.

    A row that says ``pool`` is the platform's own consumption; adding the label
    must not turn an ordinary catalog call into something it was not.
    """
    from app.pilot.tier_fallback import effective_tier_default

    _calls, written = captured
    pool_model = effective_tier_default()

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
        "model": pool_model,
        "messages": [{"role": "user", "content": "hi"}],
    })
    response = await gw._handle_alpha_chat("b14req_pool01", body)
    await drain()

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert "credential_source" not in payload["business14"]
    assert len(written) == 1
    assert written[0].credential_source == "pool"


@_NO_ROUTE
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


@_NO_ROUTE
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
    # The wire is the lane's own projection of the provider that answered: a
    # caller-key credential rides the OpenAI-compatible chat wire, and the same
    # projection names a platform-backed provider's wire (the ledger's rule).
    from app.pilot.gateway import _protocol_for

    assert record.protocol == _protocol_for(PROVIDER, UPSTREAM_MODEL)


@_NO_ROUTE
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


#: The caller-key provider whose address B14 reads from the platform plane
#: instead of a pinned origin (the table's own structural marker), and the alias
#: the Chat side spells for it. Both come from the credential adapter's own rule
#: tables, not from this file.
PLATFORM_TARGET = _PLATFORM[0] if _PLATFORM else None
PLATFORM_PROVIDER = PLATFORM_TARGET.platform_provider_id if PLATFORM_TARGET else None
PLATFORM_ALIAS = next(
    (
        alias for alias, target in _BY_PROVIDER.items() if target is PLATFORM_TARGET
    ),
    None,
)
_PLATFORM_SPEC = (
    psecrets.get_platform_provider(PLATFORM_PROVIDER) if PLATFORM_PROVIDER else None
)
PLATFORM_MODEL = next(
    (
        row["upstream_model"]
        for row in read_registry()["models"]
        if row["provider_id"] == PLATFORM_PROVIDER and "/" not in row["upstream_model"]
    ),
    UPSTREAM_MODEL,
)


@_NO_ROUTE
def test_the_alias_and_the_trailing_slash_resolve_to_b14s_own_address():
    """One provider, one address; the caller's spelling decides nothing."""
    if _PLATFORM_SPEC is None:
        pytest.skip("no platform-owned provider backs a caller-key route")
    aliased = credential_from_body({
        "user_credential": {
            "provider": PLATFORM_ALIAS,
            "endpoint": PLATFORM_TARGET.accepted_endpoints[0] + "/",
            "model": PLATFORM_MODEL,
            "key": GOOGLE_SENTINEL,
        }
    })
    assert isinstance(aliased, UserCredential)
    # The alias reaches the canonical provider id and that provider's own
    # registered address (the origin the platform plane declares).
    assert aliased.provider_id == PLATFORM_PROVIDER
    assert aliased.chat_completions_url == (
        _PLATFORM_SPEC.base_origin.rstrip("/") + COMPLETIONS_PATH
    )
    assert urlparse(aliased.origin).hostname in _PLATFORM_SPEC.allowed_hosts

    first = credential_from_body({"user_credential": CREDENTIAL})
    assert first.chat_completions_url == TARGET_ORIGIN.rstrip("/") + COMPLETIONS_PATH
    assert first.allowed_hosts == TARGET_HOSTS


@_NO_ROUTE
def test_the_credential_object_does_not_render_its_own_key():
    credential = credential_from_body({"user_credential": CREDENTIAL})
    assert SENTINEL not in repr(credential)
    assert SENTINEL not in str(credential)
    assert SENTINEL not in str({"body": {"user_credential": credential}})


#: The Go adapter's own wire table names the upstream identities it can carry.
#: The adapter is keyed by its own provider id (the gate it applies before any
#: credential is resolved), so the caller-key target it serves is the one whose
#: provider id that adapter names — and whose wire table the registry backs.
from app.pilot.opencode_go_wire import _WIRE as GO_WIRE  # noqa: E402
from app.pilot import opencode_go_wire as _go  # noqa: E402


def _go_provider_id() -> str | None:
    """The provider id the Go adapter itself is keyed by."""
    source = _go._authenticated_headers.__code__.co_consts
    named = [value for value in source if isinstance(value, str)
             and value in read_registry()["providers"]]
    assert len(named) <= 1, "the Go adapter names more than one registered provider"
    return named[0] if named else None


GO_PROVIDER = _go_provider_id()
#: The Go lane needs the adapter's own provider registered and a route of it the
#: adapter's wire table can serve; without both there is nothing to transport.
_GO_UPSTREAM_ROWS = [
    row["upstream_model"] for row in read_registry()["models"]
    if GO_PROVIDER and row["provider_id"] == GO_PROVIDER
    and row["upstream_model"] in GO_WIRE
]
_NO_GO_ROUTE = pytest.mark.skipif(
    GO_PROVIDER is None or not _GO_UPSTREAM_ROWS,
    reason="the effective registry document backs no OpenCode Go caller-key route",
)
GO_TARGET = _BY_PROVIDER.get(GO_PROVIDER) if GO_PROVIDER else None
#: The upstream this suite carries on the Go lane: one the adapter's own wire
#: table can serve, read from the registry rows of that provider.
GO_UPSTREAM = _GO_UPSTREAM_ROWS[0] if _GO_UPSTREAM_ROWS else None
GO_ENDPOINT = GO_TARGET.accepted_endpoints[0] if GO_TARGET else ""
GO_ORIGIN = _origin(GO_TARGET) if GO_TARGET else ""


@_NO_GO_ROUTE
@requires_owner_document
@pytest.mark.asyncio
async def test_opencode_go_user_key_uses_fixed_origin_and_user_ledger(live_lane, captured):
    from starlette.testclient import TestClient
    calls, written = captured
    app = _app_with(_transport(calls, lambda _request: _completed()))
    credential = {"provider": GO_PROVIDER,
                  "endpoint": GO_ENDPOINT,
                  "model": GO_UPSTREAM, "key": SENTINEL}
    body = _reference(credential)
    body["model"] = f"{GO_PROVIDER}/{GO_UPSTREAM}"
    with TestClient(app) as client:
        response = client.post(CHAT_COMPLETIONS, json=body)
    await drain()
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert str(calls[0].url) == GO_ORIGIN.rstrip("/") + COMPLETIONS_PATH
    assert json.loads(calls[0].content)["model"] == GO_UPSTREAM
    assert calls[0].headers["authorization"] == "Bearer " + SENTINEL
    assert len(written) == 1 and written[0].credential_source == "user"
    assert SENTINEL not in response.text
    assert SENTINEL not in json.dumps(written[0].to_row(), default=str)


@_NO_GO_ROUTE
@requires_owner_document
def test_opencode_go_user_key_rejects_noncanonical_endpoint():
    from app.pilot.errors import PilotError
    with pytest.raises(PilotError) as error:
        credential_from_body({"user_credential": {
            "provider": GO_PROVIDER, "endpoint": "https://example.invalid/v1",
            "model": GO_UPSTREAM, "key": SENTINEL,
        }})
    assert error.value.code == "user_credential_endpoint_unsupported"
