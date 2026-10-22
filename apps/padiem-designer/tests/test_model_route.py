"""The model route speaks the upstream tool contract and refuses to guess."""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.contracts import DesignerError
from app.model_route import (
    B14Route,
    ModelRequest,
    OpenAICompatibleRoute,
    designer_tool_schema,
    ui_from_tool_arguments,
)


def _settings(**overrides) -> Settings:
    base = {
        "model_route": "openai_compatible",
        "model_base_url": "https://gateway.invalid/api",
        "model_api_key": "test-key",
        "model_id": "test/model",
    }
    base.update(overrides)
    return Settings(**base)


def test_the_tool_schema_uses_the_upstream_parameter_names_and_order() -> None:
    schema = designer_tool_schema()

    assert schema["function"]["name"] == "generateSandboxedUi"
    properties = list(schema["function"]["parameters"]["properties"])
    assert properties == [
        "initialHeight",
        "placeholderMessages",
        "css",
        "html",
        "jsFunctions",
        "jsExpressions",
    ]


def test_a_generated_ui_is_built_from_the_tool_arguments() -> None:
    ui = ui_from_tool_arguments(
        {
            "initialHeight": 420,
            "placeholderMessages": ["thinking"],
            "css": ".a{color:red}",
            "html": "<div id='x'></div>",
            "jsFunctions": "function go(){}",
            "jsExpressions": ["go();"],
        }
    )

    assert ui.html == "<div id='x'></div>"
    assert ui.css == ".a{color:red}"
    assert ui.js_functions == "function go(){}"
    assert ui.js_expressions == ("go();",)
    assert ui.initial_height == 420
    assert ui.placeholder_messages == ("thinking",)


def test_a_style_block_inside_the_generated_html_is_refused() -> None:
    with pytest.raises(DesignerError) as error:
        ui_from_tool_arguments({"html": "<style>.a{}</style><div></div>", "css": ""})

    assert error.value.status_code == 502
    assert error.value.code == "generated_ui_contract_violation"


def test_a_script_block_inside_the_generated_html_is_refused() -> None:
    with pytest.raises(DesignerError) as error:
        ui_from_tool_arguments({"html": "<div></div><script>go()</script>", "css": ""})

    assert error.value.code == "generated_ui_contract_violation"


def test_the_route_is_refused_when_no_credential_is_configured() -> None:
    route = OpenAICompatibleRoute(_settings(model_base_url="", model_api_key="", model_id=""))

    with pytest.raises(DesignerError) as error:
        import asyncio

        asyncio.run(
            route.generate(ModelRequest(system_prompt="s", user_prompt="u"))
        )

    assert error.value.status_code == 503
    assert error.value.code == "model_route_not_configured"


def test_the_route_reads_the_tool_call_out_of_the_answer() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "Here you go.",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "generateSandboxedUi",
                                        "arguments": json.dumps(
                                            {"css": ".a{}", "html": "<div></div>"}
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    route = OpenAICompatibleRoute(_settings())
    original = httpx.AsyncClient

    class _Client(original):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kwargs):
            kwargs.pop("transport", None)
            super().__init__(*args, transport=httpx.MockTransport(handler), **kwargs)

    httpx.AsyncClient = _Client  # type: ignore[assignment]
    try:
        import asyncio

        turn = asyncio.run(
            route.generate(ModelRequest(system_prompt="system", user_prompt="make a form"))
        )
    finally:
        httpx.AsyncClient = original  # type: ignore[assignment]

    assert turn.text == "Here you go."
    assert len(turn.tool_calls) == 1
    assert turn.model_id == "test/model"
    assert turn.route_kind == "openai_compatible"

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "test/model"
    tools = payload["tools"]
    assert isinstance(tools, list)
    assert tools[0]["function"]["name"] == "generateSandboxedUi"


def test_a_provider_error_is_reported_as_a_route_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "slow down"})

    route = OpenAICompatibleRoute(_settings())
    original = httpx.AsyncClient

    class _Client(original):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kwargs):
            kwargs.pop("transport", None)
            super().__init__(*args, transport=httpx.MockTransport(handler), **kwargs)

    httpx.AsyncClient = _Client  # type: ignore[assignment]
    try:
        import asyncio

        with pytest.raises(DesignerError) as error:
            asyncio.run(
                route.generate(ModelRequest(system_prompt="system", user_prompt="make a form"))
            )
    finally:
        httpx.AsyncClient = original  # type: ignore[assignment]

    assert error.value.status_code == 502
    assert error.value.code == "model_route_error"


class _FakeB14Transport:
    """The service-binding transport protocol the B62 product uses."""

    def __init__(self, *, status_code: int = 200, body: dict | None = None) -> None:
        self.status_code = status_code
        self.body = body if body is not None else _TOOL_CALL_BODY
        self.calls: list[tuple[str, dict]] = []

    async def post_json(self, url: str, payload: dict) -> tuple[int, bytes]:
        self.calls.append((url, payload))
        return self.status_code, json.dumps(self.body).encode("utf-8")


_TOOL_CALL_BODY = {
    "id": "chatcmpl-designer",
    "object": "chat.completion",
    "model": "inception/mercury-2.5",
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
                                {"css": ".a{}", "html": "<div></div>"}
                            ),
                        },
                    }
                ],
            },
        }
    ],
}


def _b14_settings(**overrides) -> Settings:
    base = {
        "model_route": "b14",
        "b14_base_url": "https://b14.invalid",
        "b14_model_id": "inception/mercury-2.5",
    }
    base.update(overrides)
    return Settings(**base)


def test_the_b14_route_declares_the_tool_and_reads_the_call_out_of_the_answer() -> None:
    transport = _FakeB14Transport()
    route = B14Route(_b14_settings(), transport=transport)

    assert route.supports_tool_calls is True

    import asyncio

    turn = asyncio.run(
        route.generate(ModelRequest(system_prompt="system", user_prompt="make a form"))
    )

    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0]["id"] == "call_1"
    assert turn.route_kind == "b14"

    url, payload = transport.calls[0]
    assert url == "https://b14.invalid/api/pilot/v1/chat/completions"
    assert payload["model"] == "inception/mercury-2.5"
    assert payload["tools"][0]["function"]["name"] == "generateSandboxedUi"
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": "generateSandboxedUi"},
    }
    assert [message["role"] for message in payload["messages"]] == ["system", "user"]


def test_the_b14_route_uses_the_automatic_route_when_no_model_is_configured() -> None:
    transport = _FakeB14Transport()
    route = B14Route(_b14_settings(b14_model_id=""), transport=transport)

    import asyncio

    asyncio.run(
        route.generate(ModelRequest(system_prompt="system", user_prompt="make a form"))
    )

    _, payload = transport.calls[0]
    assert payload["model"] == "b14/auto"


def test_the_b14_route_is_refused_when_it_is_not_bound() -> None:
    route = B14Route(_b14_settings())

    import asyncio

    with pytest.raises(DesignerError) as error:
        asyncio.run(route.generate(ModelRequest(system_prompt="s", user_prompt="u")))

    assert error.value.status_code == 503
    assert error.value.code == "b14_route_not_bound"


def test_the_b14_route_carries_a_tool_result_back_to_the_model() -> None:
    # #5536: a tool result is only readable by the model when it travels with
    # the identifier of the call it answers. The route carries that
    # identifier, and the assistant turn that made the call, so the round
    # trip can be replayed.
    transport = _FakeB14Transport()
    route = B14Route(_b14_settings(), transport=transport)

    import asyncio

    asyncio.run(
        route.generate(
            ModelRequest(
                system_prompt="system",
                user_prompt="make a form",
                history=(
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "generateSandboxedUi",
                                    "arguments": '{"html":"<p></p>"}',
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "call_1",
                        "name": "generateSandboxedUi",
                        "content": '{"ok":true}',
                    },
                ),
            )
        )
    )

    _, payload = transport.calls[0]
    assistant = [m for m in payload["messages"] if m["role"] == "assistant"]
    assert assistant[0]["tool_calls"][0]["id"] == "call_1"
    tool_message = [m for m in payload["messages"] if m["role"] == "tool"][0]
    assert tool_message["tool_call_id"] == "call_1"
    assert tool_message["content"] == '{"ok":true}'


def test_a_b14_refusal_is_reported_as_a_route_error() -> None:
    transport = _FakeB14Transport(
        status_code=400,
        body={
            "error": {
                "code": "tools_not_supported",
                "message": "tool capability 없음",
            }
        },
    )
    route = B14Route(_b14_settings(), transport=transport)

    import asyncio

    with pytest.raises(DesignerError) as error:
        asyncio.run(
            route.generate(ModelRequest(system_prompt="s", user_prompt="u"))
        )

    assert error.value.status_code == 502
    assert error.value.code == "model_route_error"
