"""The sandbox document keeps the upstream assembly rules."""

from __future__ import annotations

from app.contracts import GeneratedUi
from app.sandbox import (
    build_sandbox_document,
    escape_script_close,
    escape_style_close,
)


def _ui(**overrides) -> GeneratedUi:
    base = {
        "html": "<div><input id=\"qty\" type=\"number\"><p id=\"out\">0</p></div>",
        "css": ".x { color: red; }",
        "js_functions": "function recompute(){ document.getElementById('out').textContent = '9'; }",
        "js_expressions": ("recompute();",),
    }
    base.update(overrides)
    return GeneratedUi(**base)


def test_the_generated_css_goes_into_its_own_style_block() -> None:
    document = build_sandbox_document(_ui())

    assert "<style>.x { color: red; }</style>" in document


def test_the_generated_functions_are_one_classic_script_at_the_top_level() -> None:
    document = build_sandbox_document(_ui())

    assert "function recompute()" in document
    # The upstream keeps the function declarations outside any function scope so
    # an inline onclick="fn()" handler can resolve them.
    assert "<script>\nfunction recompute()" in document


def test_the_generated_expressions_run_inside_one_async_iife() -> None:
    document = build_sandbox_document(_ui())

    assert "(async () => {" in document
    assert "recompute();" in document


def test_a_generated_script_cannot_close_its_own_tag() -> None:
    assert escape_script_close("a</script>b") == "a<\\/script>b"
    document = build_sandbox_document(_ui(js_functions="x = '</script>'"))
    assert "</script>x = '" not in document


def test_a_generated_style_cannot_close_its_own_tag() -> None:
    assert escape_style_close("a</style>b") == "a<\\/style>b"
    document = build_sandbox_document(_ui(css="x { content: '</style>'; }"))
    assert "</style>x { content" not in document


def test_the_document_carries_the_padiem_bridge() -> None:
    document = build_sandbox_document(_ui())

    assert "ui_state" in document
    assert "sendPrompt" in document
    assert "ui_ready" in document


def test_the_document_carries_the_websandbox_bridge_the_upstream_prompt_names() -> None:
    document = build_sandbox_document(_ui())

    assert "Websandbox" in document
    assert "connection" in document


def test_the_theme_variables_the_upstream_prompt_names_are_defined() -> None:
    document = build_sandbox_document(_ui())

    for token in (
        "--color-text-primary",
        "--color-text-secondary",
        "--color-background-secondary",
    ):
        assert token in document


def test_an_empty_ui_still_produces_a_valid_document() -> None:
    document = build_sandbox_document(GeneratedUi(html=""))

    assert document.startswith("<!DOCTYPE html>")
    assert "<body>" in document
