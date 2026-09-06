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
- the whole attempt chain is hard-capped by the 45s budget deadline.
"""

from __future__ import annotations

import asyncio

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import gateway as gw
from app.pilot import platform as plat
from app.pilot.errors import UpstreamAuthFailed, UpstreamServerError, UpstreamTimeout

KILO_MODEL = "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"


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


@pytest.fixture()
def client():
    return TestClient(create_app())


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


def _post(client):
    return client.post(
        "/api/pilot/v1/chat/completions",
        json={"model": KILO_MODEL, "messages": [{"role": "user", "content": "hi"}]},
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

def test_budget_deadline_caps_attempt_chain(client, monkeypatch):
    """A hung upstream is cut off by the deadline; total wall time stays
    within the (shrunk-for-test) budget and no retry is attempted once the
    budget is gone."""
    monkeypatch.setattr(gw, "_UPSTREAM_RETRY_BUDGET_SECONDS", 1.0)

    calls = []

    async def fake(**kwargs):
        calls.append(kwargs["model_id"])
        await asyncio.sleep(10)  # far beyond the 1s budget
        raise UpstreamTimeout()  # unreachable: deadline fires first

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake)

    import time as _time

    wall = _time.monotonic()
    resp = _post(client)
    elapsed = _time.monotonic() - wall

    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "upstream_timeout"
    assert len(calls) == 1  # budget exhausted -> no retry after the deadline
    assert elapsed < 5.0, f"attempt chain exceeded the budget ceiling: {elapsed:.1f}s"


def test_budget_constants_fit_engine_60s_window():
    """Worst-case arithmetic (documented in the PR):
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
