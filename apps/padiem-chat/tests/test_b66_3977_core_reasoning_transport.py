"""#3977: B66's explicit reasoning level reaches B14 through the shared Core.

PR #3998 merged the B66 side and proved the FAR end of the contract (B14
platform -> provider request). This file proves the NEAR end that was still
missing: the installed B62/B66 client and the shared Core carry the validated
parameter, as a TOP-LEVEL ``reasoning_effort``, through the real
``ExecutionRuntime`` down to the actual B14 HTTP body.

The network is always ``httpx.MockTransport``. Nothing here is evidence of a
paid provider call, and nothing here re-implements the B14 capability
authority: per-model acceptance stays owned by
``apps/korean-ai-platform/app/pilot/model_native_parameters.py``.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.b14_client import B14Client
from app.b66_quote_conversation import B66QuoteConversationInterpreter
from app.b66_registered_model_boundary import (
    B14AuthorizedModelRoute,
    B14QuoteExactModelExecutor,
    B66ModelRouteError,
    B66RegisteredModelCompletion,
)
from app.config import Settings

GEMINI_35 = "google/gemini-3.5-flash-lite"
ATRIA = "atria/Atria-Dawn-Preview"
UNLISTED = "openai/gpt-4.1-mini"
MESSAGES = [{"role": "user", "content": "synthetic quote"}]
B14_URL = "https://b14.internal"


def b14_settings() -> Settings:
    return Settings(
        runtime_mode="b14", b14_base_url=B14_URL, live_enabled=True
    )


def route_for(model_id: str) -> B14AuthorizedModelRoute:
    return B14AuthorizedModelRoute(
        model_id=model_id,
        route_id=f"route-{model_id}",
        owner_policy_id="owner-policy-b66",
        registered=True,
        enabled=True,
        authorized=True,
        credential_ready=True,
        route_count=1,
        capabilities=frozenset({"chat"}),
    )


class CapturingB14:
    """The real Core HTTP boundary: records the exact B14 request body."""

    def __init__(self, selected_model: str) -> None:
        self.selected_model = selected_model
        self.bodies: list[dict] = []
        self.urls: list[str] = []

    @property
    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.bodies.append(json.loads(request.content))
            self.urls.append(str(request.url))
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": '{"items": []}'}}
                    ],
                    "business14": {
                        "request_id": "b14req_3977",
                        "route_mode": "manual",
                        "selected_provider": "Google AI Studio",
                        "selected_model": self.selected_model,
                        "selected_upstream_model": "gemini-3.5-flash-lite",
                        "actual_response_model": "gemini-3.5-flash-lite",
                        "fallback_used": False,
                        "attempt_count": 1,
                    },
                    "usage": {
                        "prompt_tokens": 3,
                        "completion_tokens": 2,
                        "total_tokens": 5,
                    },
                },
            )

        return httpx.MockTransport(handler)


def real_completion(capture: CapturingB14, *, refunds: list[str]):
    """The production chain: trusted resolver -> real executor -> real client."""

    class Resolver:
        async def resolve_quote_model(self, requirements):
            return route_for(requirements.selected_model_id)

    client = B14Client(b14_settings(), transport=capture.transport)

    async def refund() -> None:
        refunds.append("refunded")

    completion = B66RegisteredModelCompletion(
        resolver=Resolver(),
        executor=B14QuoteExactModelExecutor(client),
        refund_pre_dispatch=refund,
    )
    return completion, client


# --------------------------------------------------------------------------
# 1. The capability B66 asks about is now real, not assumed.
# --------------------------------------------------------------------------

def test_client_declares_native_parameter_support_measured_from_the_core() -> None:
    client = B14Client(b14_settings(), transport=CapturingB14(GEMINI_35).transport)
    assert client.supports_native_model_parameters is True
    # The B66 executor reads exactly this attribute to decide whether an
    # explicit level can be honoured.
    assert B14QuoteExactModelExecutor(client).supports_native_parameters is True


def test_gate_follows_the_probe_and_never_a_literal(monkeypatch) -> None:
    """A Core build that cannot carry the field must switch the whole lane off."""
    import app.b14_client as b14_client_module

    monkeypatch.setattr(
        b14_client_module,
        "_native_model_parameter_contract_present",
        lambda: False,
    )
    b14_client_module._native_model_parameter_transport.cache_clear()
    try:
        capture = CapturingB14(GEMINI_35)
        refunds: list[str] = []
        completion, _client = real_completion(capture, refunds=refunds)
        assert _client.supports_native_model_parameters is False
        with pytest.raises(B66ModelRouteError) as raised:
            asyncio.run(
                completion.complete(
                    MESSAGES, model_id=GEMINI_35, reasoning_level="low"
                )
            )
        assert raised.value.code == "model_capability_unavailable"
        # Refused before dispatch: no request left the process at all.
        assert capture.bodies == []
        assert refunds == ["refunded"]
    finally:
        b14_client_module._native_model_parameter_transport.cache_clear()


# --------------------------------------------------------------------------
# 2. An explicit, verified level reaches the real B14 request body.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("level", ["minimal", "low", "medium", "high"])
def test_explicit_level_is_transmitted_as_a_top_level_field(level: str) -> None:
    capture = CapturingB14(GEMINI_35)
    completion, _client = real_completion(capture, refunds=[])
    result = asyncio.run(
        completion.complete(MESSAGES, model_id=GEMINI_35, reasoning_level=level)
    )
    assert result == {"answer": '{"items": []}'}
    assert len(capture.bodies) == 1
    body = capture.bodies[0]
    assert body["reasoning_effort"] == level
    assert "model_parameters" not in body
    # One dispatch, and the exact customer-selected model is unchanged.
    assert body["model"] == GEMINI_35
    assert capture.urls == [f"{B14_URL}/api/pilot/v1/chat/completions"]


def test_atria_offers_only_its_documented_levels_and_is_sent_verbatim() -> None:
    capture = CapturingB14(ATRIA)
    completion, _client = real_completion(capture, refunds=[])
    asyncio.run(
        completion.complete(MESSAGES, model_id=ATRIA, reasoning_level="medium")
    )
    assert capture.bodies[0]["reasoning_effort"] == "medium"
    assert capture.bodies[0]["model"] == ATRIA


# --------------------------------------------------------------------------
# 3. Default and omitted stay omission: byte-identical to the merged shape.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("level", [None, "default"])
def test_unselected_level_sends_no_reasoning_field(level) -> None:
    capture = CapturingB14(GEMINI_35)
    completion, _client = real_completion(capture, refunds=[])
    asyncio.run(
        completion.complete(MESSAGES, model_id=GEMINI_35, reasoning_level=level)
    )
    assert len(capture.bodies) == 1
    body = capture.bodies[0]
    assert "reasoning_effort" not in body
    assert "model_parameters" not in body
    assert body["model"] == GEMINI_35


def test_default_and_high_bodies_differ_only_by_the_native_field() -> None:
    def body_for(level):
        capture = CapturingB14(GEMINI_35)
        completion, _client = real_completion(capture, refunds=[])
        asyncio.run(
            completion.complete(MESSAGES, model_id=GEMINI_35, reasoning_level=level)
        )
        return capture.bodies[0]

    default_body = body_for("default")
    high_body = body_for("high")
    assert high_body["reasoning_effort"] == "high"
    assert {k: v for k, v in high_body.items() if k != "reasoning_effort"} == default_body


# --------------------------------------------------------------------------
# 4. Unsupported, unlisted or stale values never produce a request.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "model_id, level",
    [
        (UNLISTED, "low"),        # model has no verified reasoning contract
        (ATRIA, "minimal"),       # well-formed, not documented for that ID
        (GEMINI_35, "extreme"),   # outside the closed vocabulary
        (GEMINI_35, "auto"),      # never invent a substitution
        (GEMINI_35, "MINIMAL"),   # exact spelling only
    ],
)
def test_refused_levels_issue_no_request_and_refund(model_id: str, level: str) -> None:
    capture = CapturingB14(model_id)
    refunds: list[str] = []
    completion, _client = real_completion(capture, refunds=refunds)
    with pytest.raises(B66ModelRouteError) as raised:
        asyncio.run(
            completion.complete(MESSAGES, model_id=model_id, reasoning_level=level)
        )
    assert raised.value.code == "model_capability_unavailable"
    assert capture.bodies == []
    assert refunds == ["refunded"]


def test_client_rejects_a_malformed_parameter_container() -> None:
    capture = CapturingB14(GEMINI_35)
    client = B14Client(b14_settings(), transport=capture.transport)
    with pytest.raises(Exception) as raised:
        asyncio.run(
            client.complete_registered_quote_model(
                MESSAGES, model=GEMINI_35, model_parameters="low"
            )
        )
    assert getattr(raised.value, "status_code", None) == 422
    assert capture.bodies == []


def test_core_rejects_an_unknown_native_field_before_any_request() -> None:
    """A field the closed contract omits cannot smuggle itself onto the wire."""
    capture = CapturingB14(GEMINI_35)
    client = B14Client(b14_settings(), transport=capture.transport)
    with pytest.raises(Exception):
        asyncio.run(
            client.complete_registered_quote_model(
                MESSAGES,
                model=GEMINI_35,
                model_parameters={"reasoning_effort": "low", "temperature_bias": 0.5},
            )
        )
    assert capture.bodies == []


# --------------------------------------------------------------------------
# 5. The last hop in production is the dispatch-aware client, so it must
#    forward the parameter or the whole lane is dark.
# --------------------------------------------------------------------------

def test_installed_dispatch_aware_client_carries_the_level_to_the_wire() -> None:
    """`DispatchAwareB14Client` is the class Worker installs, not `B14Client`.

    An override that does not forward the parameter would pass every base-class
    test and still refuse the customer's level in production.
    """
    from app.dispatch_quota import DispatchAwareB14Client

    capture = CapturingB14(GEMINI_35)
    dispatch = DispatchAwareB14Client(b14_settings(), transport=capture.transport)
    assert dispatch.supports_native_model_parameters is True
    result = asyncio.run(
        dispatch.complete_registered_quote_model(
            MESSAGES, model=GEMINI_35, model_parameters={"reasoning_effort": "low"}
        )
    )
    assert result["route"]["model"] == GEMINI_35
    assert capture.bodies[0]["reasoning_effort"] == "low"
    assert "model_parameters" not in capture.bodies[0]


def test_dispatch_aware_client_omission_path_is_unchanged() -> None:
    from app.dispatch_quota import DispatchAwareB14Client

    capture = CapturingB14(GEMINI_35)
    dispatch = DispatchAwareB14Client(b14_settings(), transport=capture.transport)
    asyncio.run(
        dispatch.complete_registered_quote_model(MESSAGES, model=GEMINI_35)
    )
    assert "reasoning_effort" not in capture.bodies[0]
    assert "model_parameters" not in capture.bodies[0]


def test_dispatch_override_signature_accepts_the_native_keyword() -> None:
    """Regression: an override that drops the kwarg rejects it in production."""
    import inspect

    from app.dispatch_quota import DispatchAwareB14Client

    base = inspect.signature(B14Client.complete_registered_quote_model)
    override = inspect.signature(DispatchAwareB14Client.complete_registered_quote_model)
    assert "model_parameters" in base.parameters
    assert "model_parameters" in override.parameters
    # The override may not be narrower than the path it forwards.
    missing = set(base.parameters) - set(override.parameters)
    assert missing == set(), f"dispatch override drops {sorted(missing)}"


# --------------------------------------------------------------------------
# 6. The interpreter forwards the customer's level through the real adapter.
# --------------------------------------------------------------------------

def test_interpreter_reaches_the_wire_through_the_real_adapter() -> None:
    capture = CapturingB14(GEMINI_35)
    completion, _client = real_completion(capture, refunds=[])
    interpreter = B66QuoteConversationInterpreter(completion)
    projection = asyncio.run(
        interpreter.interpret(
            message="합성 견적: 항목 A 1개",
            skill={
                "variableSchema": {"items": True, "recipient": True},
                "fixedDefaults": {"taxMode": "taxable"},
            },
            model_id=GEMINI_35,
            reasoning_level="low",
        )
    )
    assert projection is not None
    assert len(capture.bodies) == 1
    assert capture.bodies[0]["reasoning_effort"] == "low"
    assert capture.bodies[0]["model"] == GEMINI_35
