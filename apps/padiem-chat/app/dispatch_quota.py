from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from .b14_client import B14Client, ChatRuntimeError, _resolve_b62_policy
from .model_policy import model_policy_is_executable
from .usage_gate import UsageDecision


@dataclass(slots=True)
class _DispatchState:
    started: bool = False


@dataclass(frozen=True, slots=True)
class _Reservation:
    store: Any
    buckets: tuple[tuple[str, str, str, str], ...]
    updated_at: str
    dispatch: _DispatchState = field(default_factory=_DispatchState)


_active_reservation: ContextVar[_Reservation | None] = ContextVar(
    "b62_active_pre_dispatch_quota_reservation",
    default=None,
)


def _clear_reservation() -> None:
    _active_reservation.set(None)


def _mark_active_reservation_dispatched() -> None:
    reservation = _active_reservation.get()
    if reservation is not None:
        # Core's bounded Service Binding transport runs post_json in a child
        # task. Its copied ContextVar shares this marker with the parent, while
        # setting the ContextVar to None alone would clear only the child.
        reservation.dispatch.started = True
    _clear_reservation()


async def _refund_active_reservation() -> bool:
    reservation = _active_reservation.get()
    _clear_reservation()
    if reservation is None or reservation.dispatch.started:
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

    Missing Service Bindings and, when the public live deadman switch is armed,
    a non-executable Padiem model policy are local deterministic pre-dispatch
    failures. Router-owned ``b14/auto`` is executable without a concrete B62
    model assignment, so it is allowed to reach B14. Non-live B14 test/preflight
    paths remain available for infrastructure regression without representing a
    public product route.
    """

    async def _reject_non_executable_policy(self, messages: list[dict[str, str]]) -> None:
        if self.settings.runtime_mode == "mock" or not self.settings.live_enabled:
            return
        policy = _resolve_b62_policy(messages, require_executable=False)
        if model_policy_is_executable(policy.model_id):
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
        await self._reject_non_executable_policy(messages)
        await self._prepare_stream_dispatch()
        async for event in super().stream_text_auto(messages, *args, **kwargs):
            yield event

    async def _prepare_registered_quote_dispatch(self) -> None:
        _mark_active_reservation_dispatched()

    async def complete_registered_quote_model(
        self,
        messages,
        *,
        model,
        additional_system_context=None,
        reasoning_effort=None,
    ):
        """Bypass B62 tier HOLD only; keep B66 runtime/admission boundaries.

        #3906: this override is the last hop before the actual B14 POST, so it
        must forward every field the base path accepts. Dropping
        ``reasoning_effort`` here would reject the user's explicit level in
        production (where this dispatch-aware client is the installed one)
        even though the base client and the Core wire carry it correctly.
        """
        try:
            return await super().complete_registered_quote_model(
                messages,
                model=model,
                additional_system_context=additional_system_context,
                reasoning_effort=reasoning_effort,
            )
        except (ChatRuntimeError, ValueError):
            # Dispatch clears the receipt first. Only local failures still have
            # an active reservation; an upstream failure must stay consumed.
            await _refund_active_reservation()
            raise

    async def complete(self, messages, *args, **kwargs):
        await self._reject_non_executable_policy(messages)
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
