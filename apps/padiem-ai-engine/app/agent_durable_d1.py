"""#4194: opt-in Engine Agent lease control plane backed by provisioned D1.

No schema creation at request time, no process-local fallback and no HTTP route.
Only server-resolved owner/subject/run fingerprint may use this adapter.
Failure to write/read D1 means NO dispatch, never an implicit retry.
"""
from __future__ import annotations

from datetime import datetime, timezone
import inspect
from typing import Any, Callable

from padiem_ai_core.agent_durable_lease import AgentDurableLeaseError, AgentRunLease

_TABLE = "padiem_engine_agent_runs_v1"


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _changes(result: Any) -> bool:
    """Require exact D1 changes metadata; unknown result is fail-closed."""
    meta = result.get("meta") if isinstance(result, dict) else getattr(result, "meta", None)
    if isinstance(result, dict) and result.get("success") is not True:
        return False
    if meta is None:
        return False
    n = meta.get("changes") if isinstance(meta, dict) else getattr(meta, "changes", None)
    return type(n) is int and n == 1


class D1AgentRunLedger:
    """Cloudflare D1 run lease, separate from Core's private SQLite host ledger."""

    def __init__(self, binding: Any, *, clock: Callable[[], datetime] | None = None) -> None:
        if binding is None or not callable(getattr(binding, "prepare", None)):
            raise ValueError("Engine Agent ledger requires an actual D1 binding")
        self._db = binding
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> float:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise AgentDurableLeaseError("aware clock required")
        return value.timestamp()

    @staticmethod
    def _seconds(value: int) -> int:
        if type(value) is not int or not 1 <= value <= 3600:
            raise AgentDurableLeaseError("invalid lease duration")
        return value

    async def _run(self, sql: str, *args: Any) -> bool:
        result = await _await(self._db.prepare(sql).bind(*args).run())
        return _changes(result)

    async def _first(self, sql: str, *args: Any) -> dict[str, Any] | None:
        value = await _await(self._db.prepare(sql).bind(*args).first())
        return dict(value) if isinstance(value, dict) else None

    async def start(
        self, *, run_id: str, owner_scope: str, request_fingerprint: str,
        worker_id: str, lease_seconds: int = 120,
    ) -> AgentRunLease:
        handle = AgentRunLease(run_id, owner_scope, request_fingerprint, worker_id, 1)
        now = self._now()
        period = self._seconds(lease_seconds)
        ok = await self._run(
            f"INSERT INTO {_TABLE} "
            "(run_id,owner_scope,request_fingerprint,worker_id,epoch,status,"
            "lease_until,heartbeat_at,checkpoint_step,side_effect_uncertain) "
            "VALUES (?,?,?,?,1,'running',?,?,0,0) ON CONFLICT(run_id) DO NOTHING",
            handle.run_id, handle.owner_scope, handle.request_fingerprint,
            handle.worker_id, now + period, now,
        )
        if not ok:
            raise AgentDurableLeaseError("run already exists or D1 lease unavailable")
        return handle

    @staticmethod
    def _where() -> str:
        return ("run_id=? AND owner_scope=? AND request_fingerprint=? "
                "AND worker_id=? AND epoch=? AND status='running' AND lease_until>?")

    def _args(self, handle: AgentRunLease, now: float) -> tuple[Any, ...]:
        if not isinstance(handle, AgentRunLease):
            raise AgentDurableLeaseError("trusted lease required")
        return (handle.run_id, handle.owner_scope, handle.request_fingerprint,
                handle.worker_id, handle.epoch, now)

    async def is_active(self, handle: AgentRunLease) -> bool:
        now = self._now()
        row = await self._first(
            f"SELECT epoch FROM {_TABLE} WHERE " + self._where(),
            *self._args(handle, now),
        )
        return row is not None and type(row.get("epoch")) is int and row["epoch"] == handle.epoch

    async def begin_execution(self, handle: AgentRunLease) -> bool:
        """Atomic pre-dispatch side-effect uncertainty; no second executor claim."""
        now = self._now()
        return await self._run(
            f"UPDATE {_TABLE} SET side_effect_uncertain=1 WHERE " + self._where(),
            *self._args(handle, now),
        )

    def execution_guard(self, handle: AgentRunLease) -> Callable[[], Any]:
        if not isinstance(handle, AgentRunLease):
            raise AgentDurableLeaseError("trusted lease required")
        return lambda: self.begin_execution(handle)

    async def heartbeat(self, handle: AgentRunLease, *, lease_seconds: int = 120) -> bool:
        now = self._now()
        period = self._seconds(lease_seconds)
        return await self._run(
            f"UPDATE {_TABLE} SET heartbeat_at=?,lease_until=? WHERE " + self._where(),
            now, now + period, *self._args(handle, now),
        )

    async def checkpoint(
        self, handle: AgentRunLease, *, completed_step: int,
        side_effect_uncertain: bool = True,
    ) -> bool:
        if type(completed_step) is not int or not 0 <= completed_step <= 64:
            raise AgentDurableLeaseError("invalid checkpoint step")
        if type(side_effect_uncertain) is not bool:
            raise AgentDurableLeaseError("invalid side effect marker")
        now = self._now()
        return await self._run(
            f"UPDATE {_TABLE} SET checkpoint_step=?, "
            "side_effect_uncertain=MAX(side_effect_uncertain,?) WHERE "
            + self._where() + " AND checkpoint_step<=?",
            completed_step, int(side_effect_uncertain), *self._args(handle, now),
            completed_step,
        )

    async def finish(self, handle: AgentRunLease, *, state: str) -> bool:
        if state not in ("completed", "failed", "awaiting_approval"):
            raise AgentDurableLeaseError("invalid terminal status")
        now = self._now()
        return await self._run(
            f"UPDATE {_TABLE} SET status=?,epoch=epoch+1 WHERE " + self._where(),
            state, *self._args(handle, now),
        )

    async def cancel(
        self, *, run_id: str, owner_scope: str, request_fingerprint: str,
    ) -> bool:
        # Validate all externally supplied selectors against the Core contract.
        AgentRunLease(run_id, owner_scope, request_fingerprint, "cancel", 1)
        return await self._run(
            f"UPDATE {_TABLE} SET status='cancelled',epoch=epoch+1 "
            "WHERE run_id=? AND owner_scope=? AND request_fingerprint=? "
            "AND status IN ('running','paused','awaiting_approval')",
            run_id, owner_scope, request_fingerprint,
        )

    async def pause_before_work(self, handle: AgentRunLease) -> bool:
        now = self._now()
        return await self._run(
            f"UPDATE {_TABLE} SET status='paused',epoch=epoch+1 WHERE "
            + self._where() + " AND checkpoint_step=0 AND side_effect_uncertain=0",
            *self._args(handle, now),
        )

    async def resume_prework(
        self, *, run_id: str, owner_scope: str, request_fingerprint: str,
        worker_id: str, lease_seconds: int = 120,
    ) -> AgentRunLease | None:
        AgentRunLease(run_id, owner_scope, request_fingerprint, worker_id, 1)
        now = self._now()
        period = self._seconds(lease_seconds)
        ok = await self._run(
            f"UPDATE {_TABLE} SET worker_id=?,epoch=epoch+1,status='running',"
            "heartbeat_at=?,lease_until=? "
            "WHERE run_id=? AND owner_scope=? AND request_fingerprint=? "
            "AND status='paused' AND checkpoint_step=0 AND side_effect_uncertain=0",
            worker_id, now, now + period, run_id, owner_scope, request_fingerprint,
        )
        if not ok:
            return None
        row = await self._first(f"SELECT epoch FROM {_TABLE} WHERE run_id=?", run_id)
        if row is None or type(row.get("epoch")) is not int:
            raise AgentDurableLeaseError("D1 fencing readback unavailable")
        return AgentRunLease(run_id, owner_scope, request_fingerprint, worker_id, row["epoch"])

    async def quarantine_expired(self) -> None:
        """Never auto-replay a run that might have reached a Tool/provider."""
        await _await(self._db.prepare(
            f"UPDATE {_TABLE} SET status='needs_review',epoch=epoch+1 "
            "WHERE status='running' AND lease_until<=?"
        ).bind(self._now()).run())

    async def status(
        self, *, run_id: str, owner_scope: str, request_fingerprint: str,
    ) -> tuple[str, int, int] | None:
        AgentRunLease(run_id, owner_scope, request_fingerprint, "read", 1)
        row = await self._first(
            f"SELECT status,epoch,checkpoint_step FROM {_TABLE} "
            "WHERE run_id=? AND owner_scope=? AND request_fingerprint=?",
            run_id, owner_scope, request_fingerprint,
        )
        return (str(row["status"]), int(row["epoch"]), int(row["checkpoint_step"])) if row else None


D1_AGENT_RUN_LEDGER_AUTO_REPLAYS_TOOLS = False
D1_AGENT_RUN_LEDGER_GRANTS_APPROVAL = False
D1_AGENT_RUN_LEDGER_HAS_PUBLIC_HTTP_ROUTE = False
