"""#2226: Claw execute quota refund semantics on the B62 UsageGate path.

Canonical invariant (#830/#1230, enforced through the explicit reservation
lifecycle in ``app.dispatch_quota``):

- success after authorization        -> NO refund
- gate denial                         -> NO refund (store compensates its own attempt)
- provable pre-dispatch failure       -> refund the exact authorization receipt once
- dispatched / ambiguous failures     -> NO refund (conservative counting)
- caller-supplied refund fields       -> inert; identity is server-derived only
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.config import Settings
from app.dispatch_quota import (
    DispatchAwareUsageCounterStore,
    _refund_active_reservation,
)
from app.usage_gate import InMemoryUsageCounterStore
from kagent.p01_adapter import P01AdapterError, P01DispatchClass

QUOTA_SALT = "claw-refund-quota-salt-not-a-real-secret-01"
IP = "203.0.113.77"
EXECUTE_ROUTE = "/api/claw/manual-intake/execute"
PAYLOAD: dict[str, Any] = {
    "content": "가상 테스트: A업체가 9월 말까지 샘플 20개 견적서를 요청함.",
    "channel": "kakao",
    "action": "reply",
    "sender_hint": "A업체",
}


def _live_quota_settings(**overrides) -> Settings:
    values = {
        "runtime_mode": "b14",
        "b14_base_url": "https://b14.example",
        "quota_salt": QUOTA_SALT,
        "anonymous_burst_limit": 4,
        "anonymous_daily_limit": 20,
        "user_burst_limit": 8,
        "user_daily_limit": 100,
        "global_daily_limit": 1000,
    }
    values.update(overrides)
    return Settings.from_values(**values)


class RefundableMemoryStore(InMemoryUsageCounterStore):
    def __init__(self) -> None:
        super().__init__()
        self.bucket_refund_calls = 0

    async def _refund(
        self,
        *,
        subject_type: str,
        subject_key: str,
        bucket_type: str,
        bucket_start: str,
        updated_at: str,
    ) -> None:
        del updated_at
        self.bucket_refund_calls += 1
        key = (subject_type, subject_key, bucket_type, bucket_start)
        self.counts[key] = max(0, self.counts.get(key, 0) - 1)


class ExplodingRefundStore(RefundableMemoryStore):
    async def _refund(self, **kwargs: Any) -> None:
        del kwargs
        self.bucket_refund_calls += 1
        raise RuntimeError("refund transport failed")


def _make_outcome(*, answer: str = "답변 완료", status_value: str = "completed"):
    from unittest.mock import MagicMock

    projection = MagicMock()
    projection.status = MagicMock()
    projection.status.value = status_value
    outcome = MagicMock()
    outcome.projection = projection
    outcome.answer = answer
    outcome.p01_run_id = "p01_run_test123"
    outcome.p01_event_count = 3
    return outcome


def _make_adapter(outcome: Any = None, error: BaseException | None = None):
    from unittest.mock import AsyncMock, MagicMock

    adapter = MagicMock()
    if error is not None:
        adapter.execute = AsyncMock(side_effect=error)
    else:
        adapter.execute = AsyncMock(return_value=outcome if outcome is not None else _make_outcome())
    return adapter


def _app(store: RefundableMemoryStore, settings: Settings | None = None):
    wrapped = DispatchAwareUsageCounterStore(store)
    return create_app(settings or _live_quota_settings(), usage_store=wrapped)


def _post(app, payload: dict[str, Any] | None = None):
    with TestClient(app) as client:
        return client.post(
            EXECUTE_ROUTE,
            json=payload if payload is not None else PAYLOAD,
            headers={"cf-connecting-ip": IP},
        )


def _count_values(store: RefundableMemoryStore) -> list[int]:
    return sorted(store.counts.values())


def _not_dispatched_error() -> P01AdapterError:
    return P01AdapterError(
        "terminal_run",
        "pre-dispatch failure",
        dispatch_class=P01DispatchClass.NOT_DISPATCHED,
    )


# ── refundable: provable pre-dispatch failures ──────────────────────────────


def test_not_dispatched_failure_after_authorize_refunds_once() -> None:
    store = RefundableMemoryStore()
    app = _app(store)
    app.state.claw_p01_adapter = _make_adapter(error=_not_dispatched_error())

    resp = _post(app)

    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "engine_execution_failed"
    assert _count_values(store) == [0, 0, 0]
    assert store.bucket_refund_calls == 3


def test_missing_p01_adapter_refunds_pre_dispatch_authorization() -> None:
    store = RefundableMemoryStore()
    app = _app(store)
    app.state.claw_p01_adapter = None

    resp = _post(app)

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "engine_not_configured"
    assert _count_values(store) == [0, 0, 0]
    assert store.bucket_refund_calls == 3


# ── never refundable: success, denial, dispatched/ambiguous failures ────────


def test_successful_execution_does_not_refund() -> None:
    store = RefundableMemoryStore()
    app = _app(store)
    app.state.claw_p01_adapter = _make_adapter()

    resp = _post(app)

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert _count_values(store) == [1, 1, 1]
    assert store.bucket_refund_calls == 0


def test_usage_denial_does_not_refund() -> None:
    store = RefundableMemoryStore()
    app = _app(store, settings=_live_quota_settings(anonymous_burst_limit=1))
    adapter = _make_adapter()
    app.state.claw_p01_adapter = adapter

    first = _post(app)
    second = _post(app)

    assert first.status_code == 200
    assert second.status_code == 429
    assert adapter.execute.await_count == 1
    # The denied attempt is compensated inside the store, never through the
    # pre-dispatch reservation seam.
    assert store.bucket_refund_calls == 0
    assert _count_values(store) == [1, 1, 1]


def test_timeout_after_authorize_is_not_refunded() -> None:
    store = RefundableMemoryStore()
    app = _app(store)
    app.state.claw_p01_adapter = _make_adapter(
        error=P01AdapterError(
            "p01_engine_request_failed",
            "P01 orchestration failed at the Engine boundary.",
            dispatch_class=P01DispatchClass.UNKNOWN,
        )
    )

    resp = _post(app)

    assert resp.status_code == 502
    assert _count_values(store) == [1, 1, 1]
    assert store.bucket_refund_calls == 0


def test_engine_5xx_after_authorize_is_not_refunded() -> None:
    store = RefundableMemoryStore()
    app = _app(store)
    app.state.claw_p01_adapter = _make_adapter(
        error=P01AdapterError(
            "engine_unavailable",
            "Engine returned a server-side failure.",
            dispatch_class=P01DispatchClass.DISPATCHED,
        )
    )

    resp = _post(app)

    assert resp.status_code == 502
    assert _count_values(store) == [1, 1, 1]
    assert store.bucket_refund_calls == 0


def test_malformed_downstream_after_authorize_is_not_refunded() -> None:
    store = RefundableMemoryStore()
    app = _app(store)
    app.state.claw_p01_adapter = _make_adapter(
        error=P01AdapterError(
            "unsupported_result_field",
            "P01 result carries data the projection cannot reconstruct.",
            dispatch_class=P01DispatchClass.DISPATCHED,
        )
    )

    resp = _post(app)

    assert resp.status_code == 502
    assert _count_values(store) == [1, 1, 1]
    assert store.bucket_refund_calls == 0


def test_unclassified_failure_after_authorize_is_not_refunded() -> None:
    store = RefundableMemoryStore()
    app = _app(store)
    app.state.claw_p01_adapter = _make_adapter(error=RuntimeError("ambiguous internal failure"))

    resp = _post(app)

    assert resp.status_code == 502
    assert _count_values(store) == [1, 1, 1]
    assert store.bucket_refund_calls == 0


def test_incomplete_outcome_after_dispatch_is_not_refunded() -> None:
    store = RefundableMemoryStore()
    app = _app(store)
    app.state.claw_p01_adapter = _make_adapter(outcome=_make_outcome(status_value="failed"))

    resp = _post(app)

    assert resp.status_code == 502
    assert _count_values(store) == [1, 1, 1]
    assert store.bucket_refund_calls == 0


# ── idempotency / race safety ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reservation_refunds_at_most_once() -> None:
    store = RefundableMemoryStore()
    gate = _app(store).state.usage_gate

    decision = await gate.authorize(raw_ip=IP, user_id=None)
    assert decision.allowed is True

    first = await _refund_active_reservation()
    second = await _refund_active_reservation()

    assert first is True
    assert second is False
    assert store.bucket_refund_calls == 3
    assert _count_values(store) == [0, 0, 0]


def test_retry_after_refund_pays_for_a_new_execution() -> None:
    store = RefundableMemoryStore()
    app = _app(store)
    failing = _make_adapter(error=_not_dispatched_error())
    app.state.claw_p01_adapter = failing

    first = _post(app)
    assert first.status_code == 502
    assert _count_values(store) == [0, 0, 0]

    succeeding = _make_adapter()
    app.state.claw_p01_adapter = succeeding
    second = _post(app)

    assert second.status_code == 200
    # The retried execution consumed exactly one fresh quota unit: no free run.
    assert _count_values(store) == [1, 1, 1]
    assert failing.execute.await_count == 1
    assert succeeding.execute.await_count == 1


@pytest.mark.asyncio
async def test_concurrent_failures_refund_only_their_own_receipts() -> None:
    store = RefundableMemoryStore()
    app = _app(store, settings=_live_quota_settings(anonymous_burst_limit=4))
    app.state.claw_p01_adapter = _make_adapter(error=_not_dispatched_error())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        responses = await asyncio.gather(
            *(
                client.post(EXECUTE_ROUTE, json=PAYLOAD, headers={"cf-connecting-ip": IP})
                for _ in range(2)
            )
        )

    assert [response.status_code for response in responses] == [502, 502]
    # Two independent authorizations → exactly two full receipt refunds.
    assert store.bucket_refund_calls == 6
    assert _count_values(store) == [0, 0, 0]


def test_refund_failure_fails_safe() -> None:
    store = ExplodingRefundStore()
    app = _app(store)
    app.state.claw_p01_adapter = _make_adapter(error=_not_dispatched_error())

    resp = _post(app)

    # The route still answers with the bounded failure and the consumed quota
    # stays counted (conservative over-counting) instead of double-refunding.
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "engine_execution_failed"
    assert store.bucket_refund_calls == 3
    assert _count_values(store) == [1, 1, 1]
    assert "refund" not in resp.text


# ── caller has no refund authority ──────────────────────────────────────────


SPOOFED_REFUND_FIELDS: dict[str, Any] = {
    "refund": True,
    "refund_id": "caller-minted-refund-0001",
    "usage_adjustment": "refund",
    "quota_delta": -5,
    "billing_credit": "unlimited",
}


def test_caller_cannot_request_refund_on_success() -> None:
    store = RefundableMemoryStore()
    app = _app(store)
    app.state.claw_p01_adapter = _make_adapter()

    resp = _post(app, payload=dict(PAYLOAD, **SPOOFED_REFUND_FIELDS))

    assert resp.status_code == 200
    assert _count_values(store) == [1, 1, 1]
    assert store.bucket_refund_calls == 0


def test_caller_cannot_mint_refund_identity_on_failure() -> None:
    store = RefundableMemoryStore()
    app = _app(store)
    app.state.claw_p01_adapter = _make_adapter(error=_not_dispatched_error())

    resp = _post(app, payload=dict(PAYLOAD, **SPOOFED_REFUND_FIELDS))

    assert resp.status_code == 502
    # The refund that did happen used only the server-derived receipt: the
    # caller-minted identity never entered quota accounting.
    assert store.bucket_refund_calls == 3
    assert "caller-minted-refund-0001" not in str(store.counts)
    assert all(key[1].startswith("anon_") or key[1] == "global" for key in store.counts)


def test_execute_route_has_no_body_driven_refund_authority() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "claw_routes.py").read_text(
        encoding="utf-8"
    )
    execute_handler = source.split("async def claw_manual_intake_execute", 1)[1].split(
        "async def claw_manual_intake_artifact", 1
    )[0]

    for field in ("refund", "refund_id", "usage_adjustment", "quota_delta", "billing_credit"):
        assert f'data.get("{field}"' not in execute_handler
        assert f"data[{field!r}]" not in execute_handler
    # Refunds exist only through the reservation seam and the server-side
    # dispatch classification, never through a caller-visible knob.
    assert execute_handler.count("_refund_active_reservation()") == 2
    assert "P01DispatchClass.NOT_DISPATCHED" in execute_handler
