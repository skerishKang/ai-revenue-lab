"""Server-injected durable Agent run leases and fail-closed checkpoint metadata.

This is an opt-in *control plane*, not an autonomous rescheduler or approval
issuer. It holds no user prompt, provider credentials, tool arguments or output.
The authorized host is responsible for authenticating owner_scope, binding the
request fingerprint, and injecting this ledger into Agent execution. SQLite
requires persistent private host media; Cloudflare Workers need a separate
transactional D1-backed adapter, never an in-memory pretend-persistent store.

An expired in-flight run is UNCERTAIN, never automatically replayed. A paused
run is claimable only at step 0 (before any model/tool side effects). Resuming a
later step requires a future separately verified full-state checkpoint adapter.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
from typing import Callable, Iterator

_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_LEASE_MIN_SECONDS = 1
_LEASE_MAX_SECONDS = 3600


class AgentDurableLeaseError(ValueError):
    """Safe, non-disclosing lease contract error."""


def _ref(value: str) -> str:
    if type(value) is not str or not _REF.fullmatch(value):
        raise AgentDurableLeaseError("invalid trusted run reference")
    return value


def _fingerprint(value: str) -> str:
    if type(value) is not str or not _SHA.fullmatch(value):
        raise AgentDurableLeaseError("invalid request fingerprint")
    return value


def _seconds(value: int) -> int:
    if type(value) is not int or not _LEASE_MIN_SECONDS <= value <= _LEASE_MAX_SECONDS:
        raise AgentDurableLeaseError("invalid lease duration")
    return value


@dataclass(frozen=True, slots=True)
class AgentRunLease:
    """Fencing handle minted by a trusted host; NOT an authorization token."""

    run_id: str
    owner_scope: str
    request_fingerprint: str
    worker_id: str
    epoch: int

    def __post_init__(self) -> None:
        for value in (self.run_id, self.owner_scope, self.worker_id):
            _ref(value)
        _fingerprint(self.request_fingerprint)
        if type(self.epoch) is not int or self.epoch < 1:
            raise AgentDurableLeaseError("invalid fencing epoch")


class SQLiteAgentDurableRunLedger:
    """Private durable single-writer state, with SQLite atomic fencing.

    An authenticated host MUST derive owner_scope and request_fingerprint from
    server-issued identity, not from user-controlled document/model output.
    The ledger never creates a Tool approval or authorizes an external action.
    """

    def __init__(
        self,
        *,
        database_path: str | Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = Path(database_path)
        if not self._path.parent.is_dir() or self._path.is_symlink():
            raise AgentDurableLeaseError("existing private storage directory required")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS agent_durable_lease_v1 (
                run_id TEXT PRIMARY KEY,
                owner_scope TEXT NOT NULL,
                request_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                worker_id TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                lease_until REAL NOT NULL,
                heartbeat_at REAL NOT NULL,
                checkpoint_step INTEGER NOT NULL DEFAULT 0,
                side_effect_uncertain INTEGER NOT NULL DEFAULT 0
            )""")

    def _now(self) -> float:
        v = self._clock()
        if not isinstance(v, datetime) or v.tzinfo is None or v.utcoffset() is None:
            raise AgentDurableLeaseError("aware server clock required")
        return v.timestamp()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(str(self._path), timeout=5, isolation_level=None)) as db:
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def start(
        self, *, run_id: str, owner_scope: str, request_fingerprint: str,
        worker_id: str, lease_seconds: int = 60,
    ) -> AgentRunLease:
        handle = AgentRunLease(run_id, owner_scope, request_fingerprint, worker_id, 1)
        expiry = self._now() + _seconds(lease_seconds)
        try:
            with self._db() as db:
                db.execute(
                    "INSERT INTO agent_durable_lease_v1 "
                    "(run_id,owner_scope,request_fingerprint,status,worker_id,"
                    "epoch,lease_until,heartbeat_at) VALUES (?,?,?,'running',?,1,?,?)",
                    (run_id, owner_scope, request_fingerprint, worker_id,
                     expiry, expiry - lease_seconds),
                )
        except sqlite3.IntegrityError:
            raise AgentDurableLeaseError("run already exists") from None
        return handle

    def _active_clause(self) -> str:
        return ("run_id=? AND owner_scope=? AND request_fingerprint=? "
                "AND worker_id=? AND epoch=? AND status='running' "
                "AND lease_until>?")

    @staticmethod
    def _handle_tuple(handle: AgentRunLease, now: float) -> tuple[object, ...]:
        if not isinstance(handle, AgentRunLease):
            raise AgentDurableLeaseError("trusted lease handle required")
        return (handle.run_id, handle.owner_scope, handle.request_fingerprint,
                handle.worker_id, handle.epoch, now)

    def is_active(self, handle: AgentRunLease) -> bool:
        now = self._now()
        with self._db() as db:
            return db.execute(
                "SELECT 1 FROM agent_durable_lease_v1 WHERE " + self._active_clause(),
                self._handle_tuple(handle, now),
            ).fetchone() is not None

    def begin_execution(self, handle: AgentRunLease) -> bool:
        """Before ANY driver/model/Tool dispatch, irreversibly disallow pre-work replay.

        A host must inject execution_guard(handle) into AgentPlanExecutor.
        Merely checking is_active() is NOT a safe first-dispatch guard: it would
        leave a time window allowing pause/reclaim during provider/tool work.
        """
        now = self._now()
        with self._db() as db:
            updated = db.execute(
                "UPDATE agent_durable_lease_v1 SET side_effect_uncertain=1 "
                "WHERE " + self._active_clause(),
                self._handle_tuple(handle, now),
            )
            return updated.rowcount == 1

    def execution_guard(self, handle: AgentRunLease) -> Callable[[], bool]:
        """Fail-closed runtime dispatch guard; host binds this to a leased run."""
        if not isinstance(handle, AgentRunLease):
            raise AgentDurableLeaseError("trusted lease handle required")
        return lambda: self.begin_execution(handle)

    def heartbeat(self, handle: AgentRunLease, *, lease_seconds: int = 60) -> bool:
        duration = _seconds(lease_seconds)
        now = self._now()
        with self._db() as db:
            update = db.execute(
                "UPDATE agent_durable_lease_v1 SET heartbeat_at=?,lease_until=? "
                "WHERE " + self._active_clause(),
                (now, now + duration, *self._handle_tuple(handle, now)),
            )
            return update.rowcount == 1

    def checkpoint(
        self, handle: AgentRunLease, *, completed_step: int,
        side_effect_uncertain: bool = True,
    ) -> bool:
        """Progress metadata only; never an authorization to replay a Tool.

        Default unsafe: model/provider activity, external writes and unknown
        outcomes are treated as potential side effects/duplicate cost.
        """
        if type(completed_step) is not int or not 0 <= completed_step <= 64:
            raise AgentDurableLeaseError("invalid checkpoint step")
        if type(side_effect_uncertain) is not bool:
            raise AgentDurableLeaseError("invalid side effect marker")
        now = self._now()
        with self._db() as db:
            updated = db.execute(
                "UPDATE agent_durable_lease_v1 SET checkpoint_step=?, "
                "side_effect_uncertain=MAX(side_effect_uncertain,?) "
                "WHERE " + self._active_clause() + " AND checkpoint_step<=?",
                (completed_step, int(side_effect_uncertain),
                 *self._handle_tuple(handle, now), completed_step),
            )
            return updated.rowcount == 1

    def pause_before_work(self, handle: AgentRunLease) -> bool:
        """Only a fresh step-0 run without external effects may be re-claimed."""
        now = self._now()
        with self._db() as db:
            updated = db.execute(
                "UPDATE agent_durable_lease_v1 SET status='paused',epoch=epoch+1 "
                "WHERE " + self._active_clause()
                + " AND checkpoint_step=0 AND side_effect_uncertain=0",
                self._handle_tuple(handle, now),
            )
            return updated.rowcount == 1

    def resume_prework(
        self, *, run_id: str, owner_scope: str, request_fingerprint: str,
        worker_id: str, lease_seconds: int = 60,
    ) -> AgentRunLease | None:
        """Atomic fresh fence for paused pre-work only; no tool/model replay."""
        _ref(run_id)
        _ref(owner_scope)
        _ref(worker_id)
        _fingerprint(request_fingerprint)
        duration = _seconds(lease_seconds)
        now = self._now()
        with self._db() as db:
            updated = db.execute(
                "UPDATE agent_durable_lease_v1 SET status='running', "
                "worker_id=?,epoch=epoch+1,heartbeat_at=?,lease_until=? "
                "WHERE run_id=? AND owner_scope=? AND request_fingerprint=? "
                "AND status='paused' AND checkpoint_step=0 "
                "AND side_effect_uncertain=0",
                (worker_id, now, now + duration, run_id, owner_scope,
                 request_fingerprint),
            )
            if updated.rowcount != 1:
                return None
            epoch = db.execute(
                "SELECT epoch FROM agent_durable_lease_v1 WHERE run_id=?",
                (run_id,),
            ).fetchone()[0]
        return AgentRunLease(run_id, owner_scope, request_fingerprint, worker_id, epoch)

    def finish(self, handle: AgentRunLease, *, state: str) -> bool:
        """Only the current non-expired lease may record terminal status."""
        if state not in ("completed", "failed", "awaiting_approval"):
            raise AgentDurableLeaseError("invalid terminal status")
        now = self._now()
        with self._db() as db:
            updated = db.execute(
                "UPDATE agent_durable_lease_v1 SET status=?,epoch=epoch+1 "
                "WHERE " + self._active_clause(),
                (state, *self._handle_tuple(handle, now)),
            )
            return updated.rowcount == 1

    def cancel(
        self, *, run_id: str, owner_scope: str, request_fingerprint: str,
    ) -> bool:
        """Owner-scoped persisted cancellation; fences future Tool dispatch.

        The host must separately signal a presently running coroutine/process.
        """
        _ref(run_id)
        _ref(owner_scope)
        _fingerprint(request_fingerprint)
        with self._db() as db:
            updated = db.execute(
                "UPDATE agent_durable_lease_v1 SET status='cancelled',epoch=epoch+1 "
                "WHERE run_id=? AND owner_scope=? AND request_fingerprint=? "
                "AND status IN ('running','paused','awaiting_approval')",
                (run_id, owner_scope, request_fingerprint),
            )
            return updated.rowcount == 1

    def quarantine_expired(self) -> int:
        """Never auto-replay uncertain work after lease loss or Worker crash."""
        now = self._now()
        with self._db() as db:
            updated = db.execute(
                "UPDATE agent_durable_lease_v1 SET status='needs_review', "
                "epoch=epoch+1 WHERE status='running' AND lease_until<=?",
                (now,),
            )
            return updated.rowcount

    def status(
        self, *, run_id: str, owner_scope: str, request_fingerprint: str,
    ) -> tuple[str, int, int] | None:
        """Nondisclosing read: (state, fence epoch, checkpoint step) only."""
        _ref(run_id)
        _ref(owner_scope)
        _fingerprint(request_fingerprint)
        with self._db() as db:
            row = db.execute(
                "SELECT status,epoch,checkpoint_step "
                "FROM agent_durable_lease_v1 "
                "WHERE run_id=? AND owner_scope=? AND request_fingerprint=?",
                (run_id, owner_scope, request_fingerprint),
            ).fetchone()
            return tuple(row) if row else None


DURABLE_LEDGER_AUTO_RETRIES_EXTERNAL_TOOLS = False
DURABLE_LEDGER_AUTHORIZES_APPROVAL = False
DURABLE_LEDGER_SUPPORTS_POST_TOOL_RESUME = False
