"""#7975 — read the newest user-mode dispatch outcome for each owned device.

This lives in its own module instead of adding a method to the frozen store
classes (#7813 public-method contracts). It uses only the metadata already in
``oracle_mesh_dispatch`` and never selects command text, nonce hashes or result
bodies. No PC command is sent and no new table is written.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .history_text import _iso

USER_MODE_WINDOW_HOURS = 24


async def latest_user_mode_results_for_owner(
    store: Any, *, user_id: str, device_ids: list[str],
    window_hours: int = USER_MODE_WINDOW_HOURS,
) -> dict[str, dict[str, Any]]:
    """One owner-scoped query for a whole device list.

    The agent reports a user-session refusal as
    ``termination='not_executed', exit_code=1`` in a user-mode dispatch, so the
    executor's termination field is the SQL-visible signal. The full error code
    lives in the private result original and is deliberately not read here.
    A store fault keeps the answer empty ('unknown') instead of guessing.
    """
    if not isinstance(user_id, str) or not user_id:
        return {}
    if not isinstance(device_ids, list) or not device_ids:
        return {}
    if any(not isinstance(device, str) or not device for device in device_ids):
        return {}
    if not isinstance(window_hours, int) or isinstance(window_hours, bool) or window_hours < 1:
        return {}
    placeholders = ",".join("?" for _ in device_ids)
    since = _iso(datetime.now(timezone.utc) - timedelta(hours=window_hours))
    try:
        rows = await store._all(
            "WITH user_mode_rows AS ("
            " SELECT device_id, created_at, termination, exit_code,"
            " COALESCE(user_mode,0) AS user_mode"
            " FROM oracle_mesh_dispatch WHERE user_id=? AND created_at>=?"
            "), ranked AS ("
            " SELECT device_id, created_at, termination, exit_code,"
            " ROW_NUMBER() OVER (PARTITION BY device_id"
            " ORDER BY created_at DESC, device_id DESC) AS rn"
            " FROM user_mode_rows WHERE user_mode=1"
            ") SELECT device_id, created_at, termination, exit_code FROM ranked"
            " WHERE rn=1 AND device_id IN (" + placeholders + ")",
            user_id, since, *device_ids,
        )
    except Exception:
        return {}
    latest: dict[str, dict[str, Any]] = {}
    for row in rows or ():
        device = row.get("device_id")
        if not isinstance(device, str):
            continue
        latest[device] = {
            "termination": row.get("termination"),
            "exit_code": row.get("exit_code"),
            "created_at": row.get("created_at"),
        }
    return latest
