"""#7389 — upstream 401/403/404/429 before the first byte advance the chain.

One candidate that cannot serve (bad registry row, expired key, quota or a
transient bus|限) must not take down the whole grade chain. Request-content
rejections (400/409/413/422) and anything after the first answer byte stay
terminal. The user-visible error code mapping is unchanged.
"""
from __future__ import annotations

import pytest

from app.pilot import b14_runtime_config as rcfg
from app.pilot import gateway as gw
from app.pilot import platform as plat
from app.pilot import router_core
from app.pilot.call_ledger import LedgerDraft
from app.pilot.errors import (
    UpstreamAuthFailed,
    UpstreamClientError,
    UpstreamRateLimited,
)
from app.pilot.tier_fallback import effective_tier_default, effective_tier_fallback

from _pilot_lane_paths import chat_surface
from _registry_values import provider_of, provider_row

CHAT_PATH = chat_surface()
FREE_PRIMARY = effective_tier_default()
FREE_ROSTER = tuple(effective_tier_fallback()["free"])
OPTIONS = {"product_tier": "free"}


def _primary_binding() -> str:
    return provider_row(provider_of(FREE_PRIMARY))["credential_binding_name"]


def _ready(monkeypatch) -> None:
    monkeypatch.setattr(
        router_core, "_credential_status_for",
        lambda cm: (True, "present", "platform_secret", cm.platform_provider_id),
    )
    monkeypatch.setattr(router_core, "_platform_secret_present", lambda cm: True)


def _setup(monkeypatch) -> None:
    rcfg.provider_mode = "live"
    monkeypatch.setenv(_primary_binding(), "sk-free-primary-0123456789abcdef")
    _ready(monkeypatch)


def _ok(upstream_model: str) -> dict:
    return {
        "id": "cmpl-7389",
        "object": "chat.completion",
        "model": upstream_model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "OK"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        "_live": True,
        "_requested_upstream_model": upstream_model,
        "_actual_response_model": upstream_model,
    }


def _post(client):
    return client.post(
        CHAT_PATH,
        json={
            "model": FREE_PRIMARY,
            "messages": [{"role": "user", "content": "hi"}],
            "business14": dict(OPTIONS),
        },
    )


def test_the_fallback_policy_matrix():
    allowed = [
        ("upstream_timeout", None),
        ("upstream_server_error", None),
        ("upstream_rate_limited", None),
        ("upstream_rate_limited_busy", None),
        ("kilo_free_rate_limited", None),
        ("upstream_auth_failed", None),
        ("upstream_client_error", "upstream_http_401"),
        ("upstream_client_error", "upstream_http_403"),
        ("upstream_client_error", "upstream_http_404"),
        ("upstream_client_error", "upstream_http_429"),
    ]
    blocked = [
        # A bare client error carries no status: fail closed.
        ("upstream_client_error", None),
        ("upstream_client_error", "upstream_http_400"),
        ("upstream_client_error", "upstream_http_409"),
        ("upstream_client_error", "upstream_http_413"),
        ("upstream_client_error", "upstream_http_422"),
        ("malformed_upstream_response", "upstream_http_400"),
        ("malformed_upstream_response", "unexpected_http_status"),
        ("internal_error", None),
        ("unknown_future_code", None),
    ]
    for code, reason in allowed:
        assert router_core.is_error_fallback_allowed(code, reason=reason) is True, (code, reason)
    for code, reason in blocked:
        assert router_core.is_error_fallback_allowed(code, reason=reason) is False, (code, reason)


@pytest.mark.parametrize("failure", [
    UpstreamAuthFailed(),
    UpstreamClientError(404),
    UpstreamRateLimited(),
])
def test_a_candidate_level_rejection_advances_and_is_recorded_per_attempt(
    client, monkeypatch, failure,
):
    _setup(monkeypatch)
    calls: list[str] = []
    attempts: list[dict] = []

    async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages,
                   temperature=0.2, max_tokens=300, transport=None):
        calls.append(model_id)
        if len(calls) == 1:
            raise failure
        return _ok(upstream_model)

    original_record = LedgerDraft.record_attempt

    def capture(self, **kwargs):
        attempts.append(dict(kwargs))
        return original_record(self, **kwargs)

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake)
    monkeypatch.setattr(LedgerDraft, "record_attempt", capture)
    response = _post(client)

    assert response.status_code == 200, response.text
    assert calls == [FREE_PRIMARY, FREE_ROSTER[0]]
    business = response.json()["business14"]
    assert business["fallback_used"] is True
    assert business["attempt_count"] == 2
    assert business["attempt_evidence"][0]["error_code"] == failure.code
    assert business["attempt_evidence"][1]["outcome"] == "success"
    # The ledger keeps one row per physical attempt: the failed candidate and
    # the one that answered.
    assert [row["outcome"] for row in attempts] == ["error", "success"]
    assert attempts[0]["error_code"] == failure.code


def test_the_last_candidate_keeps_the_final_error_code(client, monkeypatch):
    """Every candidate 404s: the walk ends and the 502 code mapping is unchanged."""
    _setup(monkeypatch)
    calls: list[str] = []

    async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages,
                   temperature=0.2, max_tokens=300, transport=None):
        calls.append(model_id)
        raise UpstreamClientError(404)

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake)
    response = _post(client)

    # Each candidate is visited once; a 404 grants no same-route retry.
    assert calls == [FREE_PRIMARY, *FREE_ROSTER]
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "upstream_client_error"
    assert body["error"]["attempt_count"] == len(calls)


def test_a_request_content_rejection_still_stops_at_the_first_candidate(client, monkeypatch):
    _setup(monkeypatch)
    calls: list[str] = []

    async def fake(*, model_id, upstream_model, provider, platform_provider_id, messages,
                   temperature=0.2, max_tokens=300, transport=None):
        calls.append(model_id)
        raise UpstreamClientError(422)

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake)
    response = _post(client)

    assert calls == [FREE_PRIMARY]
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_client_error"
