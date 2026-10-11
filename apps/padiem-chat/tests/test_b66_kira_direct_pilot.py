"""B66-only exact Kira direct path. No Cloudflare keys or real vendor traffic."""
from __future__ import annotations

from dataclasses import replace
import json

import httpx
import pytest

from app.b14_client import ChatRuntimeError
from app.b66_kira_direct_pilot import B66KiraPilotExecutor, KIRA_B66_MODEL_ID
from app.b66_registered_model_boundary import (
    B14AuthorizedModelRoute,
    B66ModelRouteError,
    B66QuoteTaskRequirements,
    B66RegisteredModelCompletion,
)


class Secret:
    def __init__(self, value="test-secret-never-real"):
        self.value = value
        self.reads = 0

    async def get(self):
        self.reads += 1
        return self.value


class Original:
    supports_native_parameters = True

    def __init__(self):
        self.calls = []

    def ensure_runtime_available(self):
        return None

    async def execute_quote_text(self, **kw):
        self.calls.append(kw)
        return {"answer": "from B14", "route": {"mode": "manual", "model": kw["route"].model_id}}


def route(model=KIRA_B66_MODEL_ID):
    return B14AuthorizedModelRoute(
        model_id=model, route_id=model,
        owner_policy_id="owner-approved-b66-policy-v1",
        registered=True, enabled=True, authorized=True,
        credential_ready=True, route_count=1, capabilities=frozenset({"chat"}),
    )


class Resolver:
    def __init__(self, selected):
        self.selected = selected
        self.calls = 0

    async def resolve_quote_model(self, requirements):
        self.calls += 1
        assert requirements.selected_model_id == self.selected.model_id
        return self.selected


def args(model=KIRA_B66_MODEL_ID):
    return {
        "route": route(model),
        "messages": [{"role": "user", "content": "배관 100미터"}],
        "additional_system_context": "Return quote JSON.",
        "requirements": replace(B66QuoteTaskRequirements(), selected_model_id=model),
        "model_parameters": None,
    }


def setup(handler=None, *, secret=None):
    original = Original()
    secret = secret if secret is not None else Secret()
    calls = []

    def record(request):
        calls.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://kiraai.vn/api/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-secret-never-real"
        assert request.headers["content-type"] == "application/json"
        request_body = json.loads(request.content)
        assert request_body["model"] == "qwen3.8-flash-free"
        assert request_body["stream"] is False
        assert request_body["messages"] == [
            {"role": "system", "content": "Return quote JSON."},
            {"role": "user", "content": "배관 100미터"},
        ]
        return handler(request) if handler else httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": '{"items":[{"name":"배관","qty":100}]}'}}]
        })
    executor = B66KiraPilotExecutor(
        original_executor=original,
        credential_binding=secret,
        transport=httpx.MockTransport(record),
    )
    return executor, original, secret, calls


@pytest.mark.asyncio
async def test_exact_kira_direct_once_and_never_calls_b14():
    executor, original, secret, calls = setup()
    resolver = Resolver(route())
    result = await B66RegisteredModelCompletion(resolver=resolver, executor=executor).complete(
        [{"role": "user", "content": "배관 100미터"}],
        additional_system_context="Return quote JSON.",
        model_id=KIRA_B66_MODEL_ID,
    )
    assert result["answer"] == '{"items":[{"name":"배관","qty":100}]}'
    assert resolver.calls == secret.reads == len(calls) == 1
    assert original.calls == []
    assert executor.supports_native_parameters is True


@pytest.mark.asyncio
async def test_other_models_stay_with_original_b14_and_never_read_secret():
    executor, original, secret, calls = setup()
    result = await executor.execute_quote_text(**args("google/gemma-4-26b-a4b-it"))
    assert result["answer"] == "from B14"
    assert len(original.calls) == 1 and secret.reads == len(calls) == 0


@pytest.mark.asyncio
async def test_invalid_owner_route_fails_before_secret_or_vendor():
    executor, original, secret, calls = setup()
    kw = args()
    kw["route"] = replace(kw["route"], authorized=False)
    with pytest.raises(B66ModelRouteError):
        await executor.execute_quote_text(**kw)
    assert not original.calls and not secret.reads and not calls


@pytest.mark.asyncio
async def test_absent_credential_never_calls_vendor():
    executor, original, secret, calls = setup(secret=Secret(""))
    with pytest.raises(ChatRuntimeError) as error:
        await executor.execute_quote_text(**args())
    assert error.value.code == "upstream_binding_unavailable"
    assert secret.reads == 1 and len(calls) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("status","code"), [
    (401, "provider_auth_error"),
    (403, "provider_auth_error"),
    (429, "upstream_busy"),
    (502, "provider_server_error"),
    (400, "provider_route_error"),
])
async def test_vendor_errors_are_bounded_without_fallback(status, code):
    executor, original, secret, calls = setup(
        handler=lambda _request: httpx.Response(status, text="SENSITIVE_VENDOR_ERROR")
    )
    with pytest.raises(ChatRuntimeError) as err:
        await executor.execute_quote_text(**args())
    assert err.value.code == code
    assert "SENSITIVE_VENDOR_ERROR" not in str(err.value)
    assert len(calls) == 1 and not original.calls


@pytest.mark.asyncio
async def test_bad_vendor_response_is_rejected():
    executor, original, secret, calls = setup(
        handler=lambda _request: httpx.Response(200, json={"choices": []})
    )
    with pytest.raises(ChatRuntimeError) as err:
        await executor.execute_quote_text(**args())
    assert err.value.code == "malformed_upstream"
    assert len(calls) == 1 and not original.calls
