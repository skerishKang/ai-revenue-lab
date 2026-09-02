from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.usage_gate import InMemoryUsageCounterStore, UsageGate


FIXED_NOW = datetime(2026, 9, 2, 13, 30, 0, tzinfo=timezone.utc)
QUOTA_SALT = "b62-launch-policy-test-salt-not-a-real-secret-0001"


def _launch_settings() -> Settings:
    """#1398 launch values: product quota out of the way, abuse fuse retained."""
    return Settings.from_values(
        runtime_mode="b14",
        b14_base_url="https://b14.example",
        quota_salt=QUOTA_SALT,
        anonymous_burst_limit=20,
        anonymous_daily_limit=1_000_000,
        user_burst_limit=40,
        user_daily_limit=1_000_000,
        global_daily_limit=10_000,
    )


def test_launch_policy_is_explicit_config_not_an_unbounded_bypass():
    settings = _launch_settings()

    assert settings.anonymous_burst_limit == 20
    assert settings.anonymous_daily_limit == 1_000_000
    assert settings.user_burst_limit == 40
    assert settings.user_daily_limit == 1_000_000
    assert settings.global_daily_limit == 10_000

    # Product-level daily caps are deliberately out of the way for beta launch,
    # while minute and global emergency limits remain finite server-owned values.
    assert settings.anonymous_burst_limit < settings.anonymous_daily_limit
    assert settings.user_burst_limit < settings.user_daily_limit
    assert settings.global_daily_limit < settings.anonymous_daily_limit


@pytest.mark.asyncio
async def test_launch_anonymous_policy_allows_normal_chat_burst_then_rate_limits():
    store = InMemoryUsageCounterStore()
    gate = UsageGate(_launch_settings(), store, clock=lambda: FIXED_NOW)

    decisions = [
        await gate.authorize(raw_ip="203.0.113.90", user_id=None)
        for _ in range(21)
    ]

    assert all(decision.allowed for decision in decisions[:20])
    assert decisions[20].allowed is False
    assert decisions[20].code == "rate_limited"
    assert decisions[20].status_code == 429
    assert decisions[20].retry_after_seconds == 60
    assert not any(decision.code == "quota_exhausted" for decision in decisions)


@pytest.mark.asyncio
async def test_launch_signed_in_policy_has_higher_finite_burst_ceiling():
    store = InMemoryUsageCounterStore()
    gate = UsageGate(_launch_settings(), store, clock=lambda: FIXED_NOW)
    user_id = "usr_1398launchpolicy000000000000000000"

    decisions = [
        await gate.authorize(raw_ip=None, user_id=user_id)
        for _ in range(41)
    ]

    assert all(decision.allowed for decision in decisions[:40])
    assert decisions[40].allowed is False
    assert decisions[40].code == "rate_limited"
    assert not any(decision.code == "quota_exhausted" for decision in decisions)


@pytest.mark.asyncio
async def test_launch_global_daily_emergency_fuse_remains_fail_closed():
    settings = _launch_settings()
    store = InMemoryUsageCounterStore()
    gate = UsageGate(settings, store, clock=lambda: FIXED_NOW)
    day_bucket = FIXED_NOW.replace(hour=0, minute=0, second=0, microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    store.counts[("global", "global", "global_day", day_bucket)] = settings.global_daily_limit

    decision = await gate.authorize(raw_ip="203.0.113.91", user_id=None)

    assert decision.allowed is False
    assert decision.code == "service_limit_reached"
    assert decision.status_code == 429
    assert decision.limit == 10_000
