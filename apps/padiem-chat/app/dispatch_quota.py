from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from .b14_client import B14Client
from .usage_gate import UsageDecision


@dataclass(frozen=True, slots=True)
class _Reservation:
    store: Any
    buckets: tuple[tuple[str, str, str, str], ...]
    updated_at: str


_active_reservation: ContextVar[_Reservation | None] = ContextVar(
    "b62_active_pre_dispatch_quota_reservation",
    default=None,
)


def _clear_reservation() -> None:
    _active_reservation.set(None)


async def _refund_active_reservation() -> bool:
    reservation = _active_reservation.get()
    _clear_reservation()
    if reservation is None:
        return False

    refund_bucket = getattr(reservation.store, "_refund", None)
    if not callable(refund_bucket):
        return False

    refunded_all = True
    for subject_type, subject_key, bucket_type, bucket_start in reversed(reservation.buckets):
        try:
            await refund_bucket(
                subject_type=subject_type,
                subject_key=subject_key,
                bucket_type=bucket_type,
                bucket_start=bucket_start,
                updated_at=reservation.updated_at,
            )
        except Exception:
            refunded_all = False
    return refunded_all


class DispatchAwareUsageCounterStore:
    """Keep one exact authorization receipt only until B14 dispatch becomes possible.

    The wrapped store remains the quota-policy authority. This adapter records the
    exact minute/day/global buckets from an allowed authorization so a later local,
    provable pre-dispatch failure can compensate only that request. Gate denials and
    normal store behavior are unchanged.
    """

    def __init__(self, store: Any):
        if store is None:
            raise ValueError("usage counter store is required")
        self.store = store

    async def consume(
        self,
        *,
        subject_type: str,
        subject_key: str,
        minute_bucket: str,
        day_bucket: str,
        burst_limit: int,
        daily_limit: int,
        global_daily_limit: int,
        updated_at: str,
    ) -> UsageDecision:
        _clear_reservation()
        decision = await self.store.consume(
            subject_type=subject_type,
            subject_key=subject_key,
            minute_bucket=minute_bucket,
            day_bucket=day_bucket,
            burst_limit=burst_limit,
            daily_limit=daily_limit,
            global_daily_limit=global_daily_limit,
            updated_at=updated_at,
        )
        if decision.allowed:
            _active_reservation.set(
                _Reservation(
                    store=self.store,
                    buckets=(
                        (subject_type, subject_key, "minute", minute_bucket),
                        (subject_type, subject_key, "day", day_bucket),
                        ("global", "global", "global_day", day_bucket),
                    ),
                    updated_at=updated_at,
                )
            )
        return decision


class DispatchAwareB14Client(B14Client):
    """Refund only the one failure B62 can prove happened before B14 dispatch.

    A missing required Service Binding is detected locally before any transport call.
    Every path that can attempt Core/Service-Binding execution clears refundability
    first, so timeouts, transport ambiguity, B14 429/5xx, malformed responses and
    Provider failures remain conservatively counted.
    """

    async def complete(self, *args, **kwargs):
        if (
            self.settings.runtime_mode != "mock"
            and self.require_service_binding
            and self.service_transport is None
        ):
            await _refund_active_reservation()
            return await super().complete(*args, **kwargs)

        if self.settings.runtime_mode != "mock":
            _clear_reservation()
        return await super().complete(*args, **kwargs)
