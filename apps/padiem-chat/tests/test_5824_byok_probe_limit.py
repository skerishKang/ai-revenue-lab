"""#5824 — BYOK key verification calls have a bounded per-owner budget.

The probe budget counts only the owner id and timestamps. No credential value
is stored, logged or returned by any path exercised here.
"""
from __future__ import annotations

import pytest

from app.byok_probe_limit import (
    PROBE_LIMIT_PER_HOUR,
    PROBE_WINDOW_SECONDS,
    ProbeRateLimited,
    ProbeRateLimiter,
)
from test_5121_multi_provider_byok import OWNER, OTHER, build_chat_app, request

PROBE_KEY = "sk-synthetic-probe-" + "a" * 20
LIMIT = 10
WINDOW = 3600


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_within_hourly_budget_is_allowed() -> None:
    assert PROBE_LIMIT_PER_HOUR == LIMIT
    assert PROBE_WINDOW_SECONDS == WINDOW
    limiter = ProbeRateLimiter(clock=FakeClock())
    for _ in range(LIMIT):
        limiter.check_and_record(OWNER)


def test_over_budget_raises_with_a_retry_hint() -> None:
    limiter = ProbeRateLimiter(clock=FakeClock())
    for _ in range(LIMIT):
        limiter.check_and_record(OWNER)
    with pytest.raises(ProbeRateLimited) as caught:
        limiter.check_and_record(OWNER)
    assert 0 < caught.value.retry_after <= WINDOW


def test_budget_unlocks_after_the_window() -> None:
    clock = FakeClock()
    limiter = ProbeRateLimiter(clock=clock)
    for _ in range(LIMIT):
        limiter.check_and_record(OWNER)
    with pytest.raises(ProbeRateLimited):
        limiter.check_and_record(OWNER)
    clock.now += WINDOW + 1
    limiter.check_and_record(OWNER)


def test_one_owner_does_not_consume_another_owners_budget() -> None:
    limiter = ProbeRateLimiter(clock=FakeClock())
    for _ in range(LIMIT):
        limiter.check_and_record(OWNER)
    with pytest.raises(ProbeRateLimited):
        limiter.check_and_record(OWNER)
    limiter.check_and_record(OTHER)


@pytest.mark.asyncio
async def test_detect_route_enforces_the_budget_without_echoing_the_key(caplog) -> None:
    clock = FakeClock()
    app, *_ = build_chat_app()
    app.state.byok_probe_limiter = ProbeRateLimiter(clock=clock)

    responses = []
    body = {"key": PROBE_KEY, "base_url": "https://gateway.example.test/v1"}
    for _ in range(LIMIT):
        responses.append(await request(app, "POST", "/api/byok/detect", uid=OWNER, json_body=body))
    assert all(r.status_code == 200 for r in responses)

    over = await request(app, "POST", "/api/byok/detect", uid=OWNER, json_body=body)
    assert over.status_code == 429
    assert over.json()["error"]["code"] == "byok_probe_rate_limited"
    assert "잠시 뒤 다시 시도해 주세요" in over.json()["error"]["message"]

    clock.now += WINDOW + 1
    unlocked = await request(app, "POST", "/api/byok/detect", uid=OWNER, json_body=body)
    assert unlocked.status_code == 200

    other = await request(app, "POST", "/api/byok/detect", uid=OTHER, json_body=body)
    assert other.status_code == 200

    for response in (*responses, over, unlocked, other):
        assert PROBE_KEY not in response.text
    assert PROBE_KEY not in caplog.text
