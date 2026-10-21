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


def test_the_b14_route_reports_the_missing_tool_channel_instead_of_pretending() -> None:
    route = B14Route(_settings(model_route="b14"))

    assert route.supports_tool_calls is False

    import asyncio

    with pytest.raises(DesignerError) as error:
        asyncio.run(route.generate(ModelRequest(system_prompt="s", user_prompt="u")))

    assert error.value.status_code == 503
    assert error.value.code == "b14_route_not_bound"
