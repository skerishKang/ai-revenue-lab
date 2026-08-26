from __future__ import annotations

import json

import httpx
import pytest

from app.pilot.catalog import (
    CATALOG_MODELS,
    CatalogModel,
    ensure_free_tag_requires_known_zero_price,
    filter_catalog,
    get_catalog_by_id,
)
from app.pilot.errors import NoSafeRoute
from app.pilot.openrouter import call_openrouter_chat_completions
from app.pilot.openrouter_config import openrouter_config
from app.pilot.router_core import resolve_auto_route


@pytest.fixture(autouse=True)
def _restore_openrouter_config():
    saved_key = openrouter_config.api_key
    saved_mode = openrouter_config.provider_mode
    saved_url = openrouter_config.base_url
    yield
    openrouter_config.api_key = saved_key
    openrouter_config.provider_mode = saved_mode
    openrouter_config.base_url = saved_url


def test_ox_alpha_catalog_snapshot_is_approved_free_multimodal_route():
    model = get_catalog_by_id("stealth/ox-alpha")
    assert model is not None
    assert model.upstream_model == "stealth/ox-alpha"
    assert model.provider == "Stealth"
    assert model.enabled is True
    assert model.input_price_usd_per_1m == 0.0
    assert model.output_price_usd_per_1m == 0.0
    assert model.context_window == 1_048_576
    assert {"chat", "image", "long_context", "coding", "free"}.issubset(model.capabilities)
    assert "video" not in model.capabilities


def test_only_known_zero_price_models_are_tagged_free_and_paid_catalog_is_preserved():
    free_models = [model for model in CATALOG_MODELS if "free" in model.capabilities]
    assert {model.model_id for model in free_models} == {"stealth/ox-alpha", "openrouter/free"}
    for model in free_models:
        assert model.price_is_known is True
        assert model.input_price_usd_per_1m == 0.0
        assert model.output_price_usd_per_1m == 0.0

    paid_models = [model for model in CATALOG_MODELS if model.model_id not in {"stealth/ox-alpha", "openrouter/free"}]
    assert paid_models
    assert all(model.enabled for model in paid_models)
    assert all("free" not in model.capabilities for model in paid_models)


def test_general_free_route_prefers_ox_and_fallback_never_contains_paid_model():
    decision = resolve_auto_route(
        task_type="general",
        required_capabilities=["free"],
        optimize_for="korean",
        allow_external_fallback=True,
        max_attempts=3,
    )
    assert decision.selected_model == "stealth/ox-alpha"
    assert [item["model_id"] for item in decision.eligible_fallback] == ["openrouter/free"]
    assert decision.max_attempts == 3
    assert all(
        "free" in get_catalog_by_id(item["model_id"]).capabilities
        for item in decision.eligible_fallback
    )


@pytest.mark.parametrize(
    ("task_type", "required"),
    [
        ("general", ["free", "image"]),
        ("coding", ["free"]),
        ("document", ["free"]),
    ],
)
def test_specialized_free_routes_never_widen_to_paid_models(task_type, required):
    decision = resolve_auto_route(
        task_type=task_type,
        required_capabilities=required,
        optimize_for="balanced",
        allow_external_fallback=True,
        max_attempts=3,
    )
    assert decision.selected_model == "stealth/ox-alpha"
    assert decision.eligible_fallback == []
    assert decision.max_attempts == 3


def test_no_matching_free_route_fails_before_upstream():
    with pytest.raises(NoSafeRoute) as info:
        resolve_auto_route(
            task_type="general",
            required_capabilities=["free", "video"],
            optimize_for="balanced",
        )
    assert info.value.reason_code == "no_candidate_meets_capabilities"
    assert info.value.upstream_called is False


def test_openrouter_free_router_capability_is_conservative_chat_only():
    model = get_catalog_by_id("openrouter/free")
    assert model is not None
    assert model.enabled is True
    assert "free" in model.capabilities
    assert model.capabilities == frozenset({"chat", "free"})
    assert "image" not in model.capabilities
    assert "coding" not in model.capabilities
    assert "long_context" not in model.capabilities


@pytest.mark.asyncio
async def test_ox_alpha_free_route_adds_zero_price_ceiling_and_no_model_specific_hint():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "resp_free",
                "model": "stealth/ox-alpha",
                "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    openrouter_config.provider_mode = "live"
    openrouter_config.api_key = "sk-or-v1-b62-free-route-credential-92837465"
    await call_openrouter_chat_completions(
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.2,
        max_tokens=700,
        model_id="stealth/ox-alpha",
        upstream_model="stealth/ox-alpha",
        provider="Stealth",
        transport=httpx.MockTransport(handler),
    )

    assert seen["body"]["model"] == "stealth/ox-alpha"
    assert seen["body"]["provider"] == {
        "max_price": {"prompt": 0, "completion": 0}
    }
    assert "reasoning" not in seen["body"]
    assert "reasoning_effort" not in seen["body"]


@pytest.mark.asyncio
async def test_other_routes_do_not_receive_ox_reasoning_profile():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.path] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "resp_other",
                "model": "openrouter/free",
                "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    openrouter_config.provider_mode = "live"
    openrouter_config.api_key = "sk-or-v1-b62-other-route-credential-48392017"
    await call_openrouter_chat_completions(
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.2,
        max_tokens=700,
        model_id="openrouter/free",
        upstream_model="openrouter/free",
        provider="OpenRouter (free router)",
        transport=httpx.MockTransport(handler),
    )

    body = seen["/api/v1/chat/completions"]
    assert body["provider"] == {"max_price": {"prompt": 0, "completion": 0}}
    assert "reasoning" not in body


@pytest.mark.asyncio
async def test_paid_catalog_route_does_not_receive_free_price_ceiling_or_ox_reasoning():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "resp_paid",
                "model": "google/gemini-2.5-flash",
                "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    openrouter_config.provider_mode = "live"
    openrouter_config.api_key = "sk-or-v1-b14-paid-route-credential-57483921"
    await call_openrouter_chat_completions(
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.2,
        max_tokens=32,
        model_id="google/gemini-2.5-flash",
        upstream_model="google/gemini-2.5-flash",
        provider="Google",
        transport=httpx.MockTransport(handler),
    )

    assert seen["body"]["model"] == "google/gemini-2.5-flash"
    assert "provider" not in seen["body"]
    assert "reasoning" not in seen["body"]


def test_unknown_price_model_is_never_implicitly_classified_free():
    unknown_price = CatalogModel(
        model_id="mystery/unknown-price",
        upstream_model="mystery/unknown-price",
        display_name="Unknown Price Model",
        provider="Mystery",
        provider_type="external",
        input_price_usd_per_1m=None,
        output_price_usd_per_1m=None,
        capabilities=frozenset({"chat", "free"}),
    )
    assert unknown_price.price_is_known is False
    with pytest.raises(RuntimeError):
        ensure_free_tag_requires_known_zero_price(unknown_price)

    nonzero = CatalogModel(
        model_id="mystery/nonzero",
        upstream_model="mystery/nonzero",
        display_name="Nonzero Price Model",
        provider="Mystery",
        provider_type="external",
        input_price_usd_per_1m=1.0,
        output_price_usd_per_1m=2.0,
        capabilities=frozenset({"chat", "free"}),
    )
    with pytest.raises(RuntimeError):
        ensure_free_tag_requires_known_zero_price(nonzero)


def test_required_capability_free_excludes_every_paid_entry():
    candidates = filter_catalog(required_capabilities=["free"])
    candidate_ids = {m.model_id for m in candidates}
    assert candidate_ids == {"stealth/ox-alpha", "openrouter/free"}

    paid_entries = [m for m in CATALOG_MODELS if "free" not in m.capabilities]
    assert paid_entries
    excluded_ids = {m.model_id for m in paid_entries}
    assert {
        "google/gemini-2.5-flash",
        "deepseek/deepseek-chat",
        "mistralai/mistral-small-3.2-24b-instruct",
        "anthropic/claude-sonnet-4.5",
    }.issubset(excluded_ids)
    assert candidate_ids.isdisjoint(excluded_ids)
    for m in candidates:
        assert m.price_is_known is True
        assert m.input_price_usd_per_1m == 0.0
        assert m.output_price_usd_per_1m == 0.0
        assert "free" in m.capabilities
