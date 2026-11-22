"""#7841 — a PC-tool turn ends inside its own window with a fixed notice.

The model-first PC lane waits on the Engine's orchestration call. A PC tool
turn carries no execution deadline on that wire (#5573), so Chat's own wait had
no bound either: when the PC claimed a dispatch and then sent no byte, the
client gave up first and the user received no guidance at all.

This module bounds only Chat's wait for the first orchestration result. The PC
work itself keeps running, and a result that lands late still meets the
unchanged ``summary_guard`` in ``history.py``. The bound is the turn's own
remaining answer budget, so no second wait number is introduced.
"""
from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Awaitable
from typing import TypeVar

#: The owner-facing failure notice. No English, tool name, or dispatch id: the
#: user only needs to know which side to check and that trying again is safe.
PC_DISPATCH_NO_RESULT_TEXT = (
    "PC가 응답하지 않습니다. PC가 켜져 있고 PADIEM 연결 프로그램이 실행 중인지 확인한 뒤 다시 시도해 주세요."
)
#: The closed reason word the timing line carries when the turn window ended
#: first. Same shape as the #7857 append reasons: a lower-case word only.
PC_DISPATCH_NO_RESULT_CODE = "pc_dispatch_no_result_in_window"
PC_DISPATCH_WAIT_NONE = "none"
_PC_DISPATCH_WAIT_CODES = frozenset({
    PC_DISPATCH_WAIT_NONE,
    PC_DISPATCH_NO_RESULT_CODE,
})
_WAIT_REASON = contextvars.ContextVar(
    "pc_dispatch_wait_reason", default=PC_DISPATCH_WAIT_NONE,
)

_Result = TypeVar("_Result")


def reset_wait_reason() -> None:
    """Clear the reason so a reused context cannot inherit the previous turn."""

    _WAIT_REASON.set(PC_DISPATCH_WAIT_NONE)


def note_wait_reason(code: str) -> None:
    """Record one closed reason word; never raises and never writes a record."""

    _WAIT_REASON.set(code if code in _PC_DISPATCH_WAIT_CODES else PC_DISPATCH_WAIT_NONE)


def last_wait_reason() -> str:
    """The reason the most recent wait in this context recorded."""

    return _WAIT_REASON.get()


async def await_pc_dispatch(
    awaitable: Awaitable[_Result], *, wait_seconds: float | None,
) -> tuple[bool, _Result | None]:
    """Wait for one PC-tool orchestration result inside the turn window.

    Returns ``(True, result)`` when the Engine answered in time. On timeout it
    records the reason and returns ``(False, None)``. ``None`` keeps the exact
    pre-existing unbounded wait for callers that carry no turn budget.
    """

    if wait_seconds is None:
        return True, await awaitable
    try:
        value = await asyncio.wait_for(
            awaitable, timeout=max(0.001, float(wait_seconds)),
        )
    except asyncio.TimeoutError:
        note_wait_reason(PC_DISPATCH_NO_RESULT_CODE)
        return False, None
    return True, value


__all__ = [
    "PC_DISPATCH_NO_RESULT_CODE",
    "PC_DISPATCH_NO_RESULT_TEXT",
    "PC_DISPATCH_WAIT_NONE",
    "await_pc_dispatch",
    "last_wait_reason",
    "note_wait_reason",
    "reset_wait_reason",
]
