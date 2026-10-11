"""#4194: opt-in Engine Agent lease control plane backed by provisioned D1.

No schema creation at request time, no process-local fallback and no HTTP route.
Only server-resolved owner/subject/run fingerprint may use this adapter.
Failure to write/read D1 means NO dispatch, never an implicit retry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import inspect
import re
from typing import Any, Callable

from padiem_ai_core.agent_durable_lease import AgentDurableLeaseError, AgentRunLease

_TABLE = "padiem_engine_agent_runs_v1"
_SERVER_RUN_ID = re.compile(r"arun_[0-9a-f]{32}\Z")
_OWNER_SCOPE = re.compile(r"scope_[0-9a-f]{64}\Z")
_STATES = frozenset(
    {"running", "paused", "awaiting_approval", "completed", "failed", "cancelled", "needs_review"}
)
_CANCELLABLE_STATES = ("running", "paused", "awaiting_approval")
DEFAULT_EXPIRED_SWEEP_LIMIT = 500
MAX_EXPIRED_SWEEP_LIMIT = 2_000


def _server_run_id(run_id: str) -> str:
    """Only a server-issued Agent run identity may address a durable run."""
    if not isinstance(run_id, str) or not _SERVER_RUN_ID.fullmatch(run_id):
        raise AgentDurableLeaseError("server-issued Agent run identity required")
    return run_id


def _owner_scope(owner_scope: str) -> str:
    if not isinstance(owner_scope, str) or not _OWNER_SCOPE.fullmatch(owner_scope):
        raise AgentDurableLeaseError("trusted owner scope required")
    return owner_scope


def agent_run_owner_scope(app_id: str, subject_id: str) -> str:
    """Single owner-scope derivation shared by run dispatch and run control.

    Both the execution path and the status/cancel/recovery control path must
    derive the same scope from server-resolved identity. Keeping one function
    prevents an authorization drift that would let one actor's control request
    address another actor's run.
    """
    if not isinstance(app_id, str) or not app_id:
        raise AgentDurableLeaseError("trusted application identity required")
    if not isinstance(subject_id, str) or not subject_id:
        raise AgentDurableLeaseError("trusted subject identity required")
    return "scope_" + hashlib.sha256(
        (app_id + ":" + subject_id).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class AgentRunStatusView:
    """Non-disclosing owner-scoped run state; never carries payload or identity."""

    run_id: str
    state: str
    epoch: int
    checkpoint_step: int
    side_effect_uncertain: bool
    lease_live: bool
    heartbeat_age_seconds: int

    @property
    def dispatch_fenced(self) -> bool:
        """The lease guard refuses the next dispatch (cancel/terminal/expiry)."""
        return self.state != "running" or not self.lease_live

    @property
    def requires_reconciliation(self) -> bool:
        """Cancelled/failed uncertainty is never reported as a clean rollback."""
        return self.side_effect_uncertain and self.state in {"cancelled", "needs_review"}

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "state": self.state,
            "epoch": self.epoch,
            "checkpoint_step": self.checkpoint_step,
            "side_effect_uncertain": self.side_effect_uncertain,
            "lease_live": self.lease_live,
            "heartbeat_age_seconds": self.heartbeat_age_seconds,
            "dispatch_fenced": self.dispatch_fenced,
            "requires_reconciliation": self.requires_reconciliation,
        }


@dataclass(frozen=True, slots=True)
class AgentRunCancelOutcome:
    """Result of one owner-scoped cancel attempt; ``changed=False`` is idempotent."""

    state: AgentRunStatusView
    changed: bool

    @property
    def requires_reconciliation(self) -> bool:
        return self.state.requires_reconciliation

    def to_public_dict(self) -> dict[str, Any]:
        payload = dict(self.state.to_public_dict())
        payload["changed"] = self.changed
        return payload


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
        try:
            result = await _await(self._db.prepare(sql).bind(*args).run())
        except Exception:
            raise AgentDurableLeaseError("D1 Agent lease write unavailable") from None
        return _changes(result)

    async def _first(self, sql: str, *args: Any) -> dict[str, Any] | None:
        try:
            value = await _await(self._db.prepare(sql).bind(*args).first())
        except Exception:
            raise AgentDurableLeaseError("D1 Agent lease read unavailable") from None
        return dict(value) if isinstance(value, dict) else None

    async def _count(self, sql: str, *args: Any) -> int:
        """Bounded aggregate read; unknown or negative counts are fail-closed."""
        row = await self._first(sql, *args)
        if row is None:
            raise AgentDurableLeaseError("D1 Agent lease count unavailable")
        value = row.get("n")
        if type(value) is not int or value < 0:
            raise AgentDurableLeaseError("D1 Agent lease count unavailable")
        return value

    async def _bulk(self, sql: str, *args: Any) -> int:
        """Bulk CAS write; requires exact D1 changes metadata, never a guess."""
        try:
            result = await _await(self._db.prepare(sql).bind(*args).run())
        except Exception:
            raise AgentDurableLeaseError("D1 Agent lease write unavailable") from None
        if isinstance(result, dict) and result.get("success") is not True:
            raise AgentDurableLeaseError("D1 Agent lease write unavailable")
        meta = result.get("meta") if isinstance(result, dict) else getattr(result, "meta", None)
        if meta is None:
            raise AgentDurableLeaseError("D1 Agent lease write unavailable")
        changes = meta.get("changes") if isinstance(meta, dict) else getattr(meta, "changes", None)
        if type(changes) is not int or changes < 0:
            raise AgentDurableLeaseError("D1 Agent lease write unavailable")
        return changes

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

    @staticmethod
    def _server_run(run_id: str) -> str:
        # This identifier must originate in the trusted initial Agent Worker,
        # and may only be obtained from a server-persisted ApprovalPause.
        if not isinstance(run_id, str) or not _SERVER_RUN_ID.fullmatch(run_id):
            raise AgentDurableLeaseError("server-issued Agent run identity required")
        return run_id

    async def resume_approved_pause(
        self, *, run_id: str, owner_scope: str, worker_id: str, completed_step: int,
        lease_seconds: int = 120,
    ) -> AgentRunLease:
        """CAS an approved, already-fenced pause into one fresh executor epoch.

        Continuation resolve + decision verification + claim must precede this.
        This is not automatic recovery of uncertain Tool/provider effects.
        """
        run_id = self._server_run(run_id)
        if type(completed_step) is not int or not 0 <= completed_step <= 63:
            raise AgentDurableLeaseError("invalid approval checkpoint")
        period = self._seconds(lease_seconds)
        if not isinstance(owner_scope, str) or not re.fullmatch(r"scope_[0-9a-f]{64}", owner_scope):
            raise AgentDurableLeaseError("invalid trusted owner scope")
        if not isinstance(worker_id, str) or not re.fullmatch(r"eng_[0-9a-f]{24}", worker_id):
            raise AgentDurableLeaseError("invalid trusted resume worker")
        now = self._now()
        ok = await self._run(
            f"UPDATE {_TABLE} SET worker_id=?,epoch=epoch+1,status='running',"
            "heartbeat_at=?,lease_until=? WHERE run_id=? AND owner_scope=? "
            "AND status='awaiting_approval' AND checkpoint_step=?",
            worker_id, now, now + period, run_id, owner_scope, completed_step,
        )
        if not ok:
            raise AgentDurableLeaseError("Agent approval lease unavailable or already consumed")
        row = await self._first(
            f"SELECT owner_scope,request_fingerprint,epoch,worker_id,status,checkpoint_step "
            f"FROM {_TABLE} WHERE run_id=?", run_id,
        )
        if (row is None or row.get("worker_id") != worker_id
                or row.get("status") != "running"
                or type(row.get("epoch")) is not int
                or row.get("checkpoint_step") != completed_step):
            raise AgentDurableLeaseError("Agent approval fencing readback unavailable")
        return AgentRunLease(
            run_id, row["owner_scope"], row["request_fingerprint"], worker_id, row["epoch"],
        )

    async def cancel_awaiting_approval(self, *, run_id: str, completed_step: int) -> bool:
        """Revoke only the exact server-issued approval-pause lease, not other runs."""
        run_id = self._server_run(run_id)
        if type(completed_step) is not int or not 0 <= completed_step <= 63:
            raise AgentDurableLeaseError("invalid approval checkpoint")
        return await self._run(
            f"UPDATE {_TABLE} SET status='cancelled',epoch=epoch+1 "
            "WHERE run_id=? AND status='awaiting_approval' AND checkpoint_step=?",
            run_id, completed_step,
        )

    @staticmethod
    def _status_view(run_id: str, row: dict[str, Any], *, now: float) -> AgentRunStatusView:
        state = row.get("status")
        epoch = row.get("epoch")
        step = row.get("checkpoint_step")
        uncertain = row.get("side_effect_uncertain")
        lease_until = row.get("lease_until")
        heartbeat = row.get("heartbeat_at")
        if (
            state not in _STATES
            or type(epoch) is not int
            or epoch < 1
            or type(step) is not int
            or not 0 <= step <= 64
            or type(uncertain) is not int
            or uncertain not in (0, 1)
            or not isinstance(lease_until, (int, float))
            or isinstance(lease_until, bool)
            or not isinstance(heartbeat, (int, float))
            or isinstance(heartbeat, bool)
        ):
            raise AgentDurableLeaseError("D1 Agent lease readback unavailable")
        return AgentRunStatusView(
            run_id=run_id,
            state=state,
            epoch=epoch,
            checkpoint_step=step,
            side_effect_uncertain=uncertain == 1,
            lease_live=float(lease_until) > now,
            heartbeat_age_seconds=max(0, int(now - float(heartbeat))),
        )

    async def status_for_owner(
        self, *, run_id: str, owner_scope: str,
    ) -> AgentRunStatusView | None:
        """Owner-scoped read of one already-issued run. No payload, no identity.

        The caller can only reach a run whose server-derived owner scope matches;
        an unknown run and a foreign run are indistinguishable (``None``).
        """
        _server_run_id(run_id)
        _owner_scope(owner_scope)
        now = self._now()
        row = await self._first(
            f"SELECT status,epoch,checkpoint_step,side_effect_uncertain,"
            f"lease_until,heartbeat_at FROM {_TABLE} "
            "WHERE run_id=? AND owner_scope=?",
            run_id, owner_scope,
        )
        if row is None:
            return None
        return self._status_view(run_id, row, now=now)

    async def cancel_for_owner(
        self, *, run_id: str, owner_scope: str,
    ) -> AgentRunCancelOutcome | None:
        """Owner-scoped cancel of a running/paused already-issued run.

        Honest safety contract:
        - a run that already left the pre-dispatch safety boundary
          (``side_effect_uncertain=1``) and is still executing is fenced to
          ``needs_review``, never reported as a clean rollback;
        - a paused/awaiting-approval run keeps the existing ``cancelled`` state
          used by the approval-pause cancel flow;
        - an already terminal run is reported unchanged (idempotent retry) and
          is never overwritten;
        - a concurrent completion wins the CAS and is reported as-is.
        No Tool/provider work is replayed, rolled back or re-dispatched here.
        """
        current = await self.status_for_owner(run_id=run_id, owner_scope=owner_scope)
        if current is None:
            return None
        if current.state not in _CANCELLABLE_STATES:
            return AgentRunCancelOutcome(state=current, changed=False)
        if current.state == "running" and current.side_effect_uncertain:
            changed = await self._cancel_cas(
                run_id=run_id, owner_scope=owner_scope, new_state="needs_review",
                require_running_uncertain=True,
            )
        else:
            changed = await self._cancel_cas(
                run_id=run_id, owner_scope=owner_scope, new_state="cancelled",
                require_running_uncertain=False,
            )
        final = await self.status_for_owner(run_id=run_id, owner_scope=owner_scope)
        if final is None:
            raise AgentDurableLeaseError("D1 Agent lease readback unavailable")
        return AgentRunCancelOutcome(state=final, changed=changed)

    async def _cancel_cas(
        self, *, run_id: str, owner_scope: str, new_state: str,
        require_running_uncertain: bool,
    ) -> bool:
        """Single atomic fence. ``False`` means a race already resolved state."""
        _server_run_id(run_id)
        _owner_scope(owner_scope)
        if new_state not in ("cancelled", "needs_review"):
            raise AgentDurableLeaseError("invalid Agent run cancel state")
        if require_running_uncertain:
            condition = "status='running' AND side_effect_uncertain=1"
        else:
            condition = "status IN ('running','paused','awaiting_approval')"
        return await self._run(
            f"UPDATE {_TABLE} SET status=?,epoch=epoch+1 "
            f"WHERE run_id=? AND owner_scope=? AND {condition}",
            new_state, run_id, owner_scope,
        )

    async def count_expired_runs(self, *, owner_scope: str | None = None) -> int:
        """Bound the sweep target before any write; never counts live leases.

        With ``owner_scope`` the count is restricted to that trusted owner, so a
        recovery caller can only ever affect the runs it owns.
        """
        if owner_scope is None:
            return await self._count(
                f"SELECT COUNT(*) AS n FROM {_TABLE} "
                "WHERE status='running' AND lease_until<=?",
                self._now(),
            )
        _owner_scope(owner_scope)
        return await self._count(
            f"SELECT COUNT(*) AS n FROM {_TABLE} "
            "WHERE status='running' AND lease_until<=? AND owner_scope=?",
            self._now(), owner_scope,
        )

    async def quarantine_expired(
        self, *, limit: int = DEFAULT_EXPIRED_SWEEP_LIMIT, owner_scope: str | None = None,
    ) -> int:
        """Never auto-replay a run that might have reached a Tool/provider.

        Only an expired ``running`` lease is moved to ``needs_review``; live
        leases, terminal states and concurrent heartbeats are untouched, and a
        repeated call is a no-op. The row remains the only source of truth, so
        this recovery path cannot re-execute Agent or Tool work. Passing a
        trusted ``owner_scope`` confines the sweep to that owner's runs.
        """
        if type(limit) is not int or not 1 <= limit <= MAX_EXPIRED_SWEEP_LIMIT:
            raise AgentDurableLeaseError("invalid expired sweep limit")
        scope_filter = ""
        args: list[Any] = [self._now()]
        if owner_scope is not None:
            _owner_scope(owner_scope)
            scope_filter = " AND owner_scope=?"
            args.append(owner_scope)
        args.append(limit)
        return await self._bulk(
            f"UPDATE {_TABLE} SET status='needs_review',epoch=epoch+1 "
            "WHERE run_id IN (SELECT run_id FROM " + _TABLE + " "
            "WHERE status='running' AND lease_until<=?" + scope_filter + " "
            "ORDER BY lease_until ASC LIMIT ?)",
            *args,
        )

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
