"""#8359 step 1: select managed PCs for unattended maintenance and record it.

Selection and bookkeeping only. This module never dispatches a command and
never writes to a PC; the SYSTEM update lane is a separate follow-up. Off
unless the deployment sets the switch, and even then the caller decides what
to do with the selection.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .d1_rows import rows_from_result
from .pc_helper_rollout import offer
from .pc_helper_update_policy import version_parts

AUTO_UPDATE_SWITCH = "PADIEM_PC_HELPER_AUTO_UPDATE_ENABLED"
MAX_FAILURES = 2


def auto_update_enabled(env: Any) -> bool:
    getter = getattr(env, "get", None)
    value = getter(AUTO_UPDATE_SWITCH, "") if callable(getter) else ""
    return isinstance(value, str) and value.strip().lower() in {"1", "true", "on"}


def needs_update(observation: Any, *, source_sha256: str, min_version: str) -> bool:
    """Missing evidence, wrong source, no updater task or an old release needs work."""
    if not isinstance(observation, dict):
        return True
    state = observation.get("state") if isinstance(observation.get("state"), dict) else {}
    if state.get("updater_source_sha256") != source_sha256:
        return True
    if not state.get("updater_task_present"):
        return True
    version = observation.get("helper_version") or state.get("helper_version")
    current, minimum = version_parts(version), version_parts(min_version)
    if current is None:
        return True
    return minimum is not None and current < minimum


def stage_allows(rollout: Any, *, device_id: str, source_sha256: str) -> bool:
    """The staged rollout decides which managed PC may be offered this source."""
    if not isinstance(rollout, dict):
        return False
    offered = offer(rollout, device_id=device_id, managed=True)
    return isinstance(offered, dict) and offered.get("sha256") == source_sha256


@dataclass(frozen=True)
class Attempt:
    count: int
    stopped: bool = False
    reason: str | None = None


def select(
    *, devices: Any, managed: Any, observations: Mapping[str, Any], rollout: Any,
    source_sha256: str, min_version: str, attempts: Mapping[tuple[str, str], Attempt],
) -> list[str]:
    """Managed PCs that still need one first selection for this source."""
    managed_ids = {item for item in managed if isinstance(item, str) and item} if managed else set()
    out: list[str] = []
    for device in devices if isinstance(devices, (list, tuple, set)) else ():
        if not isinstance(device, str) or device not in managed_ids:
            continue
        key = (device, source_sha256)
        previous = attempts.get(key)
        if previous is not None:
            continue
        if not stage_allows(rollout, device_id=device, source_sha256=source_sha256):
            continue
        if needs_update(observations.get(device), source_sha256=source_sha256,
                        min_version=min_version):
            out.append(device)
    return out


def failure_attempt(count: int, *, reason: str | None = None) -> Attempt:
    """One more failed attempt stops the lane after the bounded limit."""
    total = count + 1
    return Attempt(count=total, stopped=total >= MAX_FAILURES, reason=reason)


class D1PcHelperAutoAttemptStore:
    """One bounded row per (PC, source) so a release is never retried blindly."""

    def __init__(self, db: Any):
        if db is None or not callable(getattr(db, "prepare", None)):
            raise ValueError("auto-update attempt binding missing")
        self._db = db

    async def load_all(self, *, source_sha256: str) -> dict[tuple[str, str], Attempt]:
        result = await self._db.prepare(
            "SELECT device_id, source_sha256, attempts, stopped, last_reason "
            "FROM pc_helper_auto_attempts WHERE source_sha256=?"
        ).bind(source_sha256).run()
        out: dict[tuple[str, str], Attempt] = {}
        for raw in rows_from_result(result):
            row = dict(raw.to_py() if callable(getattr(raw, "to_py", None)) else raw)
            out[(row["device_id"], row["source_sha256"])] = Attempt(
                count=int(row["attempts"]), stopped=bool(row["stopped"]),
                reason=row.get("last_reason"),
            )
        return out

    async def record(self, *, device_id: str, source_sha256: str, attempt: Attempt,
                     now: str) -> bool:
        try:
            await self._db.prepare(
                "INSERT INTO pc_helper_auto_attempts "
                "(device_id, source_sha256, attempts, stopped, last_reason, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(device_id, source_sha256) DO UPDATE SET "
                "attempts=excluded.attempts, stopped=excluded.stopped, "
                "last_reason=excluded.last_reason, updated_at=excluded.updated_at"
            ).bind(device_id, source_sha256, attempt.count, int(attempt.stopped),
                   attempt.reason, now).run()
            return True
        except Exception:
            return False


async def record_selection(
    state: Any, *, device_id: str, source_sha256: str, now: str,
    alert: Any = None, audit: Any = None,
) -> bool:
    """Remember that this PC/source pair was selected, once."""
    store = getattr(state, "pc_helper_auto_attempt_store", None)
    if store is None:
        return False
    existing = (await store.load_all(source_sha256=source_sha256)).get((device_id, source_sha256))
    if existing is not None:
        return False
    saved = await store.record(device_id=device_id, source_sha256=source_sha256,
                               attempt=Attempt(count=0, reason="selected"), now=now)
    if not saved:
        return False
    if callable(alert):
        await alert(device_id, "helper_auto_update_selected")
    if callable(audit):
        await audit("helper_auto_update_selected", device_id)
    return True


async def record_failure(
    state: Any, *, device_id: str, source_sha256: str, reason: str, now: str,
    alert: Any = None, audit: Any = None,
) -> Attempt | None:
    """Count one failure, alert/audit it, and stop the lane after the limit."""
    store = getattr(state, "pc_helper_auto_attempt_store", None)
    if store is None:
        return None
    attempts = await store.load_all(source_sha256=source_sha256)
    previous = attempts.get((device_id, source_sha256), Attempt(count=0))
    if previous.stopped:
        return previous
    attempt = failure_attempt(previous.count, reason=reason)
    if not await store.record(device_id=device_id, source_sha256=source_sha256,
                              attempt=attempt, now=now):
        return None
    action = "helper_auto_update_stopped" if attempt.stopped else "helper_auto_update_failed"
    if callable(alert):
        await alert(device_id, action)
    if callable(audit):
        await audit(action, device_id)
    return attempt
