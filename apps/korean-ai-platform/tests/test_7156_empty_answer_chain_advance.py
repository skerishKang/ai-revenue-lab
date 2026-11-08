"""#7156: an empty provider answer must not end the grade chain.

The 2026-11-08 nightly grade smoke lost the whole Free request with 502
``upstream_empty_answer`` on its **second** of five pinned candidates: the
primary timed out at the completed first-byte bound (by design, a fallback
remained), and the empty answer that followed ended the walk although three
candidates were still untried. #7079's same-route reasoning retry did not
apply (that route sent no reasoning effort and its finish category was not
``length``), so the empty answer reached the walk as a terminal error.

Pinned here:

* an empty answer permits a fallback to the next pinned candidate;
* it still grants **no** same-route retry (#3554 stays intact);
* the walk visits each remaining candidate once and then stops;
* when every candidate answers empty, the bounded 502 is surfaced.

No provider is contacted: the platform adapter is patched directly.
"""
from __future__ import annotations


from app.pilot import router_core
from app.pilot.errors import UpstreamAuthFailed
from app.pilot.tier_fallback import TIER_DEFAULT_B14_MODEL, TIER_FALLBACK_B14_MODELS
from app.pilot.upstream_answer_contract import UpstreamEmptyAnswer

FREE_ROSTER = TIER_FALLBACK_B14_MODELS["free"]

COMPLETED_CHAT_OPTIONS = {"product_tier": "free"}


def _ready(monkeypatch):
    monkeypatch.setattr(
        router_core, "_credential_status_for",
        lambda cm: (True, "present", "platform_secret", cm.platform_provider_id),
    )
    monkeypatch.setattr(router_core, "_platform_secret_present", lambda cm: True)


def _payload(upstream_model):
    return {
        "id": "cmpl-empty-answer-fallback",
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


def test_an_empty_answer_permits_a_fallback_to_the_next_candidate():
    assert router_core.is_error_fallback_allowed("upstream_empty_answer") is True


def test_an_empty_answer_grants_no_same_route_retry():
    """#3554: the code stays non-retryable on the same route."""
    from app.pilot import gateway

    assert "upstream_empty_answer" not in gateway._SAME_ROUTE_RETRYABLE_CODES


def test_a_non_recoverable_failure_still_does_not_advance():
    assert router_core.is_error_fallback_allowed("upstream_auth_failed") is False


def test_the_walk_advances_past_an_empty_answer(client, monkeypatch):
    """Primary answers empty; the next pinned candidate answers."""
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
        if len(calls) == 1:
            raise UpstreamEmptyAnswer("length")
        return _payload(upstream_model)

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
    assert [call["model_id"] for call in calls] == [TIER_DEFAULT_B14_MODEL, FREE_ROSTER[0]]
    business = response.json()["business14"]
    assert business["fallback_used"] is True
    assert business["attempt_count"] == 2
    assert business["attempt_evidence"][0]["error_code"] == "upstream_empty_answer"
    assert business["attempt_evidence"][1]["outcome"] == "success"


def test_every_candidate_answering_empty_ends_with_the_bounded_error(client, monkeypatch):
    """The walk still terminates after the last candidate (no unbounded retry)."""
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
        raise UpstreamEmptyAnswer("stop")

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

    expected = [TIER_DEFAULT_B14_MODEL, *FREE_ROSTER]
    assert [call["model_id"] for call in calls] == expected
    assert len({call["model_id"] for call in calls}) == len(calls)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_empty_answer"
    assert response.json()["error"]["attempt_count"] == len(expected)


def test_the_chain_still_stops_at_the_first_non_recoverable_failure(client, monkeypatch):
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

    assert len(calls) == 1
    assert response.status_code >= 400


