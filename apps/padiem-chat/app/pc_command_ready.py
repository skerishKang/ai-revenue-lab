"""#7987 — whether a connected PC can take a user-mode command, from what it reported.

'연결됨' says the PC's Mesh agent answers. A user-mode command also needs the
user-session helper: installed, a Windows user signed in, and the helper
listening. The executor observes those facts on its existing device round and
the queue keeps the latest row per PC; this module turns one row into the three
words the settings screen shows.

It replaces the #7990 history reading (the newest ``not_executed`` dispatch).
That reading could only speak after a command had already failed, missed the
ordinary ``pc_shell`` failure, and was never issued on the queue-backed store.
Nothing here reads a dispatch, sends a PC command or touches a private store
method: the row comes through the store's public ``load_helper_ready`` call,
which both deployment shapes serve.

The answer is display evidence only. It grants nothing and blocks nothing, and
whenever the evidence is missing, old, partial or unreadable the word is
``unknown`` - never ``not_ready`` - so the screen keeps plain '연결됨'.
"""
from __future__ import annotations

import inspect
from datetime import datetime
from typing import Any

from padiem_ai_core.pc_helper_ready import HelperReadyError, validate_helper_ready

#: The same bound the Mesh presence receipt is trusted for. The executor sends
#: an unchanged observation again every minute, so a healthy lane is never older.
HELPER_READY_MAX_AGE_SECONDS = 180

READY = "ready"
NOT_READY = "not_ready"
UNKNOWN = "unknown"
REASON_HELPER_MISSING = "helper_missing"
REASON_NO_USER_SESSION = "no_user_session"
REASON_HELPER_STOPPED = "helper_stopped"


def unknown_command_ready() -> dict[str, Any]:
    """The three list fields when nothing can be said about this PC."""
    return {"command_ready": UNKNOWN, "command_ready_reason": None,
            "last_user_session_failure_at": None}


def _received(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def command_ready_view(row: Any, *, device_id: str, now: datetime) -> dict[str, Any]:
    """One stored readiness row -> ``ready`` / ``not_ready`` / ``unknown``.

    * the helper's pipe is open -> ``ready``;
    * the helper's task is not there -> ``not_ready`` (the executor reads the
      same task file before it can reach the helper at all);
    * the pipe is not open -> ``not_ready``, and the reason says whether nobody
      is signed in or the helper is simply not running;
    * anything else, including a value the PC could not read -> ``unknown``.
    """
    if not isinstance(row, dict) or row.get("device_id") != device_id:
        return unknown_command_ready()
    stamp = row.get("received_at")
    received = _received(stamp)
    if received is None:
        return unknown_command_ready()
    age = (now - received).total_seconds()
    if not 0 <= age <= HELPER_READY_MAX_AGE_SECONDS:
        return unknown_command_ready()
    try:
        state = validate_helper_ready(row.get("state"))
    except HelperReadyError:
        # A row from a different version of the shape says nothing.
        return unknown_command_ready()
    if state["pipe_open"] is True:
        return {"command_ready": READY, "command_ready_reason": None,
                "last_user_session_failure_at": None}
    reason: str | None
    if state["task_present"] is False:
        reason = REASON_HELPER_MISSING
    elif state["pipe_open"] is False:
        reason = {False: REASON_NO_USER_SESSION,
                  True: REASON_HELPER_STOPPED}.get(state["interactive_session"])
    else:
        return unknown_command_ready()
    return {"command_ready": NOT_READY, "command_ready_reason": reason,
            "last_user_session_failure_at": stamp}


async def load_command_ready(store: Any, *, device_id: str, now: datetime) -> dict[str, Any]:
    """Read one PC's row through the store's public call; any fault is ``unknown``."""
    loader = getattr(store, "load_helper_ready", None)
    if not callable(loader):
        return unknown_command_ready()
    try:
        row = loader(device_id=device_id)
        if inspect.isawaitable(row):
            row = await row
    except Exception:
        return unknown_command_ready()
    return command_ready_view(row, device_id=device_id, now=now)


__all__ = [
    "HELPER_READY_MAX_AGE_SECONDS", "NOT_READY", "READY", "REASON_HELPER_MISSING",
    "REASON_HELPER_STOPPED", "REASON_NO_USER_SESSION", "UNKNOWN",
    "command_ready_view", "load_command_ready", "unknown_command_ready",
]
