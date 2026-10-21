"""The request and result contracts refuse what they should."""

from __future__ import annotations

import pytest

from app.contracts import (
    DESIGNER_TOOL_NAME,
    DESIGNER_TOOL_PARAMETERS,
    DesignerError,
    GeneratedUi,
    InteractionState,
    UiRequest,
    UiTurnResult,
)


def test_the_tool_name_and_parameter_order_are_the_upstream_ones() -> None:
    assert DESIGNER_TOOL_NAME == "generateSandboxedUi"
    assert DESIGNER_TOOL_PARAMETERS == (
        "initialHeight",
        "placeholderMessages",
        "css",
        "html",
        "jsFunctions",
        "jsExpressions",
    )


def test_a_prompt_is_required() -> None:
    with pytest.raises(DesignerError) as error:
        UiRequest.from_payload({"prompt": "   "})

    assert error.value.status_code == 400
    assert error.value.code == "prompt_required"


def test_an_oversized_prompt_is_refused() -> None:
    with pytest.raises(DesignerError) as error:
        UiRequest.from_payload({"prompt": "x" * 20_000})

    assert error.value.code == "prompt_too_long"


def test_a_history_entry_must_be_an_object_with_a_role_and_content() -> None:
    with pytest.raises(DesignerError) as error:
        UiRequest.from_payload({"prompt": "hi", "history": ["nope"]})

    assert error.value.code == "history_invalid"

    with pytest.raises(DesignerError) as error:
        UiRequest.from_payload({"prompt": "hi", "history": [{"role": "user"}]})

    assert error.value.code == "history_invalid"


def test_the_interaction_state_keeps_only_scalar_control_values() -> None:
    request = UiRequest.from_payload(
        {
            "prompt": "next",
            "interaction_state": {
                "values": {"qty": 5, "name": "a", "bad": {"x": 1}, "flag": True},
                "prompt": "raise the total",
            },
        }
    )

    assert request.interaction_state.values == {
        "qty": "5",
        "name": "a",
        "flag": "True",
    }
    assert request.interaction_state.prompt == "raise the total"


def test_an_empty_interaction_state_is_reported_as_empty() -> None:
    assert InteractionState().is_empty() is True
    assert InteractionState(values={"a": "1"}).is_empty() is False


def test_a_generated_ui_serializes_to_the_upstream_channel_names() -> None:
    ui = GeneratedUi(
        html="<div></div>",
        css=".a{}",
        js_functions="function f(){}",
        js_expressions=("f();",),
        title="T",
    )

    payload = ui.to_public_dict()

    assert payload["html"] == "<div></div>"
    assert payload["css"] == ".a{}"
    assert payload["jsFunctions"] == "function f(){}"
    assert payload["jsExpressions"] == ["f();"]
    assert payload["title"] == "T"


def test_a_turn_result_reports_whether_the_tool_was_called() -> None:
    result = UiTurnResult(
        text="",
        ui=GeneratedUi(html="<div></div>"),
        model_id="m",
        route_kind="openai_compatible",
        tool_called=True,
        context_sent={"values": {"qty": "2"}},
    )

    payload = result.to_public_dict()

    assert payload["toolCalled"] is True
    assert payload["contextSent"] == {"values": {"qty": "2"}}
    assert payload["ui"] is not None
