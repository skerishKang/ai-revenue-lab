"""#3906 — the selected level reaches the ACTUAL B14 request body (B66 stack).

The B66 quote path never streams, so the acceptance evidence is the completed
call's real POST body, captured from the transport the product actually installs:

* the Cloudflare Service-Binding transport (``require_service_binding=True``),
  which is what the deployed Worker uses, and
* the direct HTTP transport, used by non-binding deployments.

Both are read here as bytes on the wire, not as a renderer self-report. The
dispatch-aware client is the LAST hop before the POST, so it must forward the
level exactly like the base client; a dropped keyword would otherwise reject the
user's explicit choice only in Production, where that subclass is installed.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.b66_registered_model_boundary import (
    B14QuoteExactModelExecutor,
    B66ModelRouteError,
    B66RegisteredModelCompletion,
)
from app.b66_reasoning_level import (
    DEFAULT_REASONING_LEVEL,
    VERIFIED_REASONING_EFFORT,
)
from app.config import Settings
from app.dispatch_quota import DispatchAwareB14Client
from test_b66_registered_model_boundary import FakeTrustedResolver, approved_route

MESSAGES = [{"role": "user", "content": "synthetic quotation"}]
UNVERIFIED_MODEL = "test-owner-catalog/quote-capable"

# Every verified (model, level) pair, plus what each model must refuse.
VERIFIED_PAIRS = [
    (model_id, level)
    for model_id, levels in VERIFIED_REASONING_EFFORT.items()
    for level in levels
]
ALL_VOCABULARY = sorted({level for _, level in VERIFIED_PAIRS})


def settings(**overrides):
    values = dict(
        runtime_mode="b14", b14_base_url="https://b14.internal", live_enabled=True
    )
    values.update(overrides)
    return Settings(**values)


def _completion_response(model_id: str) -> bytes:
    return json.dumps(
        {
            "choices": [{"message": {"role": "assistant", "content": "{}"}}],
            "business14": {"route_mode": "manual", "selected_model": model_id},
        }
    ).encode()


class Binding:
    """Service-Binding transport double: records the exact payload it is handed."""

    def __init__(self, model_id: str):
        self.calls: list[tuple[str, dict]] = []
        self.model_id = model_id

    async def post_json(self, url, payload):
        self.calls.append((url, payload))
        return 200, _completion_response(self.model_id)


def _dispatch_aware(*, model_id: str, binding: Binding | None):
    transport = binding if binding is not None else None
    return DispatchAwareB14Client(
        settings(),
        service_transport=transport,
        require_service_binding=binding is not None,
    )


async def _quote_call(client, *, model_id: str, level: str | None) -> None:
    await client.complete_registered_quote_model(
        MESSAGES,
        model=model_id,
        additional_system_context=None,
        reasoning_effort=level,
    )


# --------------------------------------------------------------------------
# 1. The Production (Service Binding) transport carries the level, top level.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(("model_id", "level"), VERIFIED_PAIRS)
def test_dispatch_aware_binding_posts_the_exact_level_for_each_verified_pair(
    model_id, level
):
    binding = Binding(model_id)
    asyncio.run(
        _quote_call(
            _dispatch_aware(model_id=model_id, binding=binding),
            model_id=model_id,
            level=level,
        )
    )
    assert len(binding.calls) == 1, "exactly one provider dispatch, never a retry"
    payload = binding.calls[0][1]
    # Top-level provider-native field, matching the B14 gateway allow-list.
    assert payload["reasoning_effort"] == level
    # It is a provider parameter, never smuggled through the B14 routing block.
    assert "reasoning_effort" not in payload["business14"]
    # The exact model the user picked is preserved.
    assert payload["model"] == model_id


def test_no_level_selected_produces_the_exact_pre_3906_request_shape():
    """Nothing selected must not change the request at all.

    The omitted level and the ``default`` sentinel both reach the provider with
    no ``reasoning_effort`` key, so the served provider keeps its own documented
    default and the body is byte-identical to the pre-#3906 shape.
    """
    model_id = "google/gemini-3.1-flash-lite"
    binding = Binding(model_id)
    facade = B66RegisteredModelCompletion(
        resolver=FakeTrustedResolver(approved_route(model_id=model_id)),
        executor=B14QuoteExactModelExecutor(_dispatch_aware(model_id=model_id, binding=binding)),
    )
    # Omitted keyword (legacy caller) and the explicit sentinel, same request.
    asyncio.run(facade.complete([dict(MESSAGES[0])], model_id=model_id))
    asyncio.run(
        facade.complete(
            [dict(MESSAGES[0])], model_id=model_id, reasoning_level=DEFAULT_REASONING_LEVEL
        )
    )
    assert len(binding.calls) == 2
    omitted, sentinel = (call[1] for call in binding.calls)
    assert "reasoning_effort" not in omitted
    assert "reasoning_effort" not in sentinel
    assert omitted == sentinel
    # The sentinel is B66 vocabulary only: it is never sent to B14 as a value.
    assert DEFAULT_REASONING_LEVEL not in json.dumps(omitted)
    assert "reasoning_effort" not in json.dumps(omitted)


def test_direct_http_quote_transport_carries_the_same_level():
    """The non-binding transport must agree with the Service-Binding one."""
    seen: list[dict] = []

    async def transport(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=_completion_response("google/gemini-3.5-flash-lite"))

    client = DispatchAwareB14Client(settings(), transport=httpx.MockTransport(transport))
    asyncio.run(
        _quote_call(client, model_id="google/gemini-3.5-flash-lite", level="medium")
    )
    assert len(seen) == 1
    assert seen[0]["reasoning_effort"] == "medium"
    assert seen[0]["model"] == "google/gemini-3.5-flash-lite"


# --------------------------------------------------------------------------
# 2. Fail closed BEFORE dispatch: no provider call, no substitution.
# --------------------------------------------------------------------------

def _facade(model_id: str, binding: Binding) -> B66RegisteredModelCompletion:
    return B66RegisteredModelCompletion(
        resolver=FakeTrustedResolver(approved_route(model_id=model_id)),
        executor=B14QuoteExactModelExecutor(_dispatch_aware(model_id=model_id, binding=binding)),
    )


@pytest.mark.parametrize("model_id", sorted(VERIFIED_REASONING_EFFORT))
def test_a_verified_model_refuses_every_level_it_does_not_offer(model_id):
    """Vocabulary membership is not a capability promise.

    Each verified model is offered only its own attested levels; any other
    well-formed level is refused with an explainable error and zero dispatches.
    """
    unsupported = [
        level for level in ALL_VOCABULARY if level not in VERIFIED_REASONING_EFFORT[model_id]
    ]
    for level in unsupported:
        binding = Binding(model_id)
        facade = _facade(model_id, binding)
        with pytest.raises(B66ModelRouteError, match="model_capability_unavailable"):
            asyncio.run(
                facade.complete([dict(MESSAGES[0])], model_id=model_id, reasoning_level=level)
            )
        assert binding.calls == [], f"{model_id} must not dispatch for {level!r}"


def test_the_vocabulary_union_is_fully_exercised_as_unsupported_somewhere():
    """Guard against a vacuous capability test.

    Every word in the vocabulary must be refused by at least one served model,
    so the per-model refusal test above can never silently become a no-op.
    """
    served = set().union(*VERIFIED_REASONING_EFFORT.values())
    union_of_offered_per_model = [
        {level for level in ALL_VOCABULARY if level in levels}
        for levels in VERIFIED_REASONING_EFFORT.values()
    ]
    assert served == set(ALL_VOCABULARY)
    assert any(len(offered) < len(ALL_VOCABULARY) for offered in union_of_offered_per_model)


@pytest.mark.parametrize("level", ["minimal", "low", "medium", "high", "xhigh", "ultra"])
def test_unverified_registered_model_never_dispatches_an_explicit_level(level):
    binding = Binding(UNVERIFIED_MODEL)
    facade = _facade(UNVERIFIED_MODEL, binding)
    with pytest.raises(B66ModelRouteError, match="model_capability_unavailable"):
        asyncio.run(
            facade.complete([dict(MESSAGES[0])], model_id=UNVERIFIED_MODEL, reasoning_level=level)
        )
    assert binding.calls == []


def test_unverified_model_still_posts_its_default_without_a_reasoning_key():
    """A model with no attested reasoning capability keeps working, unchanged."""
    binding = Binding(UNVERIFIED_MODEL)
    facade = _facade(UNVERIFIED_MODEL, binding)
    asyncio.run(
        facade.complete(
            [dict(MESSAGES[0])], model_id=UNVERIFIED_MODEL, reasoning_level=DEFAULT_REASONING_LEVEL
        )
    )
    assert len(binding.calls) == 1
    payload = binding.calls[0][1]
    assert payload["model"] == UNVERIFIED_MODEL
    assert "reasoning_effort" not in payload


@pytest.mark.parametrize("level", ["xhigh", "none", "ultra", "default"])
def test_a_level_outside_the_verified_vocabulary_is_refused_twice_independently(level):
    """Defense in depth on the wire even if a caller skips the B66 boundary.

    The B14 gateway allow-list and the Core request contract reject anything
    outside the documented vocabulary, so an invented level can never be
    transmitted even by a direct, unvalidated caller.
    """
    binding = Binding("google/gemini-3.1-flash-lite")
    client = _dispatch_aware(model_id="google/gemini-3.1-flash-lite", binding=binding)
    with pytest.raises(Exception) as caught:
        asyncio.run(
            _quote_call(client, model_id="google/gemini-3.1-flash-lite", level=level)
        )
    assert type(caught.value).__name__ == "ChatRuntimeError"
    assert getattr(caught.value, "code", None) == "invalid_request"
    assert binding.calls == []


# --------------------------------------------------------------------------
# 3. The full B66 facade -> exact executor -> B14 POST chain.
# --------------------------------------------------------------------------

def test_facade_posts_the_selected_level_and_preserves_the_exact_model():
    model_id = "google/gemini-3.1-flash-lite"
    binding = Binding(model_id)
    facade = _facade(model_id, binding)
    result = asyncio.run(
        facade.complete([dict(MESSAGES[0])], model_id=model_id, reasoning_level="high")
    )
    assert result == {"answer": "{}"}
    payload = binding.calls[0][1]
    assert payload["model"] == model_id
    assert payload["reasoning_effort"] == "high"
    # The bounded quote task budget is untouched by the new keyword.
    assert payload["business14"]["max_attempts"] == 1
    assert payload["business14"]["max_retries"] == 0
    assert payload["business14"]["allow_external_fallback"] is False


def test_facade_without_a_level_matches_the_previous_request_shape():
    model_id = "google/gemini-3.1-flash-lite"
    binding = Binding(model_id)
    facade = _facade(model_id, binding)
    asyncio.run(facade.complete([dict(MESSAGES[0])], model_id=model_id))
    payload = binding.calls[0][1]
    assert set(payload) == {"model", "messages", "temperature", "business14"}
    assert payload["model"] == model_id
