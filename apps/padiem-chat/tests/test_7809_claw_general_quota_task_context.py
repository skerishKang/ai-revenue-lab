"""#7809 9/13: the Claw quota reservation stays in the caller task.

Exercises the real DispatchAwareUsageCounterStore and its ContextVar across
multiple awaits, including the relocated _claw_general_quota_gate boundary.
No Engine, provider, PC dispatch, live store, or external services are used.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from _support.claw_general_modules import patch_bound
from app import claw_general_routes
from app.dispatch_quota import (
    DispatchAwareUsageCounterStore,
    _active_reservation,
    _clear_reservation,
    _refund_active_reservation,
)
from app.usage_gate import UsageDecision


class _Store:
    def __init__(self) -> None:
        self.refund_rows: list[dict] = []

    async def consume(self, **_kwargs) -> UsageDecision:
        await asyncio.sleep(0)
        return UsageDecision(allowed=True, subject_type="user")

    async def _refund(self, **kwargs) -> None:
        await asyncio.sleep(0)
        self.refund_rows.append(kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_conversation", [False, True])
async def test_quota_contextvar_survives_gate_and_caller_await_in_same_task(
    monkeypatch: pytest.MonkeyPatch, existing_conversation: bool,
) -> None:
    """The gate and refund read the exact same reservation after awaits."""
    owner_task = asyncio.current_task()
    assert owner_task is not None
    store = _Store()
    usage = DispatchAwareUsageCounterStore(store)
    observed: list[object] = []
    grant_calls: list[object] = []

    async def reserve_grant(_request, **_kwargs):
        assert asyncio.current_task() is owner_task
        grant_calls.append(owner_task)
        await asyncio.sleep(0)
        assert asyncio.current_task() is owner_task
        return None

    async def gate(_request):
        assert asyncio.current_task() is owner_task
        decision = await usage.consume(
            subject_type="user", subject_key="fixture-owner",
            minute_bucket="fixture-minute", day_bucket="fixture-day",
            burst_limit=10, daily_limit=20, global_daily_limit=100,
            updated_at="2026-11-28T00:00:00Z",
        )
        assert decision.allowed
        receipt = _active_reservation.get()
        assert receipt is not None
        observed.append(receipt)
        await asyncio.sleep(0)
        assert asyncio.current_task() is owner_task
        assert _active_reservation.get() is receipt
        return None

    patch_bound(monkeypatch, "reserve_first_turn_grant", reserve_grant)
    patch_bound(monkeypatch, "_usage_gate_denial", gate)
    patch_bound(monkeypatch, "_claw_stage", lambda *_args, **_kwargs: None)
    patch_bound(monkeypatch, "parse_native_calendar_intent",
                lambda *_args, **_kwargs: {"op": "none"})

    # Ensure prior tests cannot hand this fixture an unrelated reservation.
    _clear_reservation()
    try:
        response, bundle = await claw_general_routes._claw_general_quota_gate(
            SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
                settings=SimpleNamespace(auth_mode="off"),
                history_store=None,
            ))),
            {}, "ordinary fixture text",
            conversation_id="fixture-conversation" if existing_conversation else None,
            subject_id="fixture-subject",
            authorized_workspace_id="fixture-workspace",
            adapter=object(), live_requested=False,
        )
        assert response is None
        assert bundle == {"first_turn_context": None}
        assert len(grant_calls) == (0 if existing_conversation else 1)
        assert asyncio.current_task() is owner_task
        assert len(observed) == 1
        receipt = observed[0]
        assert _active_reservation.get() is receipt

        # This await is in the same task after control returned through the
        # relocated quota function. A new/detached task would break this proof.
        await asyncio.sleep(0)
        assert asyncio.current_task() is owner_task
        assert _active_reservation.get() is receipt
        assert await _refund_active_reservation() is True
        assert _active_reservation.get() is None
        assert len(store.refund_rows) == 3
        assert await _refund_active_reservation() is False
        assert len(store.refund_rows) == 3
    finally:
        _clear_reservation()
