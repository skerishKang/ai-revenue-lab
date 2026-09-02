from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .contracts import ClawRunStatus, ClawTaskIntent, ContractError, RunProjection


class RunStateError(RuntimeError):
    pass


_ALLOWED_TRANSITIONS: dict[ClawRunStatus, frozenset[ClawRunStatus]] = {
    ClawRunStatus.QUEUED: frozenset(
        {ClawRunStatus.PREPARING, ClawRunStatus.CANCELLED, ClawRunStatus.FAILED}
    ),
    ClawRunStatus.PREPARING: frozenset(
        {
            ClawRunStatus.RUNNING,
            ClawRunStatus.WAITING_APPROVAL,
            ClawRunStatus.CANCELLED,
            ClawRunStatus.FAILED,
        }
    ),
    ClawRunStatus.RUNNING: frozenset(
        {
            ClawRunStatus.WAITING_APPROVAL,
            ClawRunStatus.COMPLETED,
            ClawRunStatus.CANCELLED,
            ClawRunStatus.FAILED,
        }
    ),
    ClawRunStatus.WAITING_APPROVAL: frozenset(
        {ClawRunStatus.RUNNING, ClawRunStatus.CANCELLED, ClawRunStatus.FAILED}
    ),
    ClawRunStatus.COMPLETED: frozenset(),
    ClawRunStatus.FAILED: frozenset(),
    ClawRunStatus.CANCELLED: frozenset(),
}


@dataclass(slots=True)
class ClawRun:
    """Product-owned run container.

    This state machine tracks user-visible B54 lifecycle only. It deliberately
    does not implement P01 planning, retry/recovery, approval authority, Tool
    execution, or model routing.
    """

    run_id: str
    intent: ClawTaskIntent
    status: ClawRunStatus = ClawRunStatus.QUEUED
    summary: str = ""
    changed_files: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def create(cls, run_id: str, intent: ClawTaskIntent) -> "ClawRun":
        # RunProjection provides the shared identifier validation without
        # duplicating identifier grammar in this mutable lifecycle container.
        RunProjection(
            run_id=run_id,
            task_id=intent.task_id,
            status=ClawRunStatus.QUEUED,
            execution_mode=intent.execution_mode,
        )
        return cls(run_id=run_id, intent=intent)

    @property
    def terminal(self) -> bool:
        return self.status.terminal

    def transition(self, next_status: ClawRunStatus, *, summary: str | None = None) -> None:
        allowed = _ALLOWED_TRANSITIONS[self.status]
        if next_status not in allowed:
            raise RunStateError(
                f"illegal run transition: {self.status.value} -> {next_status.value}"
            )
        candidate_summary = self.summary if summary is None else summary
        # Validate presentation fields before mutating state.
        RunProjection(
            run_id=self.run_id,
            task_id=self.intent.task_id,
            status=next_status,
            execution_mode=self.intent.execution_mode,
            summary=candidate_summary,
            changed_files=self.changed_files,
            approval_required=next_status is ClawRunStatus.WAITING_APPROVAL,
        )
        self.status = next_status
        self.summary = candidate_summary

    def record_changed_files(self, paths: Iterable[str]) -> None:
        if self.terminal:
            raise RunStateError("terminal run cannot accept changed-file updates")
        candidate = tuple(paths)
        RunProjection(
            run_id=self.run_id,
            task_id=self.intent.task_id,
            status=self.status,
            execution_mode=self.intent.execution_mode,
            summary=self.summary,
            changed_files=candidate,
            approval_required=self.status is ClawRunStatus.WAITING_APPROVAL,
        )
        self.changed_files = candidate

    def projection(self) -> RunProjection:
        return RunProjection(
            run_id=self.run_id,
            task_id=self.intent.task_id,
            status=self.status,
            execution_mode=self.intent.execution_mode,
            summary=self.summary,
            changed_files=self.changed_files,
            approval_required=self.status is ClawRunStatus.WAITING_APPROVAL,
        )


class InMemoryRunStore:
    """Process-local development store; not a persistence or billing authority."""

    def __init__(self) -> None:
        self._runs: dict[str, ClawRun] = {}

    def add(self, run: ClawRun) -> None:
        if run.run_id in self._runs:
            raise RunStateError(f"run already exists: {run.run_id}")
        self._runs[run.run_id] = run

    def get(self, run_id: str) -> ClawRun:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise RunStateError(f"unknown run: {run_id}") from exc

    def projection(self, run_id: str) -> RunProjection:
        return self.get(run_id).projection()

    def __len__(self) -> int:
        return len(self._runs)
