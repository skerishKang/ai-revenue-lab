"""thought-summary stream: B14 asks for thinking summaries and separates them.

The Owner's per-model switch (inside the reasoning block) decides whether a
model's stream is asked to include thinking summaries. A summary fragment
rides its own delta field end to end — provider delta, StreamEvent, wire —
so the answer body stays clean. A thought fragment is a first byte: the
first-byte timeout must not fire while the model is still thinking. The
ledger stores whether summaries arrived (fragment count, character length)
and never the thought text itself.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.pilot import catalog as cat
from app.pilot import platform as plat
from app.pilot import reasoning_policy as policy
from app.pilot.call_ledger import CallLedgerError, LedgerDraft, new_log_id, utc_now_iso
from app.pilot.model_registry_file import ModelRegistryError, install_models
from app.pilot.router_core import RouteDecision
from app.pilot.stream_gateway import _encode_event, _stream_body
from app.pilot.stream_types import _parse_sse_frame, StreamEvent
from app.pilot.errors import MalformedUpstreamResponse

MODEL_ID = "test-model"
UPSTREAM_MODEL = "test-upstream"
PROVIDER_ID = "test-route"

THOUGHT_OPTION = {"google": {"thinking_config": {"include_thoughts": True}}}


def _sse_frame(delta: dict) -> bytes:
    chunk = {
        "id": "r1", "model": "m",
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
    }
    return (
        "data: " + json.dumps(chunk, ensure_ascii=False, separators=(",", ":")) + "\n\n"
    ).encode("utf-8")


SSE_THOUGHT_OK = (
    _sse_frame({"reasoning_content": "생각 조각"})
    + _sse_frame({"content": "답"})
    + b"data: [DONE]\n\n"
)

SSE_OK = _sse_frame({"content": "ok"}) + b"data: [DONE]\n\n"


def run(coro):
    return asyncio.run(coro)


class _Spec:
    base_origin = "https://upstream.invalid"
    credential_binding_name = "TEST_CREDENTIAL_BINDING"


async def _no_secret(name: str | None = None) -> None:
    return None


async def _collect(agen):
    collected = []
    async for event in agen:
        collected.append(event)
    return collected


def _wire(monkeypatch, handler):
    """Isolate the streaming lane's own logic from the provider registry."""
    monkeypatch.setattr(plat, "_require_spec", lambda provider_id: _Spec())
    monkeypatch.setattr(plat, "_provider_mode", lambda: "live")
    monkeypatch.setattr(plat, "_require_owner_allowed_live_model", lambda *a, **k: None)
    monkeypatch.setattr(
        plat, "_request_headers",
        lambda spec, model_id=None: {
            "Content-Type": "application/json",
            "Authorization": "Bearer test",
        },
    )
    monkeypatch.setattr("app.pilot.worker_env.load_request_secret", _no_secret)
    return httpx.MockTransport(handler)


def _enable(monkeypatch, *, reasoning=True, thoughts=True):
    """Put one catalog row where the platform lane's helpers will find it."""
    model = cat.CatalogModel(
        model_id=MODEL_ID,
        upstream_model=UPSTREAM_MODEL,
        display_name="Test Model",
        provider="Test",
        provider_type="platform",
        input_price_usd_per_1m=0.3,
        output_price_usd_per_1m=2.5,
        platform_provider_id=PROVIDER_ID,
        reasoning_supported=reasoning,
        thought_summary_enabled=thoughts,
    )
    monkeypatch.setitem(cat.CATALOG_BY_ID, MODEL_ID, model)


def _stream(transport):
    return plat.stream_platform_chat_completions(
        model_id=MODEL_ID,
        upstream_model=UPSTREAM_MODEL,
        provider="test-provider",
        platform_provider_id=PROVIDER_ID,
        messages=[{"role": "user", "content": "안녕"}],
        transport=transport,
    )


def _decision() -> RouteDecision:
    return RouteDecision(
        route_mode="manual",
        selected_provider="Test",
        selected_model=MODEL_ID,
        selected_upstream_model=UPSTREAM_MODEL,
        selected_route_id="test-route",
        reason_codes=["manual"],
        fallback_allowed=False,
        eligible_fallback=[],
        excluded_candidates=[],
        credential_available=True,
        credential_status="key_available",
        evidence_status="resolved_not_called",
        request_id="b14req_thought",
        provider_mode="live",
        credential_source="platform_secret",
        platform_provider_id=PROVIDER_ID,
    )


_CANDIDATE = {
    "provider": "Test",
    "model_id": MODEL_ID,
    "upstream_model": UPSTREAM_MODEL,
    "route_id": "test-route",
    "platform_provider_id": PROVIDER_ID,
}


def _draft() -> LedgerDraft:
    return LedgerDraft(
        log_id=new_log_id(),
        request_id="req-thought",
        endpoint="/api/pilot/v1/chat/completions",
        protocol="chat/completions",
        streaming=True,
        requested_model_id=MODEL_ID,
        started_at=utc_now_iso(),
    )


# ---------------------------------------------------------------------------
# The Owner overlay switch
# ---------------------------------------------------------------------------


def test_thought_summary_is_a_supported_model_only_switch():
    assert policy.normalize_policy(
        {"supported": True, "values": ["high"], "thought_summary": True}
    ) == (True, ("high",), "high", True)
    assert policy.normalize_policy(
        {"supported": True, "values": ["high"]}
    ) == (True, ("high",), "high", False)


def test_an_unsupported_model_may_not_declare_thought_summary():
    with pytest.raises(policy.ReasoningPolicyError):
        policy.normalize_policy({"supported": False, "thought_summary": True})


def test_thought_summary_must_be_a_boolean():
    with pytest.raises(policy.ReasoningPolicyError):
        policy.normalize_policy(
            {"supported": True, "values": ["high"], "thought_summary": "yes"}
        )


def test_helper_reads_the_catalog_switch(monkeypatch):
    _enable(monkeypatch)
    assert policy.thought_summary_enabled_for_model(MODEL_ID) is True

    _enable(monkeypatch, reasoning=True, thoughts=False)
    assert policy.thought_summary_enabled_for_model(MODEL_ID) is False

    _enable(monkeypatch, reasoning=False, thoughts=True)
    # An unsupported model never carries a thought request, whatever the row says.
    assert policy.thought_summary_enabled_for_model(MODEL_ID) is False

    assert policy.thought_summary_enabled_for_model("unknown-model") is False
    assert policy.thought_summary_enabled_for_model(None) is False


def test_install_models_applies_the_reasoning_block_to_the_catalog():
    """The block was validated at boot but never installed (#6838 gap)."""
    data = {
        "schema_version": 1,
        "comment": "test",
        "providers": {
            "google": {
                "base_origin": "https://upstream.invalid",
                "allowed_hosts": ["upstream.invalid"],
                "credential_source": "platform_secret",
                "credential_binding_name": "TEST_CREDENTIAL_BINDING",
                "enabled": True,
            },
        },
        "models": [
            {
                "id": "google/thinking-flash",
                "provider_id": "google",
                "upstream_model": "thinking-flash",
                "display_name": "Google: Thinking Flash",
                "provider_name": "Google AI Studio",
                "capabilities": ["chat"],
                "context_window": 1048576,
                "input_price_usd_per_1m": 0.3,
                "output_price_usd_per_1m": 2.5,
                "source": "test_catalog",
                "source_checked_at": "2026-11-05",
                "enabled": True,
                "reasoning": {
                    "supported": True, "values": ["medium", "high"],
                    "thought_summary": True,
                },
            },
        ],
        "groups": {"plus": [], "pro": [], "max": []},
    }
    saved_models = dict(cat.CATALOG_BY_ID)
    saved_list = list(cat.CATALOG_MODELS)
    try:
        install_models(data)
        model = cat.CATALOG_BY_ID["google/thinking-flash"]
        assert model.reasoning_supported is True
        assert model.reasoning_default == "high"
        assert model.thought_summary_enabled is True
        assert policy.reasoning_effort_for_model("google/thinking-flash") == "high"
        assert policy.thought_summary_enabled_for_model("google/thinking-flash") is True
    finally:
        cat.CATALOG_BY_ID.clear()
        cat.CATALOG_BY_ID.update(saved_models)
        cat.CATALOG_MODELS.clear()
        cat.CATALOG_MODELS.extend(saved_list)


def test_install_models_leaves_a_plain_row_unsupported():
    data = {
        "schema_version": 1,
        "comment": "test",
        "providers": {
            "google": {
                "base_origin": "https://upstream.invalid",
                "allowed_hosts": ["upstream.invalid"],
                "credential_source": "platform_secret",
                "credential_binding_name": "TEST_CREDENTIAL_BINDING",
                "enabled": True,
            },
        },
        "models": [
            {
                "id": "google/plain-flash",
                "provider_id": "google",
                "upstream_model": "plain-flash",
                "display_name": "Google: Plain Flash",
                "provider_name": "Google AI Studio",
                "capabilities": ["chat"],
                "context_window": 1048576,
                "input_price_usd_per_1m": 0.3,
                "output_price_usd_per_1m": 2.5,
                "source": "test_catalog",
                "source_checked_at": "2026-11-05",
                "enabled": True,
            },
        ],
        "groups": {"plus": [], "pro": [], "max": []},
    }
    saved_models = dict(cat.CATALOG_BY_ID)
    saved_list = list(cat.CATALOG_MODELS)
    try:
        install_models(data)
        model = cat.CATALOG_BY_ID["google/plain-flash"]
        assert model.reasoning_supported is False
        assert model.thought_summary_enabled is False
        assert policy.reasoning_effort_for_model("google/plain-flash") is None
        assert policy.thought_summary_enabled_for_model("google/plain-flash") is False
    finally:
        cat.CATALOG_BY_ID.clear()
        cat.CATALOG_BY_ID.update(saved_models)
        cat.CATALOG_MODELS.clear()
        cat.CATALOG_MODELS.extend(saved_list)


# ---------------------------------------------------------------------------
# The wire: request, parse, encode
# ---------------------------------------------------------------------------


def test_enabled_model_asks_for_thinking_summaries(monkeypatch) -> None:
    _enable(monkeypatch)
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200, content=SSE_THOUGHT_OK, headers={"content-type": "text/event-stream"},
        )

    events = run(_collect(_stream(_wire(monkeypatch, handler))))

    assert bodies[0]["extra_body"] == THOUGHT_OPTION
    thoughts = [event for event in events if event.delta_thought is not None]
    assert [event.delta_thought for event in thoughts] == ["생각 조각"]
    assert any(event.delta_content == "답" for event in events)


def test_disabled_model_keeps_todays_exact_wire(monkeypatch) -> None:
    _enable(monkeypatch, reasoning=True, thoughts=False)
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200, content=SSE_OK, headers={"content-type": "text/event-stream"},
        )

    run(_collect(_stream(_wire(monkeypatch, handler))))

    assert "extra_body" not in bodies[0]


def test_endpoint_that_rejects_thoughts_still_answers(monkeypatch) -> None:
    _enable(monkeypatch)
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(
                400,
                content=b'{"error":{"message":"Unsupported parameter: include_thoughts"}}',
                headers={"content-type": "application/json"},
            )
        return httpx.Response(
            200, content=SSE_OK, headers={"content-type": "text/event-stream"},
        )

    events = run(_collect(_stream(_wire(monkeypatch, handler))))

    assert len(bodies) == 2
    assert bodies[0]["extra_body"] == THOUGHT_OPTION
    assert "extra_body" not in bodies[1]
    assert any(event.delta_content == "ok" for event in events)


def test_unrelated_request_error_never_retries_for_thoughts(monkeypatch) -> None:
    _enable(monkeypatch)
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            400,
            content=b'{"error":{"message":"context length exceeded"}}',
            headers={"content-type": "application/json"},
        )

    with pytest.raises(Exception):
        run(_collect(_stream(_wire(monkeypatch, handler))))

    assert len(bodies) == 1


def test_only_a_rejection_naming_the_thought_option_is_a_retry_signal():
    assert policy.rejects_thought_summary(
        b'{"error":{"message":"Unsupported parameter: include_thoughts"}}'
    )
    assert policy.rejects_thought_summary(b'{"error":"thinking_config is not supported"}')
    assert not policy.rejects_thought_summary(b'{"error":"rate limited"}')
    assert not policy.rejects_thought_summary(b"")


def test_parse_splits_the_thought_fragment_from_the_answer():
    event = _parse_sse_frame(
        _sse_frame({"reasoning_content": "생각"}),
        provider="test", model_id=MODEL_ID,
    )
    assert event is not None
    assert event.delta_thought == "생각"
    assert event.delta_content is None

    both = _parse_sse_frame(
        _sse_frame({"content": "답", "reasoning_content": "생각"}),
        provider="test", model_id=MODEL_ID,
    )
    assert both is not None
    assert both.delta_content == "답"
    assert both.delta_thought == "생각"

    plain = _parse_sse_frame(
        _sse_frame({"content": "답"}),
        provider="test", model_id=MODEL_ID,
    )
    assert plain is not None
    assert plain.delta_thought is None


def test_a_non_string_thought_delta_is_a_malformed_frame():
    with pytest.raises(MalformedUpstreamResponse):
        _parse_sse_frame(
            b'data: {"id":"r1","model":"m","choices":[{"index":0,'
            b'"delta":{"reasoning_content":42},"finish_reason":null}]}',
            provider="test", model_id=MODEL_ID,
        )


def test_done_event_cannot_carry_a_thought():
    with pytest.raises(ValueError):
        StreamEvent(done=True, delta_thought="생각")


def test_encode_renders_the_thought_as_its_own_delta_field():
    decision = _decision()
    thought = _encode_event(
        StreamEvent(response_id="r1", model=UPSTREAM_MODEL, delta_thought="생각 조각"),
        request_id="req-thought", decision=decision,
    )
    payload = json.loads(thought.decode("utf-8").removeprefix("data: "))
    delta = payload["choices"][0]["delta"]
    assert delta == {"reasoning_content": "생각 조각"}

    answer = _encode_event(
        StreamEvent(response_id="r1", model=UPSTREAM_MODEL, delta_content="답"),
        request_id="req-thought", decision=decision,
    )
    payload = json.loads(answer.decode("utf-8").removeprefix("data: "))
    delta = payload["choices"][0]["delta"]
    assert delta == {"content": "답"}


# ---------------------------------------------------------------------------
# First byte and the ledger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_thought_fragment_is_a_first_byte(monkeypatch):
    monkeypatch.setattr(plat, "_provider_mode", lambda: "live")

    async def iterator():
        yield StreamEvent(response_id="r1", model=UPSTREAM_MODEL, delta_thought="생각 중")
        yield StreamEvent(response_id="r1", model=UPSTREAM_MODEL, delta_thought=" 더함")
        yield StreamEvent(response_id="r1", model=UPSTREAM_MODEL, delta_content="답")
        yield StreamEvent(response_id="r1", model=UPSTREAM_MODEL, finish_reason="stop")
        yield StreamEvent(done=True, finish_reason="stop")

    ledger = _draft()
    body = _stream_body(
        iterator(), [], request_id="req-thought", decision=_decision(),
        attempt_count=1, fallback_used=False, ledger=ledger, candidate=_CANDIDATE,
        attempt_started=1.0,
    )
    frames = [frame async for frame in body]

    assert ledger.ttft_ms is not None, "the first thought fragment must open the stream"
    assert any(b"reasoning_content" in frame for frame in frames)
    attempt = ledger.attempts[-1]
    assert attempt.thought_summary_count == 2
    assert attempt.thought_summary_chars == len("생각 중") + len(" 더함")


@pytest.mark.asyncio
async def test_a_stream_without_thoughts_records_none(monkeypatch):
    monkeypatch.setattr(plat, "_provider_mode", lambda: "live")

    async def iterator():
        yield StreamEvent(response_id="r1", model=UPSTREAM_MODEL, delta_content="답")
        yield StreamEvent(response_id="r1", model=UPSTREAM_MODEL, finish_reason="stop")
        yield StreamEvent(done=True, finish_reason="stop")

    ledger = _draft()
    [_ async for _ in _stream_body(
        iterator(), [], request_id="req-thought", decision=_decision(),
        attempt_count=1, fallback_used=False, ledger=ledger, candidate=_CANDIDATE,
        attempt_started=1.0,
    )]
    attempt = ledger.attempts[-1]
    assert attempt.thought_summary_count is None
    assert attempt.thought_summary_chars is None


def test_ledger_pairs_the_thought_volume_or_stores_neither():
    ledger = _draft()
    attempt = ledger.record_attempt(
        provider="fixture", model_id=MODEL_ID,
        thought_summary_count=3, thought_summary_chars=17,
    )
    assert attempt.thought_summary_count == 3
    assert attempt.thought_summary_chars == 17
    row = attempt.to_row()
    assert row["thought_summary_count"] == 3
    assert row["thought_summary_chars"] == 17

    plain = ledger.record_attempt(provider="fixture", model_id=MODEL_ID)
    assert plain.thought_summary_count is None
    assert plain.thought_summary_chars is None


def test_ledger_refuses_an_incomplete_or_negative_thought_volume():
    ledger = _draft()
    with pytest.raises(CallLedgerError):
        ledger.record_attempt(
            provider="fixture", model_id=MODEL_ID, thought_summary_count=2,
        )
    with pytest.raises(CallLedgerError):
        ledger.record_attempt(
            provider="fixture", model_id=MODEL_ID, thought_summary_chars=-1,
        )


def test_attempt_columns_carry_the_thought_volume():
    from app.pilot.call_ledger_store import _ATTEMPT_COLUMNS

    assert "thought_summary_count" in _ATTEMPT_COLUMNS
    assert "thought_summary_chars" in _ATTEMPT_COLUMNS
