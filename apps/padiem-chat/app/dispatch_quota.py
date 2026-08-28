from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from .b14_client import B14Client, ChatRuntimeError, _resolve_b62_policy
from .model_policy import model_profile_is_assigned
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
    """Refund failures B62 can prove happened before B14 dispatch.

    Missing Service Bindings and an unassigned Padiem model profile are local,
    deterministic pre-dispatch failures. They refund the exact active reservation.
    Once Core/Service-Binding execution can begin, refundability is cleared so
    transport ambiguity, B14 429/5xx, Provider failures and post-start stream
    failures remain conservatively counted.
    """

    async def _reject_unassigned_profile(self, messages: list[dict[str, str]]) -> None:
        if self.settings.runtime_mode == "mock":
            return
        policy = _resolve_b62_policy(messages)
        if model_profile_is_assigned(policy.model_id):
            return
        await _refund_active_reservation()
        raise ChatRuntimeError(
            503,
            "model_profile_unassigned",
            "현재 대화 모델을 준비 중입니다. 잠시 후 다시 이용해 주세요.",
        )

    async def _prepare_stream_dispatch(self) -> None:
        if (
            self.settings.runtime_mode != "mock"
            and self.require_service_binding
            and self.stream_transport is None
        ):
            await _refund_active_reservation()
        elif self.settings.runtime_mode != "mock":
            _clear_reservation()

    async def stream_text_preview(self, *args, **kwargs):
        await self._prepare_stream_dispatch()
        async for event in super().stream_text_preview(*args, **kwargs):
            yield event

    async def stream_text_auto(self, messages, *args, **kwargs):
        await self._reject_unassigned_profile(messages)
        await self._prepare_stream_dispatch()
        async for event in super().stream_text_auto(messages, *args, **kwargs):
            yield event

    async def complete(self, messages, *args, **kwargs):
        await self._reject_unassigned_profile(messages)
        if (
            self.settings.runtime_mode != "mock"
            and self.require_service_binding
            and self.service_transport is None
        ):
            await _refund_active_reservation()
            return await super().complete(messages, *args, **kwargs)

        if self.settings.runtime_mode != "mock":
            _clear_reservation()
        return await super().complete(messages, *args, **kwargs)
