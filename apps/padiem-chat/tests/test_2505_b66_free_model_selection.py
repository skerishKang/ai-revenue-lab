"""#2505: the B66 customer model selection never offers or runs a free candidate.

The owner decision (2026-10-21) keeps an OpenCode Go free model out of the
execution candidates. B66 keeps its own per-grade assignment, so this slice
only refuses the free family on the customer selection path: the selectable
list, a directly sent exact model id, and the last gate before dispatch.

No provider call, no B14 transport traffic and no database access happens.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from app.b66_b14_free_first_resolver import B14FreeFirstQuoteModelResolver
from app.b66_grade_models import B66_GRADE_MODEL_IDS, b66_grade_model_id
from app.b66_registered_model_boundary import (
    B14AuthorizedModelRoute,
    B66ModelRouteError,
    B66QuoteTaskRequirements,
    B66RegisteredModelCompletion,
    validate_authorized_route,
)

FREE_MODEL = "opencode-go/beam-free"
FREE_MODEL_B = "opencode-go/longcat-2.5-preview-free"
ALLOWED_MODEL = "test-fixture/quote-capable"
ALLOWED_PROVIDER = "test-fixture"


def _registry(*, model_ids=(ALLOWED_MODEL,), provider_id=ALLOWED_PROVIDER):
    return {
        "registered_routes": [
            {
                "id": model_id,
                "provider_id": provider_id,
                "free": model_id.endswith("-free"),
                "owner_excluded": False,
                "capabilities": ["chat", "coding"],
                "explicit_only": True,
                "auto_eligible": False,
            }
            for model_id in model_ids
        ],
        "catalog": [
            {"id": model_id, "provider_id": provider_id, "tags": ["alpha", "chat"]}
            for model_id in model_ids
        ],
    }


def _readiness(*, model_ids=(ALLOWED_MODEL,), provider_id=ALLOWED_PROVIDER):
    return {
        "provider_mode": "live",
        "providers": [
            {
                "provider_id": provider_id,
                "enabled": True,
                "credential_ready": True,
                "route_ready": True,
                "models": list(model_ids),
            }
        ],
    }


class FakeB14ReadOnlyRegistry:
    def __init__(self, models, readiness):
        self.models = models
        self.readiness = readiness
        self.paths: list[str] = []
        self.provider_execution_calls = 0

    async def get_json(self, path):
        self.paths.append(path)
        if path == "/api/pilot/models":
            return 200, json.dumps(self.models).encode("utf-8")
        if path == "/api/pilot/provider-readiness":
            return 200, json.dumps(self.readiness).encode("utf-8")
        raise AssertionError("unknown path")


def _requirements(model_id):
    return replace(B66QuoteTaskRequirements(), selected_model_id=model_id)


@pytest.mark.parametrize("free_model", (FREE_MODEL, FREE_MODEL_B))
def test_the_customer_model_list_never_offers_an_excluded_free_candidate(free_model):
    fake = FakeB14ReadOnlyRegistry(
        _registry(model_ids=(ALLOWED_MODEL, free_model), provider_id="opencode-go"),
        _readiness(model_ids=(ALLOWED_MODEL, free_model), provider_id="opencode-go"),
    )

    listed = asyncio.run(B14FreeFirstQuoteModelResolver(fake).list_selectable_models())

    assert [row["model_id"] for row in listed] == [ALLOWED_MODEL]
    assert free_model not in json.dumps(listed)


@pytest.mark.parametrize("free_model", (FREE_MODEL, FREE_MODEL_B))
def test_a_directly_sent_free_model_id_is_refused_before_any_b14_read(free_model):
    fake = FakeB14ReadOnlyRegistry(
        _registry(model_ids=(free_model,), provider_id="opencode-go"),
        _readiness(model_ids=(free_model,), provider_id="opencode-go"),
    )

    with pytest.raises(B66ModelRouteError) as caught:
        asyncio.run(
            B14FreeFirstQuoteModelResolver(fake).resolve_quote_model(
                _requirements(free_model)
            )
        )

    assert caught.value.code == "model_not_authorized"
    assert free_model not in str(caught.value)
    assert fake.paths == []
    assert fake.provider_execution_calls == 0


def test_the_boundary_refuses_a_free_route_answer():
    selection = B14AuthorizedModelRoute(
        model_id=FREE_MODEL,
        route_id=FREE_MODEL,
        owner_policy_id="owner-approved-b66-policy-v1",
        registered=True,
        enabled=True,
        authorized=True,
        credential_ready=True,
        route_count=1,
        capabilities=frozenset(("chat", "coding")),
    )

    with pytest.raises(B66ModelRouteError) as caught:
        validate_authorized_route(selection, _requirements(FREE_MODEL))

    assert caught.value.code == "model_not_authorized"


class _RecordingResolver:
    def __init__(self, selected=None):
        self.selected = selected
        self.calls: list = []

    async def resolve_quote_model(self, requirements):
        self.calls.append(requirements)
        return self.selected


class _RecordingExecutor:
    def __init__(self):
        self.calls: list = []

    async def execute_quote_text(
        self, *, route, messages, additional_system_context, requirements,
        model_parameters=None,
    ):
        self.calls.append(route)
        return {"answer": "{}", "route": {"mode": "manual", "model": route.model_id}}


def test_the_facade_refuses_a_free_selection_before_any_dispatch():
    resolver = _RecordingResolver()
    executor = _RecordingExecutor()
    refunds: list[bool] = []
    facade = B66RegisteredModelCompletion(
        resolver=resolver,
        executor=executor,
        refund_pre_dispatch=lambda: _record(refunds),
    )

    with pytest.raises(B66ModelRouteError) as caught:
        asyncio.run(facade.complete(
            [{"role": "user", "content": "견적 요청"}],
            additional_system_context=None,
            attachments=(),
            model_id=FREE_MODEL,
        ))

    assert caught.value.code == "model_not_authorized"
    assert resolver.calls == []
    assert executor.calls == []
    assert refunds == [True]


async def _record(refunds):
    refunds.append(True)
    return True


def test_the_last_b66_gate_refuses_a_free_route_before_the_provider_call():
    from app.b66_registered_model_boundary import B14QuoteExactModelExecutor

    class FakeClient:
        def __init__(self):
            self.calls: list = []

        def ensure_registered_quote_runtime_available(self):
            return None

        async def complete_registered_quote_model(self, messages, *, model, **kwargs):
            self.calls.append(model)
            return {"answer": "{}", "route": {"mode": "manual", "model": model}}

    client = FakeClient()
    executor = B14QuoteExactModelExecutor(client)
    selection = B14AuthorizedModelRoute(
        model_id=FREE_MODEL,
        route_id=FREE_MODEL,
        owner_policy_id="owner-approved-b66-policy-v1",
        registered=True,
        enabled=True,
        authorized=True,
        credential_ready=True,
        route_count=1,
        capabilities=frozenset(("chat", "coding")),
    )

    with pytest.raises(B66ModelRouteError) as caught:
        asyncio.run(executor.execute_quote_text(
            route=selection,
            messages=[{"role": "user", "content": "견적 요청"}],
            additional_system_context=None,
            requirements=_requirements(FREE_MODEL),
        ))

    assert caught.value.code == "model_identity_invalid"
    assert client.calls == []


def test_an_allowed_model_still_resolves_and_executes_exactly_once():
    fake = FakeB14ReadOnlyRegistry(_registry(), _readiness())
    resolver = B14FreeFirstQuoteModelResolver(fake)

    selected = asyncio.run(resolver.resolve_quote_model(_requirements(ALLOWED_MODEL)))
    assert selected.model_id == ALLOWED_MODEL

    executor = _RecordingExecutor()
    facade = B66RegisteredModelCompletion(resolver=resolver, executor=executor)
    result = asyncio.run(facade.complete(
        [{"role": "user", "content": "견적 요청"}],
        additional_system_context=None,
        attachments=(),
        model_id=ALLOWED_MODEL,
    ))

    assert result == {"answer": "{}"}
    assert [route.model_id for route in executor.calls] == [ALLOWED_MODEL]


def test_the_b66_grade_assignment_is_unchanged():
    """B66 keeps its own per-grade assignment; only the free family is refused."""
    assert set(B66_GRADE_MODEL_IDS) == {"free", "plus", "pro", "max"}
    assert b66_grade_model_id("free") == B66_GRADE_MODEL_IDS["free"]
    assert b66_grade_model_id("plus") == B66_GRADE_MODEL_IDS["plus"]
    assert b66_grade_model_id("pro") == B66_GRADE_MODEL_IDS["pro"]
    assert b66_grade_model_id("max") == B66_GRADE_MODEL_IDS["max"]
    for model_id in B66_GRADE_MODEL_IDS.values():
        assert not model_id.endswith("-free")
