"""App HMAC ingress -> real P01 client/loopback transport; provider socket is mocked."""
from __future__ import annotations
import hashlib
import hmac
import json

import httpx
import pytest
from starlette.applications import Starlette

from app.apps_ai import (
    APPS_AI_PATH, DEFAULT_MODEL, POLICY_ENV, AppsAIEngineTransport,
    create_apps_ai_service, install_apps_ai_routes, policies_from_env, strip_thought_blocks,
)
from app.local_engine_transport import LocalEngineTransportError
from padiem_ai_engine_client import ENGINE_INTERNAL_ORIGIN

NOW = 1793534400
TEST_SECRET = "test-app-only-" + "s" * 40
TEST_CREDENTIAL = "test-p01-only-" + "c" * 40


def env(**overrides):
    result = {
        "STORYMEMORY_COM2_AI_SECRET": TEST_SECRET,
        "BOOKAI_COM2_AI_SECRET": TEST_SECRET + "book",
        "PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN": "http://127.0.0.1:8811",
        "PADIEM_CHAT_LOCAL_P01_CALLER_ID": "test-chat-host",
        "PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL": TEST_CREDENTIAL,
    }
    result.update(overrides)
    return result


def payload():
    return {
        "app_id": "b61",
        "agent": {
            "id": "storymemory-reader", "title": "Reader", "description": "Bounded reader",
            "system_instruction": "Answer using the provided text.", "task_type": "korean",
            "optimize_for": "korean", "max_tokens": 900, "required_capabilities": [],
            "model_policy": {"model": DEFAULT_MODEL, "max_retries": 0},
        },
        "messages": [{"role": "user", "content": "What happened to Saul in Acts 9?"}],
        "trace_id": "test-app-ai",
        "context_permission_required": True,
        "context_permission": {
            "envelope": {
                "request_id": "test-app-ai", "source_quality_gate_applied": False,
                "policy_hints": ["storymemory-b61-bounded"],
                "candidates": [{"id": "ctx/1", "scope_id": "storymemory",
                    "resource_ref": "bible:ACT:9:1", "provenance": ["storymemory-b61"],
                    "source_quality_selected": True, "user_asserted_permission": False}],
            },
            "boundary": {
                "allowed_scope_ids": ["storymemory"], "allowed_resource_refs": ["bible:ACT:9:1"],
                "denied_scope_ids": [], "denied_resource_refs": [], "boundary_available": True,
                "max_allowed_context": 1, "policy_version": "storymemory-b61-ceiling:v1",
            },
        },
    }


def encoded(data):
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def headers(body, *, subject="sub_app_storymemory", timestamp=NOW, secret=TEST_SECRET, path=APPS_AI_PATH):
    stamp = str(timestamp)
    canonical = "\n".join(("POST", path, stamp, subject, hashlib.sha256(body).hexdigest()))
    return {
        "content-type": "application/json", "X-Bookai-Subject": subject,
        "X-Bookai-Timestamp": stamp,
        "X-Bookai-Signature": hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest(),
    }


async def request(data=None, *, settings=None, head=None, wire=None, response=None):
    seen = []
    def p01(req):
        seen.append(req)
        return response or httpx.Response(200, json={
            "ok": True, "answer": "<thought>private</thought>Saul saw a light.",
            "context_permission": {"boundary_disposition": "permitted", "context_filtered_count": 0, "context_allowed_count": 1},
            "metadata": {"app_id": "b61", "model": DEFAULT_MODEL},
        })
    async with httpx.AsyncClient(transport=httpx.MockTransport(p01)) as upstream:
        app = Starlette()
        service = install_apps_ai_routes(app, env=settings or env(), client=upstream)
        service._clock = lambda: NOW
        body = wire if wire is not None else encoded(payload() if data is None else data)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://chat.padiem.net") as caller:
            result = await caller.post(APPS_AI_PATH, content=body, headers=headers(body) if head is None else head)
        return result, seen


@pytest.mark.asyncio
@pytest.mark.parametrize("app_name,subject,secret", [
    ("storymemory", "sub_app_storymemory", TEST_SECRET),
    ("bookai", "sub_app_bookai", TEST_SECRET + "book"),
])
async def test_signed_request_reaches_p01_and_preserves_context_projection(app_name, subject, secret):
    data = payload()
    result, seen = await request(data, head=headers(encoded(data), subject=subject, secret=secret))
    assert result.status_code == 200, result.text
    assert result.json()["answer"] == "Saul saw a light."
    assert result.json()["context_permission"] == {"boundary_disposition": "permitted", "context_filtered_count": 0, "context_allowed_count": 1}
    assert len(seen) == 1
    req = seen[0]
    assert str(req.url) == "http://127.0.0.1:8811/internal/v1/execute"
    assert req.headers["x-padiem-client-app"] == app_name
    sent = json.loads(req.content)
    assert sent["app_id"] == "b61"
    assert sent["agent"]["model_policy"] == {"model": DEFAULT_MODEL, "max_retries": 0}
    assert sent["context_permission"] == data["context_permission"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["signature", "body", "expired", "future", "subject", "path", "cross_app"])
async def test_invalid_or_rebound_signature_never_calls_p01(mode):
    body = encoded(payload())
    head = headers(body)
    expected = 401
    if mode == "signature":
        head["X-Bookai-Signature"] = "0" * 64
    elif mode == "body":
        body += b" "
    elif mode == "expired":
        head = headers(body, timestamp=NOW - 301)
    elif mode == "future":
        head = headers(body, timestamp=NOW + 301)
    elif mode == "subject":
        head = headers(body, subject="sub_unknown")
        expected = 403
    elif mode == "path":
        head = headers(body, path="/api/bookai/records")
    elif mode == "cross_app":
        head = headers(body, subject="sub_app_bookai")
    result, seen = await request(wire=body, head=head)
    assert result.status_code == expected
    assert seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change,status,code", [
    ("model", 403, "model_not_allowed"),
    ("auto", 403, "model_not_allowed"),
    ("retry", 422, "model_retries_not_allowed"),
    ("extra_policy", 422, "invalid_model_policy"),
    ("tokens", 422, "app_token_limit_exceeded"),
    ("application", 403, "app_not_authorized"),
    ("context", 422, "context_permission_required"),
])
async def test_model_policy_and_app_limits_are_server_owned(change, status, code):
    data = payload()
    if change == "model": data["agent"]["model_policy"]["model"] = "google/not-authorized"
    elif change == "auto": data["agent"]["model_policy"]["model"] = "b14/auto"
    elif change == "retry": data["agent"]["model_policy"]["max_retries"] = 1
    elif change == "extra_policy": data["agent"]["model_policy"]["temperature"] = 0.5
    elif change == "tokens": data["agent"]["max_tokens"] = 901
    elif change == "application": data["app_id"] = "padiem-chat"
    elif change == "context": data["context_permission_required"] = False
    result, seen = await request(data)
    assert result.status_code == status
    assert result.json()["error"]["code"] == code
    assert seen == []


@pytest.mark.asyncio
async def test_configurable_policy_changes_model_and_limits_per_app():
    configured = env(**{POLICY_ENV: json.dumps({"storymemory": {
        "allowed_models": ["google/explicit-test"], "max_tokens": 300, "max_body_bytes": 4096,
    }})})
    data = payload()
    data["agent"]["model_policy"]["model"] = "google/explicit-test"
    data["agent"]["max_tokens"] = 300
    result, seen = await request(data, settings=configured)
    assert result.status_code == 200
    assert len(seen) == 1
    too_large = dict(data, additional_system_context="x" * 5000)
    result, seen = await request(too_large, settings=configured)
    assert result.status_code == 413
    assert seen == []


@pytest.mark.asyncio
async def test_missing_configuration_and_p01_refusal_are_not_synthetic_answers():
    result, seen = await request(settings=env(STORYMEMORY_COM2_AI_SECRET=""))
    assert result.status_code == 503 and not seen
    result, seen = await request(settings=env(PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL=""))
    assert result.status_code == 503 and not seen
    result, seen = await request(response=httpx.Response(403, json={
        "ok": False, "error": {"code": "service_app_not_authorized", "message": "not allowed"},
    }))
    assert result.status_code == 403
    assert result.json()["error"]["code"] == "service_app_not_authorized"
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_transport_stays_on_existing_loopback_target_and_no_redirects():
    transport = AppsAIEngineTransport("http://127.0.0.1:8811", app_name="bookai")
    with pytest.raises(LocalEngineTransportError):
        await transport.request(method="POST", url="https://attacker.invalid/internal/v1/execute", headers={}, body=b"{}")
    with pytest.raises(LocalEngineTransportError):
        await transport.request(method="POST", url=ENGINE_INTERNAL_ORIGIN + "/internal/v1/arbitrary", headers={}, body=b"{}")


@pytest.mark.parametrize("text,expected", [
    ("<thought>internal</thought>answer", "answer"),
    ("before<thought>unfinished", "before"),
    ("<thought>a<thought>b</thought>c</thought>answer", "answer"),
    ("<THOUGHT mode='hidden'>hidden</THOUGHT>visible", "visible"),
])
def test_thought_removal(text, expected):
    assert strip_thought_blocks(text) == expected


def test_invalid_policy_does_not_report_its_contents():
    with pytest.raises(ValueError, match="^apps_ai_policy_invalid$"):
        policies_from_env({POLICY_ENV: '{"storymemory":{"allowed_models":["b14/auto"]}}'})


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [
    httpx.Response(200, content=b"not-json"),
    httpx.Response(200, json={"ok": True, "answer": None}),
])
async def test_invalid_p01_response_is_502_so_storymemory_can_fallback(malformed):
    result, seen = await request(response=malformed)
    assert result.status_code == 502
    assert result.json()["error"]["code"] == "invalid_engine_response"
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_sdk_context_fields_are_execute_only_and_typed():
    from padiem_ai_engine_client import PadiemAiEngineClient, PadiemAiEngineClientError
    transport = AppsAIEngineTransport("http://127.0.0.1:8811", app_name="bookai")
    client = PadiemAiEngineClient(transport=transport, app_id="b61", caller_id="test-chat", credential=TEST_CREDENTIAL)
    data = {k: v for k, v in payload().items() if k != "app_id"}
    with pytest.raises(PadiemAiEngineClientError, match="unsupported fields"):
        await client.orchestrate(data)
    for key, value in [("context_permission", []), ("context_permission_required", "true")]:
        invalid = dict(data, **{key: value})
        with pytest.raises(PadiemAiEngineClientError) as caught:
            await client.execute(invalid)
        assert caught.value.code == "invalid_engine_request"


@pytest.mark.asyncio
async def test_app_transport_uses_55_seconds_without_changing_host_default(monkeypatch):
    from app.local_engine_transport import DEFAULT_TIMEOUT_SECONDS
    seen = []
    original_client = httpx.AsyncClient
    def respond(request):
        seen.append(request.extensions["timeout"])
        return httpx.Response(200, json={"ok": True, "answer": "ready"})
    def client_factory(**kwargs):
        return original_client(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr("app.local_engine_transport.httpx.AsyncClient", client_factory)
    transport = AppsAIEngineTransport("http://127.0.0.1:8811", app_name="bookai")
    result = await transport.request(
        method="POST", url=ENGINE_INTERNAL_ORIGIN + "/internal/v1/execute", headers={}, body=b"{}",
    )
    assert result.status == 200
    assert seen == [{"connect": 55.0, "read": 55.0, "write": 55.0, "pool": 55.0}]
    assert DEFAULT_TIMEOUT_SECONDS == 30.0
