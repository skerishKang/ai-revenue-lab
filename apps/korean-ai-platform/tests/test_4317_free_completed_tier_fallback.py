"""#4317: the ordinary completed Chat path can reach the owner-pinned Free roster.

The Chat Worker used to pin the upstream attempt count, so a recoverable
provider failure ended the request even though the owner-pinned per-grade
recovery chain was available. The pin was an artificial ceiling, not a safety
boundary.

B14 already owns the whole recovery contract, and this suite pins it:

* the attempt count comes from the candidates the declared product grade
  actually allows, and an explicit caller cap still wins;
* the roster is the owner-pinned per-grade list, in order;
* the walk advances to the next candidate only on a recoverable provider
  error, and it visits each candidate once;
* an arbitrary catalog substitution stays disabled.

No provider is contacted: the platform adapter is patched directly.
"""
from __future__ import annotations

import pytest

from app.pilot import router_core
from app.pilot.errors import UpstreamAuthFailed, UpstreamServerError
from app.pilot.tier_fallback import TIER_DEFAULT_B14_MODEL, TIER_FALLBACK_B14_MODELS

FREE_ROSTER = TIER_FALLBACK_B14_MODELS["free"]

# The exact option set the ordinary completed Chat path sends: the verified
# product grade, no arbitrary catalog fallback, and no attempt pin.
COMPLETED_CHAT_OPTIONS = {
    "product_tier": "free",
    "allow_external_fallback": False,
}


def _ready(monkeypatch):
    monkeypatch.setattr(
        router_core, "_credential_status_for",
        lambda cm: (True, "present", "platform_secret", cm.platform_provider_id),
    )
    monkeypatch.setattr(router_core, "_platform_secret_present", lambda cm: True)


def test_the_completed_chat_option_set_resolves_the_whole_owner_roster(monkeypatch):
    """Without an attempt pin, B14 derives the count from the allowed candidates."""
    _ready(monkeypatch)
    decision = router_core.resolve_route(TIER_DEFAULT_B14_MODEL, dict(COMPLETED_CHAT_OPTIONS))
    assert decision.route_mode == "manual"
    assert decision.selected_model == TIER_DEFAULT_B14_MODEL
    assert decision.fallback_allowed is True
    assert decision.max_attempts == 1 + len(FREE_ROSTER)
    assert [item["model_id"] for item in decision.eligible_fallback] == list(FREE_ROSTER)
    assert "owner_selected_tier_fallback:free" in decision.reason_codes


def test_an_explicit_caller_cap_still_wins(monkeypatch):
    """A lane that must not substitute another model keeps its one-attempt cap."""
    _ready(monkeypatch)
    decision = router_core.resolve_route(
        TIER_DEFAULT_B14_MODEL, dict(COMPLETED_CHAT_OPTIONS, max_attempts=1),
    )
    assert decision.max_attempts == 1
    assert [item["model_id"] for item in decision.eligible_fallback] == list(FREE_ROSTER)


def test_the_owner_roster_never_repeats_a_candidate():
    """A repeated candidate would let the walk loop on the same model."""
    assert len(set(FREE_ROSTER)) == len(FREE_ROSTER)
    assert TIER_DEFAULT_B14_MODEL not in FREE_ROSTER


def test_only_recoverable_provider_errors_advance_to_the_next_candidate():
    assert router_core.is_error_fallback_allowed("upstream_server_error") is True
    assert router_core.is_error_fallback_allowed("upstream_rate_limited") is True
    assert router_core.is_error_fallback_allowed("upstream_timeout") is True
    assert router_core.is_error_fallback_allowed("upstream_auth_failed") is False
    assert router_core.is_error_fallback_allowed("upstream_client_error") is False
    assert router_core.is_error_fallback_allowed("internal_error") is False


def test_the_gateway_walks_the_owner_roster_after_a_recoverable_failure(client, monkeypatch):
    """The primary fails with 5xx; the next roster candidate answers."""
    from app.pilot import b14_runtime_config as rcfg
    from app.pilot import platform as plat

    rcfg.provider_mode = "live"
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_03", "sk-free-google-0123456789abcdef")
    _ready(monkeypatch)

    original = plat.call_platform_chat_completions
    calls: list[dict] = []

    async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages,
                   temperature=0.2, max_tokens=300, transport=None):
        calls.append({"model_id": model_id, "provider": provider})
        if len(calls) == 1:
            raise UpstreamServerError()
        return {
            "id": "cmpl-free-fallback",
            "object": "chat.completion",
            "model": upstream_model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "OK"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
            "_live": True,
            "_requested_upstream_model": upstream_model,
            "_actual_response_model": upstream_model,
        }

    plat.call_platform_chat_completions = fake
    try:
        response = client.post(
            "/api/pilot/v1/chat/completions",
            json={
                "model": TIER_DEFAULT_B14_MODEL,
                "messages": [{"role": "user", "content": "hi"}],
                "business14": dict(COMPLETED_CHAT_OPTIONS),
            },
        )
    finally:
        plat.call_platform_chat_completions = original

    assert response.status_code == 200
    assert len(calls) == 2
    # The primary failed and the next owner-roster candidate answered.
    assert calls[0]["model_id"] == TIER_DEFAULT_B14_MODEL
    assert calls[1]["model_id"] == FREE_ROSTER[0]
    # Each candidate is visited exactly once.
    assert len({call["model_id"] for call in calls}) == len(calls)
    business = response.json()["business14"]
    assert business["fallback_used"] is True
    assert business["attempt_count"] == 2
    assert business["selected_model"] == FREE_ROSTER[0]
    assert business["attempt_evidence"][0]["outcome"] == "error"
    assert business["attempt_evidence"][0]["error_code"] == "upstream_server_error"
    assert business["attempt_evidence"][1]["outcome"] == "success"


def test_the_gateway_does_not_advance_on_a_non_recoverable_failure(client, monkeypatch):
    """An auth failure fails closed instead of trying another model."""
    from app.pilot import b14_runtime_config as rcfg
    from app.pilot import platform as plat

    rcfg.provider_mode = "live"
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_03", "sk-free-google-0123456789abcdef")
    _ready(monkeypatch)

    original = plat.call_platform_chat_completions
    calls: list[dict] = []

    async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages,
                   temperature=0.2, max_tokens=300, transport=None):
        calls.append({"model_id": model_id})
        raise UpstreamAuthFailed()

    plat.call_platform_chat_completions = fake
    try:
        response = client.post(
            "/api/pilot/v1/chat/completions",
            json={
                "model": TIER_DEFAULT_B14_MODEL,
                "messages": [{"role": "user", "content": "hi"}],
                "business14": dict(COMPLETED_CHAT_OPTIONS),
            },
        )
    finally:
        plat.call_platform_chat_completions = original

    assert response.status_code >= 400
    # Exactly one provider call: no substitution on a non-recoverable error.
    assert len(calls) == 1
    assert calls[0]["model_id"] == TIER_DEFAULT_B14_MODEL
