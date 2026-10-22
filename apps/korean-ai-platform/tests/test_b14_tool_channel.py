"""The B14 gateway's model-native tool channel (#5536).

The gateway validates a tool declaration before any provider call, refuses a
tool request for a model that cannot serve one before execution, and relays the
tool declaration to the provider that will answer it.
"""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import platform as plat
from app.pilot.catalog import get_catalog_by_id

CHAT_PATH = "/api/pilot/v1/chat/completions"

#: A registry model that declares the tool capability.
TOOL_CAPABLE_MODEL = "tokenharbor/deepseek-v4.1-flash:free"
#: A registry model that does not.
PLAIN_MODEL = "google/gemma-4-31b-it"

TOOL = {
    "type": "function",
    "function": {
        "name": "generateSandboxedUi",
        "description": "Generate the interactive UI.",
        "parameters": {
            "type": "object",
            "properties": {
                "css": {"type": "string"},
                "html": {"type": "string"},
            },
            "required": ["css", "html"],
        },
    },
}

TOOL_CALL_ANSWER = {
    "id": "chatcmpl-tool",
    "object": "chat.completion",
    "model": "deepseek-v4.1-flash:free",
    "choices": [
        {
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "generateSandboxedUi",
                            "arguments": json.dumps(
                                {"css": "p{}", "html": "<p>hi</p>"}
                            ),
                        },
                    }
                ],
            },
        }
    ],
    "usage": {"prompt_tokens": 12, "completion_tokens": 9, "total_tokens": 21},
}


@pytest.fixture()
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _mock_provider_mode(monkeypatch):
    """The catalog lane runs in mock mode: no provider call, no credential."""
    from app.pilot.b14_runtime_config import runtime_config as rcfg

    saved = rcfg.provider_mode
    rcfg.provider_mode = "mock"
    yield
    rcfg.provider_mode = saved


def _post(client: TestClient, body: dict) -> httpx.Response:
    return client.post(CHAT_PATH, json=body)


# ---------------------------------------------------------------------------
# The registry declares the capability
# ---------------------------------------------------------------------------


def test_the_registry_declares_the_tool_capability_for_a_verified_model() -> None:
    model = get_catalog_by_id(TOOL_CAPABLE_MODEL)

    assert model is not None
    assert "tools" in model.capabilities


def test_the_registry_does_not_declare_the_tool_capability_for_a_plain_model() -> None:
    model = get_catalog_by_id(PLAIN_MODEL)

    assert model is not None
    assert "tools" not in model.capabilities


# ---------------------------------------------------------------------------
# The declaration is validated before any provider call
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tools",
    [
        [{"name": "no_function_object"}],
        [{"type": "not_a_function", "function": {"name": "x"}}],
        [{"type": "function", "function": {"name": "bad name!"}}],
        [{"type": "function", "function": {"name": "x", "parameters": "nope"}}],
    ],
)
def test_a_malformed_tool_declaration_is_refused(client, tools) -> None:
    response = _post(
        client,
        {
            "model": TOOL_CAPABLE_MODEL,
            "messages": [{"role": "user", "content": "화면을 만들어줘"}],
            "tools": tools,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_body"


def test_a_tool_choice_naming_an_undeclared_tool_is_refused(client) -> None:
    response = _post(
        client,
        {
            "model": TOOL_CAPABLE_MODEL,
            "messages": [{"role": "user", "content": "화면을 만들어줘"}],
            "tools": [TOOL],
            "tool_choice": {"type": "function", "function": {"name": "otherTool"}},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_body"


def test_a_tool_message_must_carry_a_tool_call_id(client) -> None:
    response = _post(
        client,
        {
            "model": TOOL_CAPABLE_MODEL,
            "messages": [{"role": "tool", "content": "{}"}],
            "tools": [TOOL],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_body"


def test_an_unknown_top_level_field_is_still_refused(client) -> None:
    response = _post(
        client,
        {
            "model": TOOL_CAPABLE_MODEL,
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [TOOL],
            "tool_choice": "auto",
            "not_a_field": 1,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_body"


# ---------------------------------------------------------------------------
# The capability is checked before execution
# ---------------------------------------------------------------------------


def test_a_model_without_the_tool_capability_is_refused_before_execution(
    client, monkeypatch
) -> None:
    calls: list[dict] = []

    async def _upstream(**kwargs):
        calls.append(kwargs)
        return dict(TOOL_CALL_ANSWER)

    monkeypatch.setattr(plat, "call_platform_chat_completions", _upstream)
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_05", "synthetic_test_key_01")

    response = _post(
        client,
        {
            "model": PLAIN_MODEL,
            "messages": [{"role": "user", "content": "화면을 만들어줘"}],
            "tools": [TOOL],
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "tools_not_supported"
    # The refusal happened before execution: no provider call was made.
    assert calls == []


def test_a_tool_capable_model_receives_the_declaration(client, monkeypatch) -> None:
    calls: list[dict] = []

    async def _upstream(**kwargs):
        calls.append(kwargs)
        return dict(TOOL_CALL_ANSWER)

    monkeypatch.setattr(plat, "call_platform_chat_completions", _upstream)
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_13", "synthetic_test_key_02")

    response = _post(
        client,
        {
            "model": TOOL_CAPABLE_MODEL,
            "messages": [{"role": "user", "content": "화면을 만들어줘"}],
            "tools": [TOOL],
            "tool_choice": {"type": "function", "function": {"name": "generateSandboxedUi"}},
        },
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "generateSandboxedUi",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "css": {"type": "string"},
                        "html": {"type": "string"},
                    },
                    "required": ["css", "html"],
                },
                "description": "Generate the interactive UI.",
            },
        }
    ]
    assert calls[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "generateSandboxedUi"},
    }
    # The tool call comes back to the caller as the model's answer.
    body = response.json()
    assert body["choices"][0]["finish_reason"] == "tool_calls"
    call = body["choices"][0]["message"]["tool_calls"][0]
    assert call["id"] == "call_1"
    assert call["function"]["name"] == "generateSandboxedUi"


def test_a_request_without_a_tool_declares_no_tool(client, monkeypatch) -> None:
    calls: list[dict] = []

    async def _upstream(**kwargs):
        calls.append(kwargs)
        return {
            "id": "chatcmpl-text",
            "object": "chat.completion",
            "model": "deepseek-v4.1-flash:free",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "안녕하세요"},
                }
            ],
        }

    monkeypatch.setattr(plat, "call_platform_chat_completions", _upstream)
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_13", "synthetic_test_key_03")

    response = _post(
        client,
        {
            "model": TOOL_CAPABLE_MODEL,
            "messages": [{"role": "user", "content": "안녕하세요"}],
        },
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert "tools" not in calls[0]
    assert "tool_choice" not in calls[0]


def test_the_byok_lane_refuses_a_tool_declaration(client, monkeypatch) -> None:
    from app.pilot.config import pilot_settings

    # The BYOK lane is configured for this test only; the configuration is
    # restored so the surrounding suite sees an unconfigured pilot.
    monkeypatch.setattr(
        pilot_settings, "pilot_base_url", "https://api.test-pilot.example.com"
    )
    monkeypatch.setattr(pilot_settings, "pilot_model_id", "test-model-v1")

    response = client.post(
        CHAT_PATH,
        json={
            "model": "test-model-v1",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [TOOL],
        },
        headers={"X-Business14-Provider-Key": "sk-real-key-12345abcdef"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "tools_not_supported"


# ---------------------------------------------------------------------------
# The provider adapter
# ---------------------------------------------------------------------------


def _tool_call_transport(seen: list, payload: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


@pytest.fixture()
def live_provider_mode(monkeypatch):
    """The adapter reaches the provider only in live mode."""
    from app.pilot.b14_runtime_config import runtime_config as rcfg

    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_13", "synthetic_test_key_04")
    saved = rcfg.provider_mode
    rcfg.provider_mode = "live"
    yield
    rcfg.provider_mode = saved


@pytest.mark.asyncio
async def test_the_adapter_sends_the_tool_declaration_upstream(live_provider_mode) -> None:
    seen: list[dict] = []

    await plat.call_platform_chat_completions(
        model_id=TOOL_CAPABLE_MODEL,
        upstream_model="deepseek-v4.1-flash:free",
        provider="TokenHarbor",
        platform_provider_id="tokenharbor",
        messages=[{"role": "user", "content": "화면을 만들어줘"}],
        tools=[
            {
                "type": "function",
                "function": {"name": "generateSandboxedUi", "parameters": {"type": "object"}},
            }
        ],
        tool_choice={"type": "function", "function": {"name": "generateSandboxedUi"}},
        transport=_tool_call_transport(seen, TOOL_CALL_ANSWER),
    )

    assert len(seen) == 1
    assert seen[0]["tools"][0]["function"]["name"] == "generateSandboxedUi"
    assert seen[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "generateSandboxedUi"},
    }


@pytest.mark.asyncio
async def test_the_adapter_accepts_a_tool_call_answer(live_provider_mode) -> None:
    seen: list[dict] = []

    result = await plat.call_platform_chat_completions(
        model_id=TOOL_CAPABLE_MODEL,
        upstream_model="deepseek-v4.1-flash:free",
        provider="TokenHarbor",
        platform_provider_id="tokenharbor",
        messages=[{"role": "user", "content": "화면을 만들어줘"}],
        tools=[
            {
                "type": "function",
                "function": {"name": "generateSandboxedUi", "parameters": {"type": "object"}},
            }
        ],
        transport=_tool_call_transport(seen, TOOL_CALL_ANSWER),
    )

    call = result["choices"][0]["message"]["tool_calls"][0]
    assert call["id"] == "call_1"
    assert call["function"]["name"] == "generateSandboxedUi"


@pytest.mark.asyncio
async def test_an_empty_answer_without_a_tool_is_still_refused(live_provider_mode) -> None:
    from app.pilot.upstream_answer_contract import UpstreamEmptyAnswer

    seen: list[dict] = []
    empty = {
        "id": "chatcmpl-empty",
        "object": "chat.completion",
        "model": "deepseek-v4.1-flash:free",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": ""},
            }
        ],
    }

    with pytest.raises(UpstreamEmptyAnswer):
        await plat.call_platform_chat_completions(
            model_id=TOOL_CAPABLE_MODEL,
            upstream_model="deepseek-v4.1-flash:free",
            provider="TokenHarbor",
            platform_provider_id="tokenharbor",
            messages=[{"role": "user", "content": "hi"}],
            transport=_tool_call_transport(seen, empty),
        )
