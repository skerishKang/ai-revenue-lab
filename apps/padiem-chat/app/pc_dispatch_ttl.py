"""#7841 — a Chat PC dispatch lives only as long as the turn that asked for it.

A Chat answer has a fixed front-door budget (the same ``_answer_budget_seconds``
#7881 already spends waiting for the PC). The dispatch row, however, is staged
on a separate Engine -> Chat signed call and used to keep the flat
``_DISPATCH_TTL`` of ten minutes. A PC that woke up minutes after the answer had
ended could still claim and run a write command whose result ``summary_guard``
would then throw away — work the user was told had failed.

This module carries the turn's identity across that separate call without
adding a field to the queue or executor contract: Chat marks the signed Chat PC
routes with a context flag, and the two dispatch-creation functions consult it.
Only rows created by a Chat PC turn get the short TTL; every other caller keeps
the existing ten-minute value byte for byte.
"""
from __future__ import annotations

import contextvars
import functools
import math
import time
from datetime import datetime
from typing import Any, Awaitable, Callable, TypeVar

#: The PC executor polls and renews on a seconds-scale beat. Five seconds lets a
#: dispatch that arrives just as the answer window closes still be claimed once,
#: without keeping an abandoned write alive for another turn.
PC_DISPATCH_TTL_SLACK_SECONDS = 5

_T = TypeVar("_T")
_CHAT_PC_DISPATCH = contextvars.ContextVar(
    "chat_pc_dispatch_ttl_active", default=False,
)


def chat_pc_dispatch_ttl_scope() -> bool:
    """Whether the current call is a Chat PC turn allowed to shorten its TTL."""

    return _CHAT_PC_DISPATCH.get()


def _run_in_chat_pc_scope(fn: Callable[..., Awaitable[_T]]) -> Callable[..., Awaitable[_T]]:
    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> _T:
        token = _CHAT_PC_DISPATCH.set(True)
        try:
            return await fn(*args, **kwargs)
        finally:
            _CHAT_PC_DISPATCH.reset(token)

    return wrapper


def chat_pc_dispatch_ttl(fn: Callable[..., Awaitable[_T]]) -> Callable[..., Awaitable[_T]]:
    """Mark a Chat-only PC route: dispatches created inside it use the turn TTL."""

    return _run_in_chat_pc_scope(fn)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def dispatch_ttl_seconds(
    run_row: Any, *, now: float | None = None, max_seconds: float = 600,
) -> int | None:
    """The TTL for one Chat PC dispatch, or ``None`` for the existing default.

    ``None`` means "this call is not a Chat PC turn, or the run's staging time
    is unknown" — the caller then keeps ``_DISPATCH_TTL``. A run old enough that
    its answer window has already closed returns the floor of one second: the
    row is still staged (the existing contract) but cannot be claimed later.
    """

    if not _CHAT_PC_DISPATCH.get():
        return None
    updated_at = _parse_iso(run_row.get("updated_at") if isinstance(run_row, dict) else None)
    if updated_at is None:
        return None

    # The same budget #7881 waits with, measured from the moment Chat staged this
    # run: the model call and admission already happened before that write.
    from .orchestration_routes import ANSWER_BUDGET_MARGIN_MS, DEFAULT_ANSWER_BUDGET_MS

    moment = time.time() if now is None else now
    elapsed = max(0.0, moment - updated_at.timestamp())
    remaining = (
        DEFAULT_ANSWER_BUDGET_MS / 1000.0
        - elapsed
        - ANSWER_BUDGET_MARGIN_MS / 1000.0
    )
    if remaining <= 0:
        return 1
    ttl = math.ceil(remaining + PC_DISPATCH_TTL_SLACK_SECONDS)
    return max(1, min(int(max_seconds), ttl))
