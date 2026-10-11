"""#1982 — bounded retry/backoff for retryable upstream errors on direct routes.

Measured defect: the direct Kilo free route intermittently fails with
``upstream_timeout`` (504 from the Kilo Gateway's ~10s free-model limit) and
the gateway gave up after a single attempt despite the failure being
retryable. These tests pin the retry policy:

- retryable transport failures (upstream_timeout / upstream_server_error)
  are retried on the SAME route with short backoff, at most
  ``_UPSTREAM_RETRY_MAX_RETRIES`` times;
- every retry is recorded in ``reason_codes`` as ``upstream_retry:N`` and in
  ``attempt_evidence[].retry_index`` for audit;
- non-retryable classes (auth, bad request) still fail on the first attempt;
- the first manual model attempt may exceed 45s without being aborted;
- automatic fallback chains and later retries retain the 45s budget.
"""

from __future__ import annotations

import asyncio

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import gateway as gw
from app.pilot import platform as plat
from app.pilot.errors import UpstreamAuthFailed, UpstreamServerError, UpstreamTimeout

MODEL_ID = "agnes-ai/agnes-3.0-flash"


def _ok_response(upstream_model: str) -> dict:
    return {
        "id": "cmpl-retry-test",
        "object": "chat.completion",
        "model": upstream_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "OK"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        "_live": True,
        "_requested_upstream_model": upstream_model,
        "_actual_response_model": upstream_model,
    }


@pytest.fixture(autouse=True)
def _approved_manual_model_secret(monkeypatch):
    """The owner-approved Agnes model is the retry target, never a retired ID."""
    monkeypatch.setenv("PADIEM_AGNES_API_KEY","sk-fixture-agnes-retry-0123456789")
    monkeypatch.setenv("B14_PROVIDER_MODE","live")

@pytest.fixture()
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture()
def no_sleep(monkeypatch):
    """Make backoff sleeps instant without removing the retry bookkeeping."""
    real_sleep = asyncio.sleep

    async def fake_sleep(seconds, *args, **kwargs):
        assert 0 < seconds <= 5.0, f"unexpected backoff {seconds}s"
        return await real_sleep(0)

    monkeypatch.setattr(gw.asyncio, "sleep", fake_sleep)


def _install_seq(monkeypatch, behaviors):
    """Patch the platform adapter with a per-call behavior sequence.

    Each entry is either an Exception instance to raise or a callable
    returning the response dict. Records every call.
    """
    calls: list[dict] = []

    async def fake(*, model_id, upstream_model, provider, platform_provider_id,
                   messages, temperature=0.2, max_tokens=300, transport=None):
        calls.append({"model_id": model_id})
        behavior = behaviors[min(len(calls) - 1, len(behaviors) - 1)]
        if isinstance(behavior, Exception):
            raise behavior
        return behavior(upstream_model)

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake)
    return calls


def _post(client, *, business14=None):
    body = {"model": MODEL_ID, "messages": [{"role": "user", "content": "hi"}]}
    if business14 is not None:
        body["business14"] = business14
    return client.post(
        "/api/pilot/v1/chat/completions",
        json=body,
    )


# ---------------------------------------------------------------------------
# Retryable -> retried
# ---------------------------------------------------------------------------

def test_504_timeout_retries_then_succeeds(client, monkeypatch, no_sleep):
    calls = _install_seq(monkeypatch, [UpstreamTimeout(), _ok_response])

    resp = _post(client)

    assert resp.status_code == 200
    assert len(calls) == 2
    biz14 = resp.json()["business14"]
    assert biz14["attempt_count"] == 2
    assert biz14["fallback_used"] is False  # same route, not a fallback
    assert "upstream_retry:1" in biz14["reason_codes"]
    evidence = biz14["attempt_evidence"]
    assert evidence[0]["outcome"] == "error"
    assert evidence[0]["error_code"] == "upstream_timeout"
    assert evidence[0]["retry_index"] == 0
    assert evidence[1]["outcome"] == "success"
    assert evidence[1]["retry_index"] == 1


def test_502_server_error_retries_then_succeeds(client, monkeypatch, no_sleep):
    calls = _install_seq(monkeypatch, [UpstreamServerError(), _ok_response])

    resp = _post(client)

    assert resp.status_code == 200
    assert len(calls) == 2
    biz14 = resp.json()["business14"]
    assert "upstream_retry:1" in biz14["reason_codes"]


def test_request_max_retries_zero_disables_same_route_retry(client, monkeypatch, no_sleep):
    """A bounded capability proof can force exactly one upstream attempt.

    The production default remains #1982's retry policy; this opt-down is
    request-scoped and cannot increase the global retry ceiling.
    """
    calls = _install_seq(monkeypatch, [UpstreamTimeout(), _ok_response])

    resp = _post(client, business14={"max_retries": 0})

    assert resp.status_code == 504
    assert len(calls) == 1
    error = resp.json()["error"]
    assert error["attempt_count"] == 1
    assert not any(
        str(code).startswith("upstream_retry:") for code in error["reason_codes"]
    )
    assert error["attempt_evidence"] == [
        {
            "attempt": 1,
            "model_id": MODEL_ID,
            "upstream_model": "agnes-3.0-flash",
            "provider": "Agnes AI",
            "route_id": f"platform:{MODEL_ID}",
            "outcome": "error",
            "error_code": "upstream_timeout",
            "retry_index": 0,
            "actual_response_model": None,
        }
    ]


def test_request_max_retries_cannot_exceed_global_ceiling(client, monkeypatch):
    calls = _install_seq(monkeypatch, [_ok_response])

    resp = _post(
        client,
        business14={"max_retries": gw._UPSTREAM_RETRY_MAX_RETRIES + 1},
    )

    assert resp.status_code == 422
    assert calls == []
    assert resp.json()["error"]["code"] == "invalid_body"


def test_request_max_retries_rejects_boolean(client, monkeypatch):
    calls = _install_seq(monkeypatch, [_ok_response])

    resp = _post(client, business14={"max_retries": False})

    assert resp.status_code == 422
    assert calls == []
    assert resp.json()["error"]["code"] == "invalid_body"


def test_retry_exhausted_returns_last_error(client, monkeypatch, no_sleep):
    # Always 504: 1 initial attempt + 2 retries = 3 upstream calls, then the
    # 504 surfaces to the caller with full audit trail.
    calls = _install_seq(monkeypatch, [UpstreamTimeout()])

    resp = _post(client)

    assert resp.status_code == 504
    assert len(calls) == 1 + gw._UPSTREAM_RETRY_MAX_RETRIES
    error = resp.json()["error"]
    assert error["code"] == "upstream_timeout"
    assert error["attempt_count"] == 3
    assert error["attempt_evidence"][0]["retry_index"] == 0
    assert error["attempt_evidence"][-1]["retry_index"] == 2


def test_retry_bookkeeping_is_bounded(client, monkeypatch, no_sleep):
    calls = _install_seq(monkeypatch, [UpstreamTimeout()])

    resp = _post(client)

    error = resp.json()["error"]
    assert len(calls) == 3
    # exactly two retry markers, never a third — and the failure path carries
    # reason_codes so retries stay auditable even when the request fails.
    retry_markers = [
        code for code in error["reason_codes"]
        if str(code).startswith("upstream_retry:")
    ]
    assert retry_markers == ["upstream_retry:1", "upstream_retry:2"]
    assert len(error["attempt_evidence"]) == 3  # one evidence entry per attempt


# ---------------------------------------------------------------------------
# Non-retryable -> fails on first attempt
# ---------------------------------------------------------------------------

def test_auth_failure_no_retry(client, monkeypatch, no_sleep):
    calls = _install_seq(monkeypatch, [UpstreamAuthFailed()])

    resp = _post(client)

    assert resp.status_code == 401
    assert len(calls) == 1
    error = resp.json()["error"]
    assert error["code"] == "upstream_auth_failed"
    assert error["attempt_count"] == 1
    assert error["attempt_evidence"][0]["retry_index"] == 0


def test_missing_key_failure_no_retry(client, monkeypatch, no_sleep):
    from app.pilot.errors import PilotNotConfigured

    calls = _install_seq(monkeypatch, [PilotNotConfigured("no key")])

    resp = _post(client)

    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Budget ceiling
# ---------------------------------------------------------------------------

def test_budget_deadline_caps_subsequent_retry(client, monkeypatch):
    """The first manual model attempt can run long, but the retry is capped."""
    monkeypatch.setattr(gw, "_UPSTREAM_RETRY_BUDGET_SECONDS", 0.08)
    monkeypatch.setattr(gw, "_UPSTREAM_RETRY_BACKOFF_SECONDS", (0.001, 0.001))
    calls = []

    async def fake(**kwargs):
        calls.append(kwargs["model_id"])
        if len(calls) == 1:
            raise UpstreamTimeout()
        await asyncio.sleep(2)
        return _ok_response(kwargs["upstream_model"])

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake)
    import time as _time
    started = _time.monotonic()
    resp = _post(client)
    elapsed = _time.monotonic() - started

    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "upstream_timeout"
    assert len(calls) == 2
    assert elapsed < 1.0


def test_manual_first_model_attempt_survives_retry_deadline(client, monkeypatch):
    """Do not interrupt healthy initial model inference at retry-chain deadline."""
    monkeypatch.setattr(gw, "_UPSTREAM_RETRY_BUDGET_SECONDS", 0.02)
    calls = []

    async def fake(**kwargs):
        calls.append(kwargs["model_id"])
        await asyncio.sleep(0.05)
        return _ok_response(kwargs["upstream_model"])

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake)
    resp = _post(client, business14={"max_retries": 0})

    assert resp.status_code == 200
    assert len(calls) == 1
    assert resp.json()["business14"]["attempt_count"] == 1


def test_manual_slow_failure_exhausts_retry_budget_without_second_call(client, monkeypatch):
    """After a long first attempt, do not dispatch an unplanned paid retry."""
    monkeypatch.setattr(gw, "_UPSTREAM_RETRY_BUDGET_SECONDS", 0.02)
    calls = []

    async def fake(**kwargs):
        calls.append(kwargs["model_id"])
        await asyncio.sleep(0.05)
        raise UpstreamTimeout()

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake)
    resp = _post(client)

    assert resp.status_code == 504
    assert resp.json()["error"]["attempt_count"] == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_manual_initial_request_propagates_parent_cancellation(monkeypatch):
    """Removing the first-attempt hard cap must preserve explicit user abort."""
    monkeypatch.setattr(gw, "_UPSTREAM_RETRY_BUDGET_SECONDS", 0.02)
    entered = asyncio.Event()
    seen_cancel = asyncio.Event()

    async def fake(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            seen_cancel.set()
            raise

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake)
    task = asyncio.create_task(gw._handle_alpha_chat(
        "cancel_test", {"model": MODEL_ID, "messages": [{"role": "user", "content": "offline"}]}
    ))
    await asyncio.wait_for(entered.wait(), timeout=1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert seen_cancel.is_set()


def test_auto_initial_attempt_is_not_force_stopped(client, monkeypatch):
    """Automatic selection must not cut off its first healthy model either."""
    from dataclasses import replace

    original_resolve_route = gw.rcore.resolve_route

    def forced_auto(model_id, options):
        manual = original_resolve_route(model_id, options)
        return replace(manual, route_mode="auto", fallback_allowed=False, max_attempts=1)

    monkeypatch.setattr(gw.rcore, "resolve_route", forced_auto)
    monkeypatch.setattr(gw, "_UPSTREAM_RETRY_BUDGET_SECONDS", 0.04)
    calls = []

    async def fake(**kwargs):
        calls.append(kwargs["model_id"])
        await asyncio.sleep(2)
        return _ok_response(kwargs["upstream_model"])

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake)
    resp = _post(client, business14={"max_retries": 0})
    assert resp.status_code == 200
    assert len(calls) == 1


def test_budget_constants_fit_engine_60s_window():
    """Only auto chains / subsequent retries fit this bounded window.

    The first explicit-model attempt is intentionally outside this budget,
    so the caller's independent cancellation policy remains authoritative.
    Legacy worst-case arithmetic:
    3 attempts x 30s adapter read timeout + 0.5s + 1.0s backoff = 91.5s
    unbounded — therefore the 45s deadline is the hard cap:
    sum(attempt wall time) + sum(backoffs) <= 45s by construction,
    leaving >= 15s headroom inside the engine's 60s orchestration budget.
    """
    assert gw._UPSTREAM_RETRY_BUDGET_SECONDS <= 45.0
    assert gw._UPSTREAM_RETRY_MAX_RETRIES == 2
    assert sum(gw._UPSTREAM_RETRY_BACKOFF_SECONDS) <= 2.0
    # Typical Kilo case: 3 x ~10s (gateway 504) + 1.5s backoff = 31.5s
    typical = 3 * 10.0 + sum(gw._UPSTREAM_RETRY_BACKOFF_SECONDS)
    assert typical <= gw._UPSTREAM_RETRY_BUDGET_SECONDS
