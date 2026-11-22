"""#5824/#7543 S37 — BYOK key verification budget is shared across workers.

Only the owner id and fixed-window timestamps are stored. No credential value
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
from test_5121_multi_provider_byok import OWNER, OTHER, EndpointD1, build_chat_app, request

PROBE_KEY = "sk-synthetic-probe-" + "a" * 20
LIMIT = 10
WINDOW = 3600


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def _rows(db):
    return db.conn.execute(
        "SELECT user_id, window_start, count FROM byok_probe_windows"
    ).fetchall()


@pytest.mark.asyncio
async def test_within_hourly_budget_is_allowed() -> None:
    assert PROBE_LIMIT_PER_HOUR == LIMIT
    assert PROBE_WINDOW_SECONDS == WINDOW
    limiter = ProbeRateLimiter(EndpointD1(), clock=FakeClock())
    for _ in range(LIMIT):
        await limiter.check_and_record(OWNER)


@pytest.mark.asyncio
async def test_over_budget_raises_with_a_retry_hint() -> None:
    limiter = ProbeRateLimiter(EndpointD1(), clock=FakeClock())
    for _ in range(LIMIT):
        await limiter.check_and_record(OWNER)
    with pytest.raises(ProbeRateLimited) as caught:
        await limiter.check_and_record(OWNER)
    assert 0 < caught.value.retry_after <= WINDOW


@pytest.mark.asyncio
async def test_budget_unlocks_after_the_window() -> None:
    clock = FakeClock()
    limiter = ProbeRateLimiter(EndpointD1(), clock=clock)
    for _ in range(LIMIT):
        await limiter.check_and_record(OWNER)
    with pytest.raises(ProbeRateLimited):
        await limiter.check_and_record(OWNER)
    clock.now += WINDOW + 1
    await limiter.check_and_record(OWNER)


@pytest.mark.asyncio
async def test_one_owner_does_not_consume_another_owners_budget() -> None:
    limiter = ProbeRateLimiter(EndpointD1(), clock=FakeClock())
    for _ in range(LIMIT):
        await limiter.check_and_record(OWNER)
    with pytest.raises(ProbeRateLimited):
        await limiter.check_and_record(OWNER)
    await limiter.check_and_record(OTHER)


@pytest.mark.asyncio
async def test_two_workers_sharing_one_db_enforce_one_budget() -> None:
    db = EndpointD1()
    worker_a = ProbeRateLimiter(db, clock=FakeClock())
    worker_b = ProbeRateLimiter(db, clock=FakeClock())
    for index in range(LIMIT):
        await (worker_a if index % 2 == 0 else worker_b).check_and_record(OWNER)
    with pytest.raises(ProbeRateLimited):
        await worker_a.check_and_record(OWNER)
    with pytest.raises(ProbeRateLimited):
        await worker_b.check_and_record(OWNER)
    assert sum(row["count"] for row in _rows(db)) == LIMIT


@pytest.mark.asyncio
async def test_two_workers_share_the_window_expiry() -> None:
    clock = FakeClock()
    db = EndpointD1()
    worker_a = ProbeRateLimiter(db, clock=clock)
    worker_b = ProbeRateLimiter(db, clock=clock)
    for index in range(LIMIT):
        await (worker_a if index % 2 == 0 else worker_b).check_and_record(OWNER)
    clock.now += WINDOW + 1
    await worker_b.check_and_record(OWNER)
    assert len(_rows(db)) == 1


@pytest.mark.asyncio
async def test_detect_route_enforces_the_budget_without_echoing_the_key(caplog) -> None:
    clock = FakeClock()
    app, d1, *_ = build_chat_app()
    app.state.byok_probe_limiter = ProbeRateLimiter(d1, clock=clock)

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
    assert all(PROBE_KEY not in str(tuple(row)) for row in _rows(d1))


@pytest.mark.asyncio
async def test_expired_owner_records_are_removed() -> None:
    clock = FakeClock()
    db = EndpointD1()
    limiter = ProbeRateLimiter(db, clock=clock)
    await limiter.check_and_record(OWNER)
    await limiter.check_and_record(OTHER)
    assert {row["user_id"] for row in _rows(db)} == {OWNER, OTHER}

    clock.now += WINDOW + 1
    await limiter.check_and_record("usr_fresh")
    assert {row["user_id"] for row in _rows(db)} == {"usr_fresh"}
