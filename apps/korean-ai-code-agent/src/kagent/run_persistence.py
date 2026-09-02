from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .background_dispatch import DispatchProjection, DispatchState
from .contracts import ClawRunStatus, ContractError, ExecutionMode, RunProjection
from .security import redact_secrets


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_EXACT_REVISION_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


class RestoreAction(str, Enum):
    NO_ACTION_TERMINAL = "no_action_terminal"
    RECONCILE_CANCELLATION = "reconcile_cancellation"
    RECONCILE_P01 = "reconcile_p01"
    RECONCILE_WORKER_LEASE = "reconcile_worker_lease"
    POLICY_REQUEUE_REVIEW = "policy_requeue_review"


def _id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe identifier")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _revision(value: str) -> str:
    if not isinstance(value, str) or not _EXACT_REVISION_RE.fullmatch(value.strip()):
        raise ContractError("exact_revision must be an immutable hexadecimal revision")
    return value.strip().lower()


def _safe_summary(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2000:
        raise ContractError("summary must be a bounded string")
    return redact_secrets(value.strip())


@dataclass(frozen=True, slots=True)
class RunPersistenceSnapshot:
    run_id: str
    task_id: str
    generation: int
    run_status: ClawRunStatus
    execution_mode: ExecutionMode
    repository_ref: str
    exact_revision: str
    summary: str
    changed_files: tuple[str, ...]
    dispatch_id: str
    dispatch_state: DispatchState
    worker_lease_id: str | None
    worker_lease_expires_at: datetime | None
    cancellation_id: str | None
    p01_run_id: str | None
    p01_last_sequence: int | None
    p01_last_event_id: str | None
    saved_at: datetime
    snapshot_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in ("run_id", "task_id", "dispatch_id"):
            object.__setattr__(self, field_name, _id(getattr(self, field_name), field_name))
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or not 1 <= self.generation <= 1_000_000:
            raise ContractError("generation must be between 1 and 1000000")
        if not isinstance(self.run_status, ClawRunStatus):
            raise ContractError("run_status must be ClawRunStatus")
        if self.execution_mode is not ExecutionMode.CLOUD:
            raise ContractError("background persistence snapshot supports cloud mode only")
        if not isinstance(self.repository_ref, str) or not self.repository_ref.strip() or len(self.repository_ref.strip()) > 1024:
            raise ContractError("repository_ref must be bounded and non-empty")
        repository_ref = self.repository_ref.strip()
        if redact_secrets(repository_ref) != repository_ref:
            raise ContractError("repository_ref must not contain raw credential material")
        object.__setattr__(self, "repository_ref", repository_ref)
        object.__setattr__(self, "exact_revision", _revision(self.exact_revision))
        object.__setattr__(self, "summary", _safe_summary(self.summary))
        if not isinstance(self.changed_files, tuple) or len(self.changed_files) > 100:
            raise ContractError("changed_files must be a tuple with at most 100 entries")
        normalized_files: list[str] = []
        for path in self.changed_files:
            if not isinstance(path, str) or not path.strip() or len(path.strip()) > 512 or any(ord(ch) < 32 for ch in path):
                raise ContractError("changed file path is invalid")
            normalized_files.append(path.strip())
        if len(normalized_files) != len(set(normalized_files)):
            raise ContractError("changed_files must be unique")
        object.__setattr__(self, "changed_files", tuple(normalized_files))
        if not isinstance(self.dispatch_state, DispatchState):
            raise ContractError("dispatch_state must be DispatchState")

        if self.worker_lease_id is None:
            if self.worker_lease_expires_at is not None:
                raise ContractError("worker lease expiry requires worker_lease_id")
        else:
            object.__setattr__(self, "worker_lease_id", _id(self.worker_lease_id, "worker_lease_id"))
            if self.worker_lease_expires_at is None:
                raise ContractError("worker_lease_id requires worker_lease_expires_at")
            object.__setattr__(self, "worker_lease_expires_at", _aware(self.worker_lease_expires_at, "worker_lease_expires_at"))

        if self.cancellation_id is not None:
            object.__setattr__(self, "cancellation_id", _id(self.cancellation_id, "cancellation_id"))

        cursor_values = (self.p01_run_id, self.p01_last_sequence, self.p01_last_event_id)
        if all(value is None for value in cursor_values):
            pass
        elif any(value is None for value in cursor_values):
            raise ContractError("P01 cursor fields must be all present or all absent")
        else:
            assert self.p01_run_id is not None
            assert self.p01_last_sequence is not None
            assert self.p01_last_event_id is not None
            object.__setattr__(self, "p01_run_id", _id(self.p01_run_id, "p01_run_id"))
            if isinstance(self.p01_last_sequence, bool) or not isinstance(self.p01_last_sequence, int) or self.p01_last_sequence < 1:
                raise ContractError("p01_last_sequence must be positive")
            object.__setattr__(self, "p01_last_event_id", _id(self.p01_last_event_id, "p01_last_event_id"))

        object.__setattr__(self, "saved_at", _aware(self.saved_at, "saved_at"))
        object.__setattr__(self, "snapshot_digest", self._calculate_digest())

    @classmethod
    def capture(
        cls,
        *,
        run: RunProjection,
        dispatch: DispatchProjection,
        generation: int,
        saved_at: datetime,
    ) -> "RunPersistenceSnapshot":
        if not isinstance(run, RunProjection):
            raise ContractError("run must be RunProjection")
        if not isinstance(dispatch, DispatchProjection):
            raise ContractError("dispatch must be DispatchProjection")
        if run.run_id != dispatch.request.run_id:
            raise ContractError("run and dispatch correlation mismatch")
        if run.execution_mode is not ExecutionMode.CLOUD or dispatch.request.execution_mode is not ExecutionMode.CLOUD:
            raise ContractError("run persistence capture requires cloud mode")

        lease = dispatch.active_lease
        cancellation = dispatch.cancellation
        cursor = dispatch.cursor
        return cls(
            run_id=run.run_id,
            task_id=run.task_id,
            generation=generation,
            run_status=run.status,
            execution_mode=run.execution_mode,
            repository_ref=dispatch.request.repository_ref,
            exact_revision=dispatch.request.exact_revision,
            summary=run.summary,
            changed_files=run.changed_files,
            dispatch_id=dispatch.request.dispatch_id,
            dispatch_state=dispatch.state,
            worker_lease_id=lease.lease_id if lease else None,
            worker_lease_expires_at=lease.expires_at if lease else None,
            cancellation_id=cancellation.cancellation_id if cancellation else None,
            p01_run_id=cursor.p01_run_id if cursor else None,
            p01_last_sequence=cursor.last_sequence if cursor else None,
            p01_last_event_id=cursor.last_event_id if cursor else None,
            saved_at=saved_at,
        )

    def _digest_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "generation": self.generation,
            "run_status": self.run_status.value,
            "execution_mode": self.execution_mode.value,
            "repository_ref": self.repository_ref,
            "exact_revision": self.exact_revision,
            "summary": self.summary,
            "changed_files": list(self.changed_files),
            "dispatch_id": self.dispatch_id,
            "dispatch_state": self.dispatch_state.value,
            "worker_lease_id": self.worker_lease_id,
            "worker_lease_expires_at": self.worker_lease_expires_at.isoformat() if self.worker_lease_expires_at else None,
            "cancellation_id": self.cancellation_id,
            "p01_run_id": self.p01_run_id,
            "p01_last_sequence": self.p01_last_sequence,
            "p01_last_event_id": self.p01_last_event_id,
            "saved_at": self.saved_at.isoformat(),
        }

    def _calculate_digest(self) -> str:
        encoded = json.dumps(
            self._digest_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def safe_dict(self) -> dict[str, Any]:
        result = self._digest_payload()
        result.update(
            {
                "contract_version": "claw-run-persistence-snapshot.v1",
                "snapshot_digest": self.snapshot_digest,
                "task_prompt_stored": False,
                "raw_model_messages_stored": False,
                "hidden_reasoning_stored": False,
                "tool_arguments_stored": False,
                "provider_credentials_stored": False,
                "p01_internal_state_stored": False,
            }
        )
        return result


class InMemoryRunSnapshotStore:
    """Append-only deterministic persistence fake with CAS semantics."""

    def __init__(self) -> None:
        self._snapshots: dict[str, list[RunPersistenceSnapshot]] = {}

    def latest(self, run_id: str) -> RunPersistenceSnapshot:
        run_id = _id(run_id, "run_id")
        try:
            return self._snapshots[run_id][-1]
        except (KeyError, IndexError) as exc:
            raise ContractError("run snapshot not found") from exc

    def history(self, run_id: str) -> tuple[RunPersistenceSnapshot, ...]:
        run_id = _id(run_id, "run_id")
        return tuple(self._snapshots.get(run_id, ()))

    def save(self, snapshot: RunPersistenceSnapshot, *, expected_generation: int) -> RunPersistenceSnapshot:
        if not isinstance(snapshot, RunPersistenceSnapshot):
            raise ContractError("snapshot must be RunPersistenceSnapshot")
        if isinstance(expected_generation, bool) or not isinstance(expected_generation, int) or expected_generation < 0:
            raise ContractError("expected_generation must be a non-negative integer")
        history = self._snapshots.setdefault(snapshot.run_id, [])
        current_generation = history[-1].generation if history else 0

        if snapshot.generation == current_generation and history:
            if snapshot.snapshot_digest == history[-1].snapshot_digest:
                return history[-1]
            raise ContractError("snapshot generation replay conflicts with stored digest")
        if current_generation != expected_generation:
            raise ContractError("snapshot compare-and-swap generation mismatch")
        if snapshot.generation != current_generation + 1:
            raise ContractError("snapshot generation must be contiguous")

        if history:
            self._validate_successor(history[-1], snapshot)
        history.append(snapshot)
        return snapshot

    @staticmethod
    def _validate_successor(previous: RunPersistenceSnapshot, current: RunPersistenceSnapshot) -> None:
        if previous.run_status.terminal:
            raise ContractError("terminal run snapshot cannot advance or resurrect")
        for field_name in (
            "task_id",
            "execution_mode",
            "repository_ref",
            "exact_revision",
            "dispatch_id",
        ):
            if getattr(previous, field_name) != getattr(current, field_name):
                raise ContractError(f"run persistence identity changed: {field_name}")
        if previous.cancellation_id is not None and current.cancellation_id != previous.cancellation_id:
            raise ContractError("observed cancellation intent cannot disappear or change")
        if previous.p01_run_id is not None:
            if current.p01_run_id != previous.p01_run_id:
                raise ContractError("P01 run identity cannot change or disappear")
            assert previous.p01_last_sequence is not None
            assert previous.p01_last_event_id is not None
            assert current.p01_last_sequence is not None
            assert current.p01_last_event_id is not None
            if current.p01_last_sequence < previous.p01_last_sequence:
                raise ContractError("P01 event cursor cannot regress")
            if (
                current.p01_last_sequence == previous.p01_last_sequence
                and current.p01_last_event_id != previous.p01_last_event_id
            ):
                raise ContractError("same P01 event sequence cannot change event identity")
        if current.saved_at < previous.saved_at:
            raise ContractError("snapshot saved_at must be monotonic")


@dataclass(frozen=True, slots=True)
class RunRestorePlan:
    run_id: str
    generation: int
    snapshot_digest: str
    action: RestoreAction
    p01_run_id: str | None
    p01_last_sequence: int | None
    worker_lease_id: str | None
    cancellation_id: str | None
    automatic_resume_allowed: bool = False
    automatic_redispatch_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _id(self.run_id, "run_id"))
        if not isinstance(self.action, RestoreAction):
            raise ContractError("action must be RestoreAction")
        if self.automatic_resume_allowed is not False or self.automatic_redispatch_allowed is not False:
            raise ContractError("restore plan cannot authorize automatic resume or redispatch")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "generation": self.generation,
            "snapshot_digest": self.snapshot_digest,
            "action": self.action.value,
            "p01_run_id": self.p01_run_id,
            "p01_last_sequence": self.p01_last_sequence,
            "worker_lease_id": self.worker_lease_id,
            "cancellation_id": self.cancellation_id,
            "automatic_resume_allowed": False,
            "automatic_redispatch_allowed": False,
        }


def build_restore_plan(snapshot: RunPersistenceSnapshot) -> RunRestorePlan:
    if not isinstance(snapshot, RunPersistenceSnapshot):
        raise ContractError("snapshot must be RunPersistenceSnapshot")
    if snapshot.run_status.terminal:
        action = RestoreAction.NO_ACTION_TERMINAL
    elif snapshot.cancellation_id is not None or snapshot.dispatch_state is DispatchState.CANCELLATION_REQUESTED:
        action = RestoreAction.RECONCILE_CANCELLATION
    elif snapshot.p01_run_id is not None or snapshot.dispatch_state in {
        DispatchState.ACKNOWLEDGED,
        DispatchState.RECONCILIATION_REQUIRED,
    }:
        action = RestoreAction.RECONCILE_P01
    elif snapshot.worker_lease_id is not None or snapshot.dispatch_state is DispatchState.LEASED:
        action = RestoreAction.RECONCILE_WORKER_LEASE
    else:
        action = RestoreAction.POLICY_REQUEUE_REVIEW
    return RunRestorePlan(
        run_id=snapshot.run_id,
        generation=snapshot.generation,
        snapshot_digest=snapshot.snapshot_digest,
        action=action,
        p01_run_id=snapshot.p01_run_id,
        p01_last_sequence=snapshot.p01_last_sequence,
        worker_lease_id=snapshot.worker_lease_id,
        cancellation_id=snapshot.cancellation_id,
    )


REAL_DURABLE_RUN_STORE_CONFIGURED = False
AUTO_RESUME_FROM_B54_SNAPSHOT_SUPPORTED = False
B54_P01_INTERNAL_STATE_PERSISTENCE_SUPPORTED = False
