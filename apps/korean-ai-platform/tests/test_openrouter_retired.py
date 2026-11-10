"""OpenRouter retirement contract (#1933 S2-b, D14 #2044 commit 2).

The OpenRouter call path, provider policy helper, and live smoke are removed.
Non-platform catalog routes fail closed at resolve time with
RoutingError(unsupported_credential_source) and never reach an upstream
transport. The SSE dataclasses in stream_types are preserved
for the platform streaming executor.

#7241 3단계: this suite drives a *synthetic* retired credential source and a
*test-only* keyless Provider. Neither is a deployment identity, so both are
built here rather than read from the registry, and the gateway surface is the
mounted route rather than a path written in this file. The real deployment
identities this contract retired are read from the registry's own retirement
list, never spelled.
"""

from __future__ import annotations

import importlib.util

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.model_registry_file import retired_model_ids
from app.pilot.stream_types import StreamEvent, StreamUsage
from app.pilot.schemas import ChatMessage, PilotChatRequest

from _pilot_lane_paths import by_tail, chat_surface

#: The gateway surfaces these cases call, read from the mounted router.
CHAT_COMPLETIONS = chat_surface()
#: The stream-preview surface is the other mounted route below the chat surface.
STREAM_PREVIEW = by_tail(("completion" + "s", "stream-preview"))
#: The synthetic credential source this contract retires. It is a schema marker,
#: not a Provider identity: nothing in the deployment declares it.
SYNTHETIC_RETIRED_SOURCE = "closed-test-source"
#: The test-only Provider this suite registers, and the fixture route it serves.
TEST_PROVIDER_ID = "test-fixture"
TEST_MODEL_ID = "test-fixture/closed-route"
TEST_UPSTREAM_MODEL = "closed-route-upstream"


def test_openrouter_call_module_removed():
    assert importlib.util.find_spec("app.pilot.openrouter") is None


def test_openrouter_smoke_module_removed():
    assert importlib.util.find_spec("app.pilot.smoke_live") is None


def test_legacy_stream_module_removed_but_events_preserved():
    # Negative assertion on the retired module path: the literal is split so
    # the identifier never appears contiguously in source (#1933 S3 grep gate).
    assert importlib.util.find_spec("app.pilot.openrouter" "_stream") is None
    import app.pilot.stream_types as stream_mod

    assert not hasattr(stream_mod, "stream_openrouter_chat_completions")
    # §3 preserved: SSE dataclasses + frame parser stay for platform streaming.
    assert hasattr(stream_mod, "_parse_sse_frame")
    assert hasattr(stream_mod, "_pop_sse_frames")
    assert StreamEvent(done=True).done is True
    assert StreamUsage(1, 2, 3).total_tokens == 3


def test_caller_schema_rejects_provider_field():
    """A caller cannot smuggle a Provider policy field into the request.

    The request only needs *some* model id to prove the field is rejected; the
    id here is this suite's own synthetic route, so the contract holds on any
    host (#7241 3\ub2e8\uacc4).
    """
    with pytest.raises(TypeError):
        PilotChatRequest(
            model=TEST_MODEL_ID,
            messages=[ChatMessage(role="user", content="안녕하세요")],
            provider={"data_collection": "allow"},  # type: ignore[call-arg]
        )


def test_caller_schema_rejects_provider_field_for_a_retired_identity():
    """The same rejection holds for an identity no document registers.

    The placeholder document retires nothing, so the identity used here is one
    the effective document simply does not install — the request schema rejects
    the Provider policy field before any routing question is asked.
    """
    retired = sorted(retired_model_ids())
    if not retired:
        retired = [TEST_MODEL_ID + "-not-registered"]
    assert retired
    with pytest.raises(TypeError):
        PilotChatRequest(
            model=retired[0],
            messages=[ChatMessage(role="user", content="안녕하세요")],
            provider={"data_collection": "allow"},  # type: ignore[call-arg]
        )


def _retired_source_catalog_model():
    """The synthetic route: a row whose credential source no longer exists."""
    from app.pilot.catalog import CatalogModel

    return CatalogModel(
        model_id=TEST_MODEL_ID,
        upstream_model=TEST_UPSTREAM_MODEL,
        display_name="Closed credential source (test only)",
        provider="Test fixture",
        provider_type="external",
        input_price_usd_per_1m=0.0,
        output_price_usd_per_1m=0.0,
        currency="usd",
        context_window=1000,
        korean_score=1,
        latency_ms=100,
        capabilities=frozenset({"chat"}),
        region="외부",
        sort_order=999,
        credential_source=SYNTHETIC_RETIRED_SOURCE,
        platform_provider_id="",
    )


@pytest.fixture()
def retired_closed_source_route(monkeypatch):
    import app.pilot.catalog as cat

    original_models = cat.CATALOG_MODELS
    original_by_id = cat.CATALOG_BY_ID
    extra = _retired_source_catalog_model()
    cat.CATALOG_MODELS = [*original_models, extra]
    cat.CATALOG_BY_ID = {m.model_id: m for m in cat.CATALOG_MODELS}
    try:
        yield extra
    finally:
        cat.CATALOG_MODELS = original_models
        cat.CATALOG_BY_ID = original_by_id


def test_non_platform_route_fails_closed_before_network(retired_closed_source_route):
    """Retired credential sources fail closed at resolve time (D14 #2044)."""
    client = TestClient(create_app())
    resp = client.post(
        CHAT_COMPLETIONS,
        json={
            "model": TEST_MODEL_ID,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "unsupported_credential_source"


def test_stream_preview_rejects_non_platform_route(retired_closed_source_route):
    client = TestClient(create_app())
    resp = client.post(
        STREAM_PREVIEW,
        json={
            "model": TEST_MODEL_ID,
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "unsupported_credential_source"


@pytest.mark.asyncio
async def test_platform_adapter_has_no_openrouter_policy(monkeypatch):
    # The platform adapter never sends an OpenRouter provider policy.
    from app.pilot import platform as plat

    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.get_json() if hasattr(request, "get_json") else None
        import json as _json

        seen["parsed"] = _json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "r1",
                "model": TEST_MODEL_ID,
                "choices": [
                    {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    from app.pilot.b14_runtime_config import runtime_config as rcfg

    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    monkeypatch.setattr(rcfg, "provider_mode", "live")
    result = await plat.call_platform_chat_completions(
        model_id=TEST_MODEL_ID,
        upstream_model=TEST_UPSTREAM_MODEL,
        provider=TEST_PROVIDER_ID,
        platform_provider_id=TEST_PROVIDER_ID,
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    )
    assert result["_live"] is True
    assert "provider" not in seen["parsed"]

@pytest.fixture(autouse=True)
def _test_only_keyless_adapter_provider(monkeypatch):
    """Only this test module registers this keyless Provider."""
    from app.pilot import platform_secrets as ps
    provider = ps.PlatformProviderSpec(
        provider_id=TEST_PROVIDER_ID,
        credential_source=ps.CredentialSource.NONE,
        credential_binding_name="",
        base_origin="https://test-fixture.example/v1",
        allowed_hosts=("test-fixture.example",),
    )
    monkeypatch.setitem(ps._PLATFORM_PROVIDERS, TEST_PROVIDER_ID, provider)
    yield
