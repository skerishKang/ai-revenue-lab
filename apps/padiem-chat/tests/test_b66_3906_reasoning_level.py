"""B66 per-model reasoning-level selection contract (#3906).

Network-free tests that never call a provider. They prove the customer's
explicit reasoning choice is honoured exactly, rejected with an explainable
4xx, or omitted so the pre-#3906 request shape is preserved -- and that B66
never guesses an upstream provider parameter (#3977 dependency).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.b66_reasoning_level import (
    DEFAULT_REASONING_LEVEL,
    DEFAULT_REASONING_LABEL,
    is_supported_reasoning_level,
    reasoning_levels_for_model,
    reasoning_options_for_model,
    reasoning_parameter_for_request,
    validate_reasoning_level,
)
from test_b66_quote_runtime import _client, _Interpreter, _Store, SAVED_ID

MODEL = "test-fixture/registered-model"
LEVEL_OPTION = {"value": "default", "label": "기본(제공자 기본값)"}
BODY = {"saved_skill_id": SAVED_ID, "message": "synthetic quote"}
ORIGIN = {"Origin": "https://chat.example.test"}


def _options_client(levels_by_model: dict[str, list[dict[str, str]]]):
    """Authenticated client whose /quote/models advertises reasoning options."""

    class Options:
        async def list_selectable_models(self):
            return [
                {
                    "model_id": model_id,
                    "name": model_id.split("/")[-1],
                    "reasoning_levels": levels_by_model.get(model_id, []),
                }
                for model_id in sorted(levels_by_model)
            ]

    client = _client(_Store(), _Interpreter())
    client.app.state.b66_quote_model_resolver = Options()
    return client


def _capture() -> tuple[list[dict], type]:
    seen: list[dict] = []

    class Recording:
        async def interpret(self, **kwargs):
            seen.append(kwargs)
            raise RuntimeError("stop-after-capture")

    return seen, Recording()


# --------------------------------------------------------------------------
# 1. The exact model the user chose is preserved end to end.
# --------------------------------------------------------------------------

def test_models_api_preserves_exact_registered_model_id_with_options():
    client = _options_client({MODEL: [LEVEL_OPTION]})
    response = client.get("/api/b66/quote/models")
    assert response.status_code == 200
    rows = response.json()["models"]
    assert [row["model_id"] for row in rows] == [MODEL]
    assert rows[0]["name"] == MODEL.split("/")[-1]
    assert rows[0]["reasoning_levels"] == [LEVEL_OPTION]
    # A model is never chosen for the customer by this endpoint.
    assert response.json()["default_model_id"] is None


def test_interpret_forwards_exact_model_id_unchanged():
    seen, recording = _capture()
    client = _client(_Store(), recording)
    client.post(
        "/api/b66/quote/interpret", json={**BODY, "model_id": MODEL}, headers=ORIGIN
    )
    assert seen and seen[0]["model_id"] == MODEL


# --------------------------------------------------------------------------
# 2. Omitting the level keeps the existing behaviour byte for byte.
# --------------------------------------------------------------------------

def test_omitted_reasoning_level_is_not_forwarded_as_a_keyword():
    seen, recording = _capture()
    client = _client(_Store(), recording)
    client.post(
        "/api/b66/quote/interpret", json={**BODY, "model_id": MODEL}, headers=ORIGIN
    )
    assert "reasoning_level" not in seen[0]


def test_omitted_reasoning_level_reaches_interpreter_in_previous_shape():
    calls: list[dict] = []

    class Interpreter:
        async def interpret(self, *, message, skill, model_id=None):
            calls.append({"model_id": model_id})
            return None

    client = _client(_Store(), Interpreter())
    response = client.post(
        "/api/b66/quote/interpret", json={**BODY, "model_id": MODEL}, headers=ORIGIN
    )
    assert response.status_code != 400
    assert calls == [{"model_id": MODEL}]


def test_default_level_is_transmitted_as_no_provider_argument():
    """`default` means "use the provider default": zero upstream arguments."""
    assert reasoning_parameter_for_request(MODEL, DEFAULT_REASONING_LEVEL) == {}
    assert reasoning_parameter_for_request(MODEL, None) == {}


# --------------------------------------------------------------------------
# 3 & 4. Supported level reaches the request; unsupported is blocked.
# --------------------------------------------------------------------------

def test_supported_level_is_validated():
    assert validate_reasoning_level(MODEL, DEFAULT_REASONING_LEVEL) == DEFAULT_REASONING_LEVEL


def test_unsupported_level_is_rejected_with_explainable_4xx_and_never_substituted():
    fake = _Interpreter()
    client = _client(_Store(), fake)
    response = client.post(
        "/api/b66/quote/interpret",
        json={**BODY, "model_id": MODEL, "reasoning_level": "ultra"},
        headers=ORIGIN,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_reasoning_level"
    # Fail closed BEFORE any dispatch: no model call, no silent downgrade.
    assert fake.calls == []


@pytest.mark.parametrize(
    "bad",
    [
        "ultra",
        "high",
        "low",
        "medium",
        "DEFAULT",
        "default ",
        "de",
        "",
        "de" + "f" * 40,
        "de:ault",
        "de_fault",
        "../default",
    ],
)
def test_malformed_or_unknown_levels_are_rejected(bad):
    assert is_supported_reasoning_level(bad) is False
    with pytest.raises(ValueError):
        validate_reasoning_level(MODEL, bad)


def test_unsupported_field_guard_still_rejects_unknown_fields():
    client = _client(_Store(), _Interpreter())
    response = client.post(
        "/api/b66/quote/interpret",
        json={**BODY, "model_id": MODEL, "reasoning_effort": "high"},
        headers=ORIGIN,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_field"


def test_absent_model_id_still_reports_model_error_not_reasoning_error():
    """The model boundary is unchanged: reasoning never masks a bad model."""
    client = _client(_Store(), _Interpreter())
    response = client.post(
        "/api/b66/quote/interpret",
        json={
            "saved_skill_id": SAVED_ID,
            "message": "synthetic",
            "reasoning_level": DEFAULT_REASONING_LEVEL,
        },
        headers=ORIGIN,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "model_selection_required"


# --------------------------------------------------------------------------
# 5. Capability comes only from the B66 model registry, never from guesses.
# --------------------------------------------------------------------------

def test_unverified_model_offers_the_default_option_only():
    """A model without proven reasoning support must not advertise extra levels."""
    client = _options_client({MODEL: []})
    rows = client.get("/api/b66/quote/models").json()["models"]
    assert rows[0]["reasoning_levels"] == [
        {"value": DEFAULT_REASONING_LEVEL, "label": DEFAULT_REASONING_LABEL}
    ]
    assert reasoning_options_for_model(MODEL) == [
        {"value": DEFAULT_REASONING_LEVEL, "label": DEFAULT_REASONING_LABEL}
    ]
    # The closed set is exactly the provider default; nothing else is offered.
    assert reasoning_levels_for_model(MODEL) == frozenset({DEFAULT_REASONING_LEVEL})


def test_capability_source_is_the_served_registry_row_not_b66_source():
    """B66 must not hard-code any upstream provider reasoning parameter."""
    module = Path(__file__).resolve().parents[1] / "app" / "b66_reasoning_level.py"
    source = module.read_text(encoding="utf-8")
    # #3977 owns the upstream mapping. Until it lands, no provider key names
    # (thinkingConfig/reasoning_effort/reasoning.max_tokens) may appear here.
    for forbidden in (
        "thinkingConfig",
        "thinking_budget",
        "reasoning_effort",
        "reasoning_tokens",
        "max_reasoning",
    ):
        assert forbidden not in source


def test_no_parameter_is_emitted_for_any_unproven_level():
    """Fail closed: nothing is ever invented for the provider to consume."""
    assert reasoning_parameter_for_request(MODEL, DEFAULT_REASONING_LEVEL) == {}
    assert reasoning_parameter_for_request(MODEL, None) == {}
    with pytest.raises(ValueError):
        reasoning_parameter_for_request(MODEL, "high")


def test_default_option_is_the_sole_builtin_option_constant():
    assert reasoning_options_for_model(MODEL) == [
        {"value": DEFAULT_REASONING_LEVEL, "label": DEFAULT_REASONING_LABEL}
    ]


# --------------------------------------------------------------------------
# 6. Both B66 UI surfaces share one contract; no hidden model replacement.
# --------------------------------------------------------------------------

def test_both_b66_ui_sources_expose_and_reset_the_reasoning_control():
    """Both B66 surfaces share one contract, each in its own ID namespace.

    The reference UI uses the ``padiemQuote*`` namespace and the embedded
    runtime uses ``b66Quote*``; this mirrors the existing model-select
    convention and must stay in sync for the reasoning control.
    """
    root = Path(__file__).resolve().parents[3]
    reference = (
        root / "reference/business-66-padiem-quote-v1/padiem-account.js"
    ).read_text(encoding="utf-8")
    runtime = (
        root / "apps/padiem-chat/static/b66-quote-runtime.js"
    ).read_text(encoding="utf-8")
    assert "padiemQuoteReasoningSelect" in reference
    assert "reasoning_levels" in reference
    # Changing the model must re-validate/reset the level, never carry it.
    assert "syncReasoningOptions" in reference
    assert 'select.addEventListener("change", syncReasoningOptions)' in reference
    assert "reasoning_level" in reference

    assert "b66QuoteReasoningSelect" in runtime
    assert "reasoning_levels" in runtime
    assert "syncReasoningOptions" in runtime
    assert 'select.addEventListener("change", syncReasoningOptions)' in runtime
    assert "reasoning_level" in runtime

    html = (
        root / "reference/business-66-padiem-quote-v1/index.html"
    ).read_text(encoding="utf-8")
    assert 'id="padiemQuoteReasoningSelect"' in html


def test_no_automatic_model_substitution_or_fallback_in_b66_sources():
    root = Path(__file__).resolve().parents[3]
    sources = [
        root / "apps/padiem-chat/app/b66_quote_routes.py",
        root / "apps/padiem-chat/app/b66_reasoning_level.py",
        root / "reference/business-66-padiem-quote-v1/padiem-account.js",
        root / "apps/padiem-chat/static/b66-quote-runtime.js",
    ]
    for src in sources:
        content = src.read_text(encoding="utf-8")
        assert "fallback_model" not in content
        assert "model_fallback" not in content
        assert "auto_select" not in content
        # An unsupported level must never be silently coerced to another one:
        # no code path may replace a rejected level with a different value.
        assert "downgrade_to" not in content
        assert "reasoning_level = reasoning_level" not in content


# --------------------------------------------------------------------------
# 7. The existing quote extraction -> QuoteCore -> Sol PDF path is untouched.
# --------------------------------------------------------------------------

def test_interpret_still_returns_the_candidate_and_totals_shape():
    """The pre-existing projection shape is unchanged by the new keyword."""
    from app.b66_quote_conversation import B66QuoteConversationProjection

    seen: list[dict] = []

    class Interpreter:
        async def interpret(self, **kwargs):
            seen.append(kwargs)
            return B66QuoteConversationProjection(
                recipient={
                    "company": "ABC상사",
                    "person": None,
                    "address": None,
                    "email": None,
                },
                quote_no=None,
                issue_date=None,
                items=({"name": "상품", "qty": 20, "unitPrice": 30000},),
                memo=None,
                tax_mode=None,
                missing=(),
            )

    client = _client(_Store(), Interpreter())
    response = client.post(
        "/api/b66/quote/interpret",
        json={
            **BODY,
            "model_id": MODEL,
            "reasoning_level": DEFAULT_REASONING_LEVEL,
        },
        headers=ORIGIN,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    # QuoteCore remains the only calculation authority for totals.
    assert "candidate" in body
    assert isinstance(body["candidate"].get("missing"), list)
    # The accepted level reaches the interpreter alongside the exact model.
    assert seen[0]["model_id"] == MODEL
    assert seen[0]["reasoning_level"] == DEFAULT_REASONING_LEVEL


def test_streaming_and_plain_paths_forward_the_same_level():
    """One accepted level value, propagated identically by both call shapes."""
    from app.b66_quote_routes import _interpret_reserved

    seen: list[dict] = []

    class Recording:
        async def interpret(self, **kwargs):
            seen.append(kwargs)
            return None

    asyncio.run(
        _interpret_reserved(
            Recording().interpret,
            message="synthetic quote",
            skill={"variableSchema": {}},
            model_id=MODEL,
            reasoning_level=DEFAULT_REASONING_LEVEL,
        )
    )
    assert seen[0] == {
        "message": "synthetic quote",
        "skill": {"variableSchema": {}},
        "model_id": MODEL,
        "reasoning_level": DEFAULT_REASONING_LEVEL,
    }

    # Omitting the level must not add the keyword at all, so a legacy
    # interpreter with a fixed signature keeps working unchanged.
    seen.clear()
    asyncio.run(
        _interpret_reserved(
            Recording().interpret,
            message="synthetic quote",
            skill={"variableSchema": {}},
            model_id=MODEL,
        )
    )
    assert seen[0] == {
        "message": "synthetic quote",
        "skill": {"variableSchema": {}},
        "model_id": MODEL,
    }
