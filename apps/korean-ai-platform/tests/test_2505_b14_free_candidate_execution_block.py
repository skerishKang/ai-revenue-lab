"""#2505: an excluded free candidate never reaches a provider network call.

The owner decision (2026-10-21) keeps an OpenCode Go free model out of the
execution candidates. This slice closes the last common boundary in B14: a
directly supplied model id and a bypassed resolver answer are both refused
before the supplier request, while a paid model, another provider's free
model and the provider adapter itself keep working.

Every outbound call uses a synthetic transport. No provider traffic.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.pilot import opencode_go_wire as go
from app.pilot import platform as plat
from app.pilot import router_core
from app.pilot.b14_runtime_config import runtime_config as rcfg
from app.pilot.errors import NoSafeRoute, PilotNotConfigured
from app.pilot.owner_model_exclusions import free_candidate_excluded_from_execution

FREE_MODEL = "opencode-go/beam-free"
FREE_UPSTREAM = "beam-free"
FREE_MODEL_B = "opencode-go/longcat-2.5-preview-free"
PAID_MODEL = "opencode-go/muse-spark-1.3-contributor"
PAID_UPSTREAM = "muse-spark-1.3-contributor"
SESSION = "chat_0123456789abcdef0123456789abcdef"
TURNS = [{"role": "user", "content": "Say hi."}]


@pytest.fixture()
def live_mode(monkeypatch):
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    saved_mode = rcfg.provider_mode
    rcfg.provider_mode = "live"
    yield
    rcfg.provider_mode = saved_mode


@pytest.fixture()
def ready_route(monkeypatch):
    monkeypatch.setattr(
        router_core, "_credential_status_for",
        lambda cm: (True, "present", "platform_secret", cm.platform_provider_id),
    )
    monkeypatch.setattr(router_core, "_platform_secret_present", lambda cm: True)


@pytest.fixture()
def go_auth_stub(monkeypatch):
    monkeypatch.setattr(go, "_authorization_gate", lambda *_: None)
    # The provider credential is server-owned; a synthetic value keeps the
    # credentialed path testable without any real secret.
    monkeypatch.setenv(
        "PADIEM_B14_CREDENTIAL_11", "synthetic-opencode-go-key-0123456789abcdef"
    )


def _recording_transport(seen: list, *, upstream_model: str = PAID_UPSTREAM):
    def respond(request):
        seen.append(request)
        if upstream_model.startswith("muse-spark"):
            # The paid model uses the provider's responses envelope.
            return httpx.Response(200, json={
                "id": "synthetic",
                "status": "completed",
                "output": [{
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "OK"}],
                }],
            })
        return httpx.Response(200, json={
            "id": "synthetic",
            "model": upstream_model,
            "choices": [{"message": {"role": "assistant", "content": "OK"},
                         "finish_reason": "stop"}],
        })

    return httpx.MockTransport(respond)


@pytest.mark.parametrize("model_id", (FREE_MODEL, FREE_MODEL_B))
def test_the_manual_route_refuses_an_excluded_free_candidate(ready_route, model_id):
    with pytest.raises(NoSafeRoute) as caught:
        router_core.resolve_manual_route(
            model_id, allow_external_fallback=False, product_tier="free",
        )

    assert caught.value.reason_code == "free_candidate_excluded"
    assert caught.value.upstream_called is False


def test_the_manual_route_still_resolves_the_paid_opencode_go_model(ready_route):
    decision = router_core.resolve_manual_route(
        PAID_MODEL, allow_external_fallback=False, product_tier="plus",
    )

    assert decision.selected_model == PAID_MODEL


@pytest.mark.asyncio
async def test_the_last_gate_refuses_the_free_family_before_any_transport(
    live_mode, go_auth_stub
):
    seen: list = []

    with pytest.raises(PilotNotConfigured) as caught:
        await plat.call_platform_chat_completions(
            model_id=FREE_MODEL,
            upstream_model=FREE_UPSTREAM,
            provider="OpenCode Go",
            platform_provider_id="opencode-go",
            messages=TURNS,
            transport=_recording_transport(seen),
        )

    # The free-family refusal is the reason, not a missing credential or an
    # unregistered provider.
    assert "무료" in str(caught.value)
    assert seen == []


@pytest.mark.asyncio
async def test_the_streaming_gate_refuses_the_free_family_before_any_transport(
    live_mode, go_auth_stub
):
    seen: list = []

    with pytest.raises(PilotNotConfigured) as caught:
        async for _event in plat.stream_platform_chat_completions(
            model_id=FREE_MODEL,
            upstream_model=FREE_UPSTREAM,
            provider="OpenCode Go",
            platform_provider_id="opencode-go",
            messages=TURNS,
            transport=_recording_transport(seen),
        ):
            pass

    assert "무료" in str(caught.value)
    assert seen == []


@pytest.mark.asyncio
async def test_a_paid_model_still_reaches_the_provider(live_mode, go_auth_stub):
    seen: list = []

    result = await plat.call_platform_chat_completions(
        model_id=PAID_MODEL,
        upstream_model=PAID_UPSTREAM,
        provider="OpenCode Go",
        platform_provider_id="opencode-go",
        messages=TURNS,
        transport=_recording_transport(seen),
    )

    assert len(seen) == 1
    assert json.loads(seen[0].content)["model"] == PAID_UPSTREAM
    assert result["choices"][0]["message"]["content"] == "OK"


@pytest.mark.asyncio
async def test_a_benign_public_id_cannot_disguise_an_excluded_free_upstream(
    live_mode, go_auth_stub
):
    """A paid public id with the provider's free upstream is still refused."""
    seen: list = []

    with pytest.raises(PilotNotConfigured) as caught:
        await plat.call_platform_chat_completions(
            model_id=PAID_MODEL,
            upstream_model=FREE_UPSTREAM,
            provider="OpenCode Go",
            platform_provider_id="opencode-go",
            messages=TURNS,
            transport=_recording_transport(seen),
        )

    assert "무료" in str(caught.value)
    assert seen == []


def test_another_providers_free_model_keeps_its_own_status():
    """Only the excluded provider's free family is refused by this rule."""
    assert free_candidate_excluded_from_execution(FREE_MODEL) is True
    assert free_candidate_excluded_from_execution(PAID_MODEL) is False
    assert free_candidate_excluded_from_execution("tokenharbor/deepseek-v4.1-flash:free") is False
    assert free_candidate_excluded_from_execution("kira/qwen3.8-flash-free") is False
    assert free_candidate_excluded_from_execution("google/gemini-3.1-flash-lite") is False
    # Another provider's free upstream name is never this rule's business.
    assert free_candidate_excluded_from_execution(
        "tokenharbor/deepseek-v4.1-flash:free",
        upstream_model="deepseek-v4.1-flash:free",
        platform_provider_id="tokenharbor",
    ) is False


@pytest.mark.asyncio
async def test_the_provider_adapter_itself_is_untouched(go_auth_stub):
    """The provider wire is below the policy gate, so it still serves the model.

    The OpenCode coding-agent tooling uses the provider adapter directly; the
    customer execution path is the gate above it.
    """
    seen: list = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={
            "id": "synthetic",
            "model": FREE_UPSTREAM,
            "choices": [{"message": {"role": "assistant", "content": "OK"},
                         "finish_reason": "stop"}],
        })

    result = await go.call_go_model(
        model_id=FREE_MODEL,
        upstream_model=FREE_UPSTREAM,
        messages=TURNS,
        session_id=SESSION,
        max_tokens=32,
        transport=httpx.MockTransport(respond),
    )

    assert len(seen) == 1
    assert result["choices"][0]["message"]["content"] == "OK"
