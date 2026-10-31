"""#5121 PADIEM Custom multi-provider and custom-endpoint contracts.

Every official wire contract is exercised over ``httpx.MockTransport``:

* OpenAI / OpenRouter: ``/chat/completions`` (JSON and SSE ``[DONE]``),
* Anthropic: ``/v1/messages`` (``x-api-key``, ``anthropic-version``, SSE
  ``message_stop``),
* Google Gemini: ``models/{model}:generateContent`` / ``:streamGenerateContent``
  (``x-goog-api-key``, SSE terminated by EOF).

The suite also proves owner/provider/endpoint key binding, the additive
endpoint migration, SSRF/DNS/redirect refusal, and Chat/Claw/B66 product
integration with a non-OpenCode provider while B14 stays untouched. No live
paid provider call is made anywhere in this module.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from app.byok_client import CustomProviderClient, CustomProviderError
from app.byok_credentials import (
    CUSTOM_PROVIDERS,
    CustomCredentialDecryptionError,
    CustomEndpointStorageUnavailable,
    D1CustomProviderCredentialStore,
    resolve_custom_selection,
)
from app.byok_endpoint import (
    CustomEndpointError,
    CustomEndpointVerificationError,
    CustomEndpointUnverifiedError,
    normalize_custom_endpoint,
    verify_public_endpoint,
)
from app.history import D1HistoryStore
from app.main import create_app
from test_5002_byok_product_e2e import (
    CUSTOM_KEY,
    CUSTOM_KEY_SECRET,
    DEFAULT_ANSWER,
    ORIGIN,
    OTHER,
    OTHER_KEY,
    OWNER,
    SESSION_SECRET,
    B14Probe,
    FakeAuthenticatedCipher,
    ProviderRecorder,
    SQLiteD1,
    request,
    settings,
    sse_events,
)

API_KEY = "sk-multi-provider-5121-AAAA1111"
OTHER_API_KEY = "sk-multi-provider-5121-BBBB2222"
PUBLIC_IP = "93.184.216.34"
OPENAI_MODEL = "gpt-4o-mini"
OPENROUTER_MODEL = "openai/gpt-4o-mini"
ANTHROPIC_MODEL = "claude-3-5-sonnet-latest"
GEMINI_MODEL = "gemini-2.0-flash"
QUOTE_MARKER = "견적 입력값 추출기"


# ---------------------------------------------------------------------------
# Harnesses
# ---------------------------------------------------------------------------


class EndpointD1(SQLiteD1):
    """SQLite D1 with the additive 064 endpoint column."""

    def __init__(self):
        super().__init__()
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        self.conn.executescript(
            (migrations / "064_chat_custom_provider_endpoints.sql").read_text(
                encoding="utf-8"
            )
        )
        self.conn.commit()

    def credential_row(self, user_id: str = OWNER, provider_id: str = "openai"):
        row = self.conn.execute(
            "SELECT key_last4, sealed_credential, endpoint "
            "FROM chat_custom_provider_credentials WHERE user_id=? AND provider_id=?",
            (user_id, provider_id),
        ).fetchone()
        return dict(row) if row else None


class StaticResolver:
    """Deterministic DNS evidence for tests that exercise custom endpoints."""

    def __init__(self, addresses=(PUBLIC_IP,), error: Exception | None = None):
        self.addresses = tuple(addresses)
        self.error = error
        self.hosts: list[str] = []

    async def resolve(self, hostname: str) -> tuple[str, ...]:
        self.hosts.append(hostname)
        if self.error is not None:
            raise self.error
        return self.addresses


def store_for(d1, *, cipher=None) -> D1CustomProviderCredentialStore:
    return D1CustomProviderCredentialStore(
        d1,
        key_secret=CUSTOM_KEY_SECRET,
        session_secret=SESSION_SECRET,
        cipher=cipher or FakeAuthenticatedCipher(),
    )


def client_for(recorder, *, resolver=None) -> CustomProviderClient:
    return CustomProviderClient(
        transport=recorder.transport,
        endpoint_resolver=resolver or StaticResolver(),
    )


def build_chat_app(*, d1=None, recorder=None, resolver=None):
    d1 = EndpointD1() if d1 is None else d1
    history = D1HistoryStore(d1)
    credential_store = store_for(d1)
    recorder = recorder or ProviderRecorder()
    app = create_app(
        settings(),
        history_store=history,
        custom_credential_store=credential_store,
        custom_provider_client=client_for(recorder, resolver=resolver),
    )
    b14 = B14Probe()
    app.state.b14_client = b14
    app.state.b14_catalog_source = None
    app.state.central_model_policy_store = None
    app.state.usage_gate_enforced = False
    return app, d1, history, credential_store, recorder, b14


async def save_provider_key(app, provider, api_key=API_KEY, *, uid=OWNER, endpoint=None):
    body = {"provider": provider, "api_key": api_key}
    if endpoint is not None:
        body["endpoint"] = endpoint
    response = await request(
        app, "PUT", "/api/chat/custom/credential", uid=uid, json_body=body
    )
    assert response.status_code == 200, response.text
    return response


def custom_selection(provider: str, model: str) -> dict[str, str]:
    return {"provider": provider, "model": model}


def chat_body(provider: str, model: str, *, content="안녕하세요") -> dict:
    return {
        "messages": [{"role": "user", "content": content}],
        "custom": custom_selection(provider, model),
    }


# ---------------------------------------------------------------------------
# Wire fixtures
# ---------------------------------------------------------------------------


def sse(*blocks: str) -> httpx.Response:
    return httpx.Response(
        200,
        content="".join(blocks).encode("utf-8"),
        headers={"content-type": "text/event-stream"},
    )


def data(payload) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def named(event: str, payload) -> str:
    return "event: " + event + "\n" + data(payload)


def openai_json_handler(model: str = OPENAI_MODEL):
    def handler(_request):
        return httpx.Response(
            200,
            json={
                "model": model,
                "choices": [{"message": {"content": DEFAULT_ANSWER}}],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 2,
                    "total_tokens": 7,
                    "cost": 0.012,
                },
            },
        )

    return handler


def openai_stream_handler(
    *, model: str = OPENAI_MODEL, finish: bool = True, done: bool = True
):
    def handler(_request):
        final = {
            "model": model,
            "choices": [{"delta": {}, "finish_reason": "stop" if finish else None}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }
        blocks = [
            data({"model": model, "choices": [{"delta": {"content": "custom "}}]}),
            data({"model": model, "choices": [{"delta": {"content": "답변"}}]}),
            data(final),
        ]
        if done:
            blocks.append("data: [DONE]\n\n")
        return sse(*blocks)

    return handler


def anthropic_handler(_request):
    body = json.loads(_request.content)
    text = (
        json.dumps(QUOTE_CANDIDATE, ensure_ascii=False)
        if QUOTE_MARKER in body.get("system", "")
        else DEFAULT_ANSWER
    )
    if body.get("stream"):
        return sse(
            named(
                "message_start",
                {"type": "message_start", "message": {"usage": {"input_tokens": 11}}},
            ),
            named(
                "content_block_start",
                {"type": "content_block_start", "content_block": {"type": "text"}},
            ),
            named(
                "content_block_delta",
                {"type": "content_block_delta",
                 "delta": {"type": "text_delta", "text": text}},
            ),
            named(
                "message_delta",
                {"type": "message_delta", "delta": {}, "usage": {"output_tokens": 4}},
            ),
            named("message_stop", {"type": "message_stop"}),
        )
    return httpx.Response(
        200,
        json={
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 11, "output_tokens": 4},
        },
    )


def anthropic_stream_handler(*, stop: bool = True):
    def handler(_request):
        blocks = [
            named(
                "message_start",
                {"type": "message_start", "message": {"usage": {"input_tokens": 11}}},
            ),
            named(
                "content_block_delta",
                {"type": "content_block_delta",
                 "delta": {"type": "text_delta", "text": DEFAULT_ANSWER}},
            ),
            named(
                "message_delta",
                {"type": "message_delta", "delta": {}, "usage": {"output_tokens": 4}},
            ),
        ]
        if stop:
            blocks.append(named("message_stop", {"type": "message_stop"}))
        return sse(*blocks)

    return handler


def gemini_json_handler(_request):
    return httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"parts": [{"text": DEFAULT_ANSWER}]}, "finishReason": "STOP"}
            ],
            "usageMetadata": {
                "promptTokenCount": 3,
                "candidatesTokenCount": 2,
                "totalTokenCount": 5,
            },
        },
    )


def gemini_stream_handler(_request):
    return sse(
        data({"candidates": [{"content": {"parts": [{"text": "custom "}]}}]}),
        data(
            {
                "candidates": [
                    {"content": {"parts": [{"text": "답변"}]}, "finishReason": "STOP"}
                ],
                "usageMetadata": {
                    "promptTokenCount": 3,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 5,
                },
            }
        ),
    )


QUOTE_CANDIDATE = {"recipient": {"company": "ABC건설"}, "items": []}


# ---------------------------------------------------------------------------
# Registry and capability surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_exposes_the_official_providers_and_capabilities():
    app, *_ = build_chat_app()
    response = await request(app, "GET", "/api/chat/custom/credential", uid=OWNER)
    assert response.status_code == 200, response.text
    providers = {row["provider"]: row for row in response.json()["providers"]}
    assert set(providers) == {"opencode-go", "openai", "openrouter", "anthropic", "gemini",
        "deepseek", "groq", "xai", "perplexity", "huggingface"}
    assert providers["opencode-go"]["manual_model"] is False
    assert providers["opencode-go"]["supports_model_listing"] is False
    assert providers["opencode-go"]["supports_connection_test"] is False
    assert providers["opencode-go"]["models"] == ["opencode-go/beam-free"]
    for provider in ("openai", "openrouter", "anthropic", "gemini"):
        assert providers[provider]["manual_model"] is True
        assert providers[provider]["supports_model_listing"] is True
        assert providers[provider]["supports_connection_test"] is True
        assert providers[provider]["supports_custom_endpoint"] is True
        assert providers[provider]["default_endpoint"].startswith("https://")


def test_registry_keeps_the_opencode_go_model_fixed():
    spec = CUSTOM_PROVIDERS["opencode-go"]
    assert spec.stream_by_default is False
    with pytest.raises(ValueError):
        resolve_custom_selection("opencode-go", "opencode-go/other-model")
    resolved = resolve_custom_selection("opencode-go", "opencode-go/beam-free")
    assert resolved.upstream_model == "beam-free"


# ---------------------------------------------------------------------------
# Non-streaming wire contracts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_chat_completions_contract():
    recorder = ProviderRecorder(openai_json_handler())
    client = client_for(recorder)

    result = await client.complete(
        selection=resolve_custom_selection("openai", OPENAI_MODEL),
        api_key=API_KEY,
        endpoint=CUSTOM_PROVIDERS["openai"].base_origin,
        messages=[{"role": "user", "content": "안녕하세요"}],
        system_context="reference context",
        stream=False,
    )

    assert result["answer"] == DEFAULT_ANSWER
    assert result["provider"] == "openai"
    assert result["model"] == OPENAI_MODEL
    assert result["usage"] == {
        "input_tokens": 5,
        "output_tokens": 2,
        "total_tokens": 7,
        "cost_usd": 0.012,
    }
    wire = recorder.requests[0]
    assert str(wire.url) == "https://api.openai.com/v1/chat/completions"
    assert wire.headers["authorization"] == "Bearer " + API_KEY
    assert "x-api-key" not in wire.headers
    sent = json.loads(wire.content)
    assert sent["model"] == OPENAI_MODEL
    assert sent["messages"][0]["role"] == "system"
    assert "reference context" in sent["messages"][0]["content"]
    assert sent["messages"][1] == {"role": "user", "content": "안녕하세요"}
    assert "stream" not in sent


@pytest.mark.asyncio
async def test_openrouter_reuses_the_openai_wire_with_attribution_header():
    recorder = ProviderRecorder(openai_json_handler())
    client = client_for(recorder)

    result = await client.complete(
        selection=resolve_custom_selection("openrouter", OPENROUTER_MODEL),
        api_key=API_KEY,
        endpoint=CUSTOM_PROVIDERS["openrouter"].base_origin,
        messages=[{"role": "user", "content": "hi"}],
        stream=False,
    )

    assert result["answer"] == DEFAULT_ANSWER
    wire = recorder.requests[0]
    assert str(wire.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert wire.headers["authorization"] == "Bearer " + API_KEY
    assert wire.headers["x-title"] == "PADIEM Chat"
    assert json.loads(wire.content)["model"] == OPENROUTER_MODEL


@pytest.mark.asyncio
async def test_anthropic_messages_contract_and_usage():
    recorder = ProviderRecorder(anthropic_handler)
    client = client_for(recorder)

    result = await client.complete(
        selection=resolve_custom_selection("anthropic", ANTHROPIC_MODEL),
        api_key=API_KEY,
        endpoint=CUSTOM_PROVIDERS["anthropic"].base_origin,
        messages=[
            {"role": "user", "content": "첫 질문"},
            {"role": "assistant", "content": "첫 답"},
            {"role": "user", "content": "둘째 질문"},
        ],
        system_context="reference context",
        stream=False,
    )

    assert result["answer"] == DEFAULT_ANSWER
    assert result["usage"] == {
        "input_tokens": 11,
        "output_tokens": 4,
        "total_tokens": 15,
    }
    wire = recorder.requests[0]
    assert str(wire.url) == "https://api.anthropic.com/v1/messages"
    assert wire.headers["x-api-key"] == API_KEY
    assert wire.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in wire.headers
    sent = json.loads(wire.content)
    assert sent["model"] == ANTHROPIC_MODEL
    assert sent["max_tokens"] == 4096
    assert sent["stream"] is False
    assert QUOTE_MARKER not in sent["system"]
    assert "reference context" in sent["system"]
    assert sent["messages"] == [
        {"role": "user", "content": "첫 질문"},
        {"role": "assistant", "content": "첫 답"},
        {"role": "user", "content": "둘째 질문"},
    ]


@pytest.mark.asyncio
async def test_gemini_generate_content_contract_and_usage():
    recorder = ProviderRecorder(gemini_json_handler)
    client = client_for(recorder)

    result = await client.complete(
        selection=resolve_custom_selection("gemini", GEMINI_MODEL),
        api_key=API_KEY,
        endpoint=CUSTOM_PROVIDERS["gemini"].base_origin,
        messages=[
            {"role": "user", "content": "첫 질문"},
            {"role": "assistant", "content": "첫 답"},
        ],
        stream=False,
    )

    assert result["answer"] == DEFAULT_ANSWER
    assert result["usage"] == {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
    wire = recorder.requests[0]
    assert str(wire.url) == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.0-flash:generateContent"
    )
    assert wire.headers["x-goog-api-key"] == API_KEY
    assert "authorization" not in wire.headers
    sent = json.loads(wire.content)
    assert sent["contents"] == [
        {"role": "user", "parts": [{"text": "첫 질문"}]},
        {"role": "model", "parts": [{"text": "첫 답"}]},
    ]
    assert sent["systemInstruction"]["parts"][0]["text"]


# ---------------------------------------------------------------------------
# Streaming wire contracts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_stream_contract_completes_on_done_with_usage():
    recorder = ProviderRecorder(openai_stream_handler())
    client = client_for(recorder)

    result = await client.complete(
        selection=resolve_custom_selection("openai", OPENAI_MODEL),
        api_key=API_KEY,
        endpoint=CUSTOM_PROVIDERS["openai"].base_origin,
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
    )

    assert result["answer"] == "custom 답변"
    assert result["usage"] == {
        "input_tokens": 5,
        "output_tokens": 2,
        "total_tokens": 7,
    }
    sent = json.loads(recorder.requests[0].content)
    assert sent["stream"] is True


@pytest.mark.asyncio
async def test_openai_stream_accepts_finish_reason_without_done():
    recorder = ProviderRecorder(openai_stream_handler(done=False))
    client = client_for(recorder)
    result = await client.complete(
        selection=resolve_custom_selection("openai", OPENAI_MODEL),
        api_key=API_KEY,
        endpoint=CUSTOM_PROVIDERS["openai"].base_origin,
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
    )
    assert result["answer"] == "custom 답변"


@pytest.mark.asyncio
async def test_openai_stream_without_terminator_fails_closed():
    recorder = ProviderRecorder(openai_stream_handler(finish=False, done=False))
    client = client_for(recorder)
    with pytest.raises(CustomProviderError) as error:
        await client.complete(
            selection=resolve_custom_selection("openai", OPENAI_MODEL),
            api_key=API_KEY,
            endpoint=CUSTOM_PROVIDERS["openai"].base_origin,
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )
    assert error.value.code == "malformed_custom_provider_response"


@pytest.mark.asyncio
async def test_anthropic_stream_contract_requires_message_stop():
    recorder = ProviderRecorder(anthropic_stream_handler())
    client = client_for(recorder)

    result = await client.complete(
        selection=resolve_custom_selection("anthropic", ANTHROPIC_MODEL),
        api_key=API_KEY,
        endpoint=CUSTOM_PROVIDERS["anthropic"].base_origin,
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
    )
    assert result["answer"] == DEFAULT_ANSWER
    assert result["usage"] == {
        "input_tokens": 11,
        "output_tokens": 4,
        "total_tokens": 15,
    }
    assert json.loads(recorder.requests[0].content)["stream"] is True

    stopped = ProviderRecorder(anthropic_stream_handler(stop=False))
    with pytest.raises(CustomProviderError) as error:
        await client_for(stopped).complete(
            selection=resolve_custom_selection("anthropic", ANTHROPIC_MODEL),
            api_key=API_KEY,
            endpoint=CUSTOM_PROVIDERS["anthropic"].base_origin,
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )
    assert error.value.code == "malformed_custom_provider_response"


@pytest.mark.asyncio
async def test_gemini_stream_ends_at_eof_with_usage():
    recorder = ProviderRecorder(gemini_stream_handler)
    client = client_for(recorder)

    result = await client.complete(
        selection=resolve_custom_selection("gemini", GEMINI_MODEL),
        api_key=API_KEY,
        endpoint=CUSTOM_PROVIDERS["gemini"].base_origin,
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
    )

    assert result["answer"] == "custom 답변"
    assert result["usage"] == {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
    assert str(recorder.requests[0].url).endswith(
        "/models/gemini-2.0-flash:streamGenerateContent?alt=sse"
    )


# ---------------------------------------------------------------------------
# Model listing and real connection test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "payload", "expected"),
    [
        (
            "openai",
            {"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]},
            ["gpt-4o", "gpt-4o-mini"],
        ),
        (
            "openrouter",
            {"data": [{"id": "openai/gpt-4o-mini"}, {"id": "anthropic/claude-3.5"}]},
            ["anthropic/claude-3.5", "openai/gpt-4o-mini"],
        ),
        (
            "anthropic",
            {"data": [{"id": "claude-3-5-sonnet-latest"}, {"id": "claude-3-haiku"}]},
            ["claude-3-5-sonnet-latest", "claude-3-haiku"],
        ),
        (
            "gemini",
            {
                "models": [
                    {
                        "name": "models/gemini-2.0-flash",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "name": "models/text-embedding-004",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                ]
            },
            ["gemini-2.0-flash"],
        ),
    ],
)
async def test_provider_model_listing_is_real(provider, payload, expected):
    recorder = ProviderRecorder(lambda _request: httpx.Response(200, json=payload))
    listed = await client_for(recorder).list_models(
        provider_id=provider,
        api_key=API_KEY,
        endpoint=CUSTOM_PROVIDERS[provider].base_origin,
    )
    assert listed == {"models": expected, "source": "provider"}
    wire = recorder.requests[0]
    assert wire.method == "GET"
    assert str(wire.url).split("?")[0].endswith("/models")


@pytest.mark.asyncio
async def test_connection_test_uses_the_model_list_and_never_completes():
    recorder = ProviderRecorder(
        lambda _request: httpx.Response(200, json={"data": [{"id": "gpt-4o-mini"}]})
    )
    checked = await client_for(recorder).test_connection(
        provider_id="openai",
        api_key=API_KEY,
        endpoint=CUSTOM_PROVIDERS["openai"].base_origin,
    )
    assert checked == {"models_count": 1, "source": "provider"}
    assert len(recorder.requests) == 1
    assert recorder.requests[0].method == "GET"


@pytest.mark.asyncio
async def test_model_and_connection_routes_use_the_owner_key():
    recorder = ProviderRecorder(
        lambda _request: httpx.Response(200, json={"data": [{"id": "gpt-4o-mini"}]})
    )
    app, *_ = build_chat_app(recorder=recorder)
    await save_provider_key(app, "openai")

    models = await request(
        app, "GET", "/api/chat/custom/models?provider=openai", uid=OWNER
    )
    assert models.status_code == 200, models.text
    assert models.json()["models"] == ["gpt-4o-mini"]
    assert models.json()["source"] == "provider"

    tested = await request(
        app,
        "GET",
        "/api/chat/custom/credential/test?provider=openai",
        uid=OWNER,
    )
    assert tested.status_code == 200, tested.text
    assert tested.json() == {
        "ok": True,
        "provider": "openai",
        "models_count": 1,
        "source": "provider",
    }
    assert all(request.headers["authorization"] == "Bearer " + API_KEY
               for request in recorder.requests)
    assert {request.method for request in recorder.requests} == {"GET"}


@pytest.mark.asyncio
async def test_registry_model_list_works_without_a_key_and_test_is_unsupported():
    app, *_ = build_chat_app()
    listed = await request(
        app, "GET", "/api/chat/custom/models?provider=opencode-go", uid=OWNER
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["models"] == ["opencode-go/beam-free"]
    assert listed.json()["source"] == "registry"

    tested = await request(
        app,
        "GET",
        "/api/chat/custom/credential/test?provider=opencode-go",
        uid=OWNER,
    )
    assert tested.status_code == 422
    assert tested.json()["error"]["code"] == "custom_connection_test_unsupported"

    missing = await request(
        app, "GET", "/api/chat/custom/models?provider=openai", uid=OWNER
    )
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "custom_credential_required"


# ---------------------------------------------------------------------------
# Endpoint storage and key binding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_endpoint_is_stored_reported_and_decrypted():
    d1 = EndpointD1()
    credential_store = store_for(d1)
    endpoint = "https://gateway.example.test/v1"

    saved = await credential_store.save(
        user_id=OWNER, provider_id="openai", api_key=API_KEY, endpoint=endpoint
    )
    assert saved["endpoint"] == endpoint
    assert saved["endpoint_is_default"] is False
    assert d1.credential_row()["endpoint"] == endpoint
    assert API_KEY not in d1.credential_row()["sealed_credential"]

    assert await credential_store.credential(OWNER, "openai") == (API_KEY, endpoint)
    status = await credential_store.status(OWNER)
    assert status == [
        {
            "provider": "openai",
            "key_last4": API_KEY[-4:],
            "endpoint": endpoint,
            "endpoint_is_default": False,
            "created_at": status[0]["created_at"],
            "updated_at": status[0]["updated_at"],
        }
    ]


@pytest.mark.asyncio
async def test_tampered_endpoint_cannot_redirect_a_sealed_key():
    d1 = EndpointD1()
    credential_store = store_for(d1)
    await credential_store.save(
        user_id=OWNER,
        provider_id="openai",
        api_key=API_KEY,
        endpoint="https://gateway-one.example.test/v1",
    )
    d1.conn.execute(
        "UPDATE chat_custom_provider_credentials SET endpoint=? "
        "WHERE user_id=? AND provider_id=?",
        ("https://gateway-two.example.test/v1", OWNER, "openai"),
    )
    d1.conn.commit()

    with pytest.raises(CustomCredentialDecryptionError) as error:
        await credential_store.credential(OWNER, "openai")
    assert API_KEY not in str(error.value)


@pytest.mark.asyncio
async def test_default_sealed_row_cannot_be_redirected_to_a_custom_endpoint():
    """Legacy default-endpoint AAD must not unlock a tampered custom host."""
    d1 = EndpointD1()
    credential_store = store_for(d1)
    await credential_store.save(
        user_id=OWNER, provider_id="openai", api_key=API_KEY
    )
    d1.conn.execute(
        "UPDATE chat_custom_provider_credentials SET endpoint=? "
        "WHERE user_id=? AND provider_id=?",
        ("https://evil.example.test/v1", OWNER, "openai"),
    )
    d1.conn.commit()

    with pytest.raises(CustomCredentialDecryptionError) as error:
        await credential_store.credential(OWNER, "openai")
    assert API_KEY not in str(error.value)
    assert d1.credential_row()["endpoint"] == "https://evil.example.test/v1"

    # The same envelope is readable at its original default binding, so only
    # the tampered custom endpoint (not a broken seal) caused the refusal.
    d1.conn.execute(
        "UPDATE chat_custom_provider_credentials SET endpoint=NULL "
        "WHERE user_id=? AND provider_id=?",
        (OWNER, "openai"),
    )
    d1.conn.commit()
    assert await credential_store.api_key(OWNER, "openai") == API_KEY


@pytest.mark.asyncio
async def test_default_endpoint_remains_usable_without_migration_064():
    d1 = SQLiteD1()
    credential_store = store_for(d1)

    saved = await credential_store.save(
        user_id=OWNER, provider_id="openai", api_key=API_KEY
    )
    assert saved["endpoint"] == CUSTOM_PROVIDERS["openai"].base_origin
    assert saved["endpoint_is_default"] is True
    assert await credential_store.api_key(OWNER, "openai") == API_KEY

    with pytest.raises(CustomEndpointStorageUnavailable):
        await credential_store.save(
            user_id=OWNER,
            provider_id="openai",
            api_key=API_KEY,
            endpoint="https://gateway.example.test/v1",
        )


@pytest.mark.asyncio
async def test_save_route_reports_endpoint_storage_unavailable_without_059():
    app, *_ = build_chat_app(d1=SQLiteD1())
    response = await request(
        app,
        "PUT",
        "/api/chat/custom/credential",
        uid=OWNER,
        json_body={
            "provider": "openai",
            "api_key": API_KEY,
            "endpoint": "https://gateway.example.test/v1",
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "custom_endpoint_storage_unavailable"
    assert API_KEY not in response.text


# ---------------------------------------------------------------------------
# SSRF / DNS / redirect guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://gateway.example.test/v1",
        "https://user:pass@gateway.example.test/v1",
        "https://gateway.example.test/v1?key=1",
        "https://gateway.example.test/v1#frag",
        "https://gateway.example.test:8443/v1",
        "https://127.0.0.1/v1",
        "https://2130706433/v1",
        "https://0x7f000001/v1",
        "https://localhost/v1",
        "https://metadata.google.internal/v1",
        "https://service.local/v1",
        "https://internal/v1",
        "https://gateway.example.test\\@evil.example.test/v1",
        "https://gateway.example.test/ v1",
        "https://" + "a" * 2049,
    ],
)
def test_endpoint_normalization_rejects_unsafe_values(endpoint):
    with pytest.raises(CustomEndpointError):
        normalize_custom_endpoint(endpoint, default_endpoint="https://api.openai.com/v1")


def test_endpoint_normalization_canonicalizes_safe_values():
    assert normalize_custom_endpoint(
        "  https://Gateway.Example.TEST/v1/  ",
        default_endpoint="https://api.openai.com/v1",
    ) == "https://gateway.example.test/v1"
    assert normalize_custom_endpoint(
        None, default_endpoint="https://api.openai.com/v1"
    ) == "https://api.openai.com/v1"
    assert normalize_custom_endpoint(
        "https://gateway.example.test", default_endpoint="https://api.openai.com/v1"
    ) == "https://gateway.example.test"


@pytest.mark.asyncio
async def test_dns_verification_rejects_private_unresolved_and_empty_answers():
    default = "https://api.openai.com/v1"
    endpoint = "https://gateway.example.test/v1"
    assert await verify_public_endpoint(
        endpoint, default_endpoint=default, resolver=StaticResolver()
    ) == endpoint

    with pytest.raises(CustomEndpointVerificationError):
        await verify_public_endpoint(
            endpoint, default_endpoint=default, resolver=StaticResolver(("10.0.0.8",))
        )
    with pytest.raises(CustomEndpointVerificationError):
        await verify_public_endpoint(
            endpoint, default_endpoint=default, resolver=StaticResolver(())
        )
    with pytest.raises(CustomEndpointUnverifiedError):
        await verify_public_endpoint(
            endpoint,
            default_endpoint=default,
            resolver=StaticResolver(error=RuntimeError("dns down")),
        )

    resolver = StaticResolver()
    assert await verify_public_endpoint(
        default, default_endpoint=default, resolver=resolver
    ) == default
    assert resolver.hosts == []


@pytest.mark.asyncio
async def test_custom_endpoint_is_verified_before_the_key_is_used():
    def handler(_request):
        raise AssertionError("provider must not be called for an unsafe endpoint")

    selection = resolve_custom_selection("openai", OPENAI_MODEL)
    recorder = ProviderRecorder(handler)

    with pytest.raises(CustomProviderError) as unsafe:
        await client_for(recorder, resolver=StaticResolver(("10.0.0.8",))).complete(
            selection=selection,
            api_key=API_KEY,
            endpoint="https://gateway.example.test/v1",
            messages=[{"role": "user", "content": "hi"}],
            stream=False,
        )
    assert (unsafe.value.status_code, unsafe.value.code) == (502, "custom_endpoint_unsafe")

    with pytest.raises(CustomProviderError) as unverified:
        await client_for(
            recorder, resolver=StaticResolver(error=RuntimeError("dns down"))
        ).complete(
            selection=selection,
            api_key=API_KEY,
            endpoint="https://gateway.example.test/v1",
            messages=[{"role": "user", "content": "hi"}],
            stream=False,
        )
    assert (unverified.value.status_code, unverified.value.code) == (
        502,
        "custom_endpoint_unverified",
    )
    assert recorder.requests == []


@pytest.mark.asyncio
async def test_provider_redirect_is_blocked_without_reaching_another_host():
    recorder = ProviderRecorder(
        lambda _request: httpx.Response(
            302, headers={"location": "https://evil.example.test/steal"}
        )
    )
    with pytest.raises(CustomProviderError) as error:
        await client_for(recorder).complete(
            selection=resolve_custom_selection("openai", OPENAI_MODEL),
            api_key=API_KEY,
            endpoint=CUSTOM_PROVIDERS["openai"].base_origin,
            messages=[{"role": "user", "content": "hi"}],
            stream=False,
        )
    assert (error.value.status_code, error.value.code) == (
        502,
        "custom_provider_redirect_blocked",
    )
    assert len(recorder.requests) == 1
    assert str(recorder.requests[0].url).startswith("https://api.openai.com/")


@pytest.mark.asyncio
async def test_save_route_rejects_unsafe_endpoints_and_stores_nothing():
    app, d1, *_ = build_chat_app()
    for endpoint in (
        "http://gateway.example.test/v1",
        "https://127.0.0.1/v1",
        "https://gateway.example.test:8443/v1",
        "https://gateway.example.test/v1?x=1",
    ):
        response = await request(
            app,
            "PUT",
            "/api/chat/custom/credential",
            uid=OWNER,
            json_body={"provider": "openai", "api_key": API_KEY, "endpoint": endpoint},
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "custom_endpoint_invalid"
        assert API_KEY not in response.text
    assert d1.credential_row() is None


# ---------------------------------------------------------------------------
# Chat product integration with Anthropic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_byok_direct_uses_anthropic_and_saves_history_without_b14():
    recorder = ProviderRecorder(anthropic_handler)
    app, d1, history, _, _, b14 = build_chat_app(recorder=recorder)
    await save_provider_key(app, "anthropic")

    response = await request(
        app,
        "POST",
        "/api/chat",
        uid=OWNER,
        json_body=chat_body("anthropic", ANTHROPIC_MODEL),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["answer"] == DEFAULT_ANSWER
    assert payload["conversation_id"].startswith("chat_")

    wire = recorder.requests[0]
    assert str(wire.url) == "https://api.anthropic.com/v1/messages"
    assert wire.headers["x-api-key"] == API_KEY
    sent = json.loads(wire.content)
    assert sent["model"] == ANTHROPIC_MODEL
    assert sent["messages"] == [{"role": "user", "content": "안녕하세요"}]
    assert [row["role"] for row in d1.messages(payload["conversation_id"])] == [
        "user",
        "assistant",
    ]
    assert b14.calls == 0


@pytest.mark.asyncio
async def test_managed_tier_request_still_reaches_b14():
    recorder = ProviderRecorder(openai_json_handler())
    app, *_ = build_chat_app(recorder=recorder)
    b14 = app.state.b14_client

    response = await request(
        app,
        "POST",
        "/api/chat",
        uid=OWNER,
        json_body={
            "messages": [{"role": "user", "content": "안녕하세요"}],
            "tier": "free",
        },
    )
    assert response.status_code == 502
    assert b14.calls == 1
    assert recorder.requests == []


@pytest.mark.asyncio
async def test_invalid_model_and_key_are_rejected_before_dispatch():
    recorder = ProviderRecorder(openai_json_handler())
    app, *_ = build_chat_app(recorder=recorder)

    invalid_model = await request(
        app,
        "POST",
        "/api/chat",
        uid=OWNER,
        json_body=chat_body("anthropic", "model with spaces"),
    )
    assert invalid_model.status_code == 422
    assert invalid_model.json()["error"]["code"] == "custom_provider_unsupported"

    unknown_provider = await request(
        app,
        "POST",
        "/api/chat",
        uid=OWNER,
        json_body=chat_body("unknown-provider", ANTHROPIC_MODEL),
    )
    assert unknown_provider.status_code == 422
    assert unknown_provider.json()["error"]["code"] == "custom_provider_unsupported"

    short_key = await request(
        app,
        "PUT",
        "/api/chat/custom/credential",
        uid=OWNER,
        json_body={"provider": "anthropic", "api_key": "short"},
    )
    assert short_key.status_code == 422
    assert short_key.json()["error"]["code"] == "custom_key_invalid"
    assert recorder.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_status", "code"),
    [
        (401, 502, "custom_provider_auth_failed"),
        (429, 429, "custom_provider_rate_limited"),
        (500, 502, "custom_provider_unavailable"),
        (418, 502, "custom_provider_rejected"),
    ],
)
async def test_anthropic_errors_are_mapped_without_vendor_leak(
    status, expected_status, code
):
    recorder = ProviderRecorder(
        lambda _request: httpx.Response(status, json={"error": "vendor secret detail"})
    )
    app, *_ = build_chat_app(recorder=recorder)
    await save_provider_key(app, "anthropic")

    response = await request(
        app,
        "POST",
        "/api/chat",
        uid=OWNER,
        json_body=chat_body("anthropic", ANTHROPIC_MODEL),
    )
    assert response.status_code == expected_status
    assert response.json()["error"]["code"] == code
    assert "vendor" not in response.text
    assert API_KEY not in response.text


@pytest.mark.asyncio
async def test_provider_credentials_are_isolated_from_each_other():
    d1 = EndpointD1()
    credential_store = store_for(d1)
    await credential_store.save(user_id=OWNER, provider_id="openai", api_key=API_KEY)
    await credential_store.save(
        user_id=OWNER, provider_id="anthropic", api_key=OTHER_API_KEY
    )

    openai = await credential_store.credential(OWNER, "openai")
    anthropic = await credential_store.credential(OWNER, "anthropic")
    assert openai == (API_KEY, CUSTOM_PROVIDERS["openai"].base_origin)
    assert anthropic == (OTHER_API_KEY, CUSTOM_PROVIDERS["anthropic"].base_origin)
    assert [row["provider"] for row in await credential_store.status(OWNER)] == [
        "anthropic",
        "openai",
    ]

    assert await credential_store.delete(OWNER, "openai") is True
    assert await credential_store.api_key(OWNER, "openai") is None
    assert await credential_store.api_key(OWNER, "anthropic") == OTHER_API_KEY


# ---------------------------------------------------------------------------
# Custom endpoint chat and owner/provider/endpoint isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_endpoint_chat_uses_the_bound_host_and_owner_key():
    recorder = ProviderRecorder(openai_stream_handler())
    app, d1, *_ = build_chat_app(recorder=recorder)
    await save_provider_key(app, "openai", uid=OWNER,
                            endpoint="https://gateway-one.example.test/v1")
    await save_provider_key(app, "openai", api_key=OTHER_API_KEY, uid=OTHER,
                            endpoint="https://gateway-two.example.test/v1")

    owner = await request(
        app, "POST", "/api/chat", uid=OWNER,
        json_body=chat_body("openai", OPENAI_MODEL),
    )
    assert owner.status_code == 200, owner.text
    other = await request(
        app, "POST", "/api/chat", uid=OTHER,
        json_body=chat_body("openai", OPENAI_MODEL),
    )
    assert other.status_code == 200, other.text

    assert str(recorder.requests[0].url) == (
        "https://gateway-one.example.test/v1/chat/completions"
    )
    assert recorder.requests[0].headers["authorization"] == "Bearer " + API_KEY
    assert str(recorder.requests[1].url) == (
        "https://gateway-two.example.test/v1/chat/completions"
    )
    assert recorder.requests[1].headers["authorization"] == "Bearer " + OTHER_API_KEY
    assert d1.credential_row(OWNER, "openai")["endpoint"] == (
        "https://gateway-one.example.test/v1"
    )
    assert d1.credential_row(OTHER, "openai")["endpoint"] == (
        "https://gateway-two.example.test/v1"
    )


# ---------------------------------------------------------------------------
# Claw and B66 product integration with Anthropic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claw_and_b66_use_a_non_opencode_provider_without_b14():
    from test_5121_byok_claw_b66_product_e2e import (
        Harness,
        TURN_TOKEN,
        seed_saved_skill,
    )

    custom = custom_selection("anthropic", ANTHROPIC_MODEL)
    harness = Harness(recorder=ProviderRecorder(anthropic_handler))
    await save_provider_key(harness.app, "anthropic")

    claw = await request(
        harness.app,
        "POST",
        "/api/claw/general",
        uid=OWNER,
        json_body={
            "messages": [{"role": "user", "content": "Claw 질문"}],
            "custom": custom,
        },
    )
    assert claw.status_code == 200, claw.text
    events = sse_events(claw.text)
    assert [name for name, _ in events] == ["delta", "done"]
    assert events[0][1] == {"delta": DEFAULT_ANSWER}
    assert harness.recorder.requests[0].headers["x-api-key"] == API_KEY

    skill_id = await seed_saved_skill(harness.skill_store, OWNER)
    quote = await request(
        harness.app,
        "POST",
        "/api/b66/quote/interpret",
        uid=OWNER,
        json_body={
            "saved_skill_id": skill_id,
            "message": "ABC건설 견적",
            "custom": custom,
        },
    )
    assert quote.status_code == 200, quote.text
    assert quote.headers["X-B66-Result-Origin"] == "custom_provider_direct"
    assert quote.json()["candidate"]["recipient"]["company"] == "ABC건설"

    ai_chat = await request(
        harness.app,
        "POST",
        "/api/b66/ai/chat",
        uid=OWNER,
        json_body={
            "messages": [{"role": "user", "content": "B66 질문"}],
            "turn_token": TURN_TOKEN,
            "custom": custom,
        },
    )
    assert ai_chat.status_code == 200, ai_chat.text
    body = ai_chat.json()
    assert body["answer"] == DEFAULT_ANSWER
    assert body["model_id"] == ANTHROPIC_MODEL
    assert body["model_origin"] == "custom_provider_direct"
    assert harness.d1.attempt_rows()[0]["state"] == "completed"

    for wire in harness.recorder.requests:
        assert str(wire.url) == "https://api.anthropic.com/v1/messages"
        assert wire.headers["x-api-key"] == API_KEY
    assert len(harness.recorder.requests) == 3
    harness.assert_no_managed_dispatch()


@pytest.mark.parametrize("provider,prefix", [
    ("anthropic", "sk-ant-"), ("gemini", "AIza"), ("openai", "sk-proj-"),
    ("openai", "sk-"), ("groq", "gsk_"), ("xai", "xai-"),
    ("perplexity", "pplx-"), ("openrouter", "sk-or-"), ("huggingface", "hf_"),
])
async def test_byok_detect_prefix_table_verifies_without_key_echo(provider, prefix, caplog):
    from app.byok_client import detect_byok
    key = prefix + "synthetic" * 6
    calls = []
    def handler(req):
        calls.append((req.method, req.url.path))
        if req.url.path.endswith("/models"):
            if provider == "gemini":
                return httpx.Response(200, json={"models": [{"name": "models/chat-light", "supportedGenerationMethods": ["generateContent"]}]})
            return httpx.Response(200, json={"data": [{"id": "chat-light"}]})
        if req.method == "POST":
            assert json.loads(req.content)["max_tokens"] == 1
            return httpx.Response(200, json={"choices": [{"message": {"content": "H"}}]})
        return httpx.Response(200, json={"data": {}})
    result = await detect_byok(CustomProviderClient(transport=httpx.MockTransport(handler), endpoint_resolver=StaticResolver()), key=key)
    assert result["provider"] == provider and result["verified"] is True
    assert bool(result["models"])
    assert not bool(key in json.dumps(result) or key in caplog.text)
    assert len(calls) <= 2


@pytest.mark.parametrize("status,expected,calls_expected", [(401, "deepseek", 2), (403, "openai", 1), (502, "openai", 1)])
async def test_byok_ambiguous_sk_only_retries_deepseek_after_401(status, expected, calls_expected):
    from app.byok_client import detect_byok
    calls = []
    def handler(req):
        calls.append(req.url.host)
        if req.url.host == "api.openai.com":
            return httpx.Response(status)
        return httpx.Response(200, json={"data": [{"id": "deepseek-flash"}]})
    result = await detect_byok(CustomProviderClient(transport=httpx.MockTransport(handler)), key="sk-" + "synthetic" * 6)
    assert result["provider"] == expected
    assert result["verified"] == (status == 401)
    assert len(calls) == calls_expected


async def test_byok_unknown_endpoint_probe_and_registration_reverify_sealed_owner_store(caplog):
    class Recorder:
        def __init__(self):
            self.calls = []
            self.transport = httpx.MockTransport(self.handle)
        def handle(self, req):
            self.calls.append((req.method, req.url.host, req.url.path))
            return httpx.Response(200, json={"data": [{"id": "chat-light"}]})
    recorder = Recorder()
    app, d1, _, store, _, b14 = build_chat_app(recorder=recorder)
    key = "unknown_" + "synthetic" * 6
    body = {"key": key, "base_url": "https://gateway.example.test/v1"}
    unknown = await request(app, "POST", "/api/byok/detect", uid=OWNER, json_body={"key": key})
    assert unknown.json()["verified"] is False and not recorder.calls
    detect = await request(app, "POST", "/api/byok/detect", uid=OWNER, json_body=body)
    assert detect.json()["verified"] is True
    assert await store.credential(OWNER, "openai") is None
    denied = await request(app, "POST", "/api/byok/register", uid=OWNER,
        json_body={**body, "provider": "groq", "model": "chat-light"})
    assert denied.status_code == 409
    registered = await request(app, "POST", "/api/byok/register", uid=OWNER,
        json_body={**body, "provider": "openai", "model": "chat-light"})
    assert registered.status_code == 200
    assert registered.json()["selection"] == {"provider": "openai", "model": "chat-light"}
    assert bool((await store.credential(OWNER, "openai"))[0] == key)
    assert await store.credential(OTHER, "openai") is None
    for response in (unknown, detect, denied, registered):
        assert not bool(key in response.text)
    assert not bool(key in caplog.text)
    assert all(path == "/v1/models" for _, _, path in recorder.calls)


@pytest.mark.parametrize("fault", ["auth", "network", "redirect", "empty", "echo"])
async def test_byok_detect_failure_is_static_and_never_saves_or_echoes_key(fault, caplog):
    from app.byok_client import detect_byok
    key = "gsk_" + "synthetic" * 6
    def handler(req):
        if fault == "network":
            raise httpx.ConnectError("private " + key, request=req)
        if fault == "auth":
            return httpx.Response(401, json={"error": key})
        if fault == "redirect":
            return httpx.Response(302, headers={"Location": "https://untrusted.example.test"})
        return httpx.Response(200, json={"data": [{"id": key}] if fault == "echo" else []})
    result = await detect_byok(CustomProviderClient(transport=httpx.MockTransport(handler)), key=key)
    assert result["verified"] is False
    assert not bool(key in json.dumps(result) or key in caplog.text)
    assert "고급" in result["reason"]


async def test_byok_registered_default_uses_existing_direct_stream_and_no_b14():
    class Recorder:
        def __init__(self):
            self.transport = httpx.MockTransport(self.handle)
        def handle(self, req):
            if req.method == "GET":
                return httpx.Response(200, json={"data": [{"id": "chat-light"}]})
            return sse(data({"choices": [{"delta": {"content": "direct answer"}}]}),
                       "data: [DONE]\n\n")
    app, _, _, _, _, b14 = build_chat_app(recorder=Recorder())
    registered = await request(app, "POST", "/api/byok/register", uid=OWNER,
        json_body={"key": "gsk_" + "synthetic" * 6})
    assert registered.status_code == 200
    selection = registered.json()["selection"]
    response = await request(app, "POST", "/api/chat/stream", uid=OWNER,
        json_body={"messages": [{"role": "user", "content": "hello"}], "custom": selection})
    assert response.status_code == 200
    assert "direct answer" in response.text
    assert not b14.calls
