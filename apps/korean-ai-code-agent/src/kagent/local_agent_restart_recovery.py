"""#3128 — Local Runner restart reconciliation driver.

A Desktop that dies between local execution and the broker acknowledgement comes
back with two durable facts on disk: a locally terminal result and a missing
orthogonal server fact. This module is the driver that closes that gap. It

* reads the existing `DurableRunStore` classification, never re-executes,
* re-presents the exact correlation the record already holds,
* records the server fact only after the canonical broker accepted it,

and it owns no new authority. The canonical broker remains the only place a
command changes state, the store remains the only local record, and no path here
invents an execution fact, re-runs a process, or re-opens a terminal command.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Protocol

from .contracts import ContractError
from .local_agent_durable_run import (
    DurableRunRecord,
    DurableRunState,
    DurableRunTermination,
    broker_reconciliation_outcome,
)
from .local_agent_durable_run_store import DurableRunRecoveryClass, DurableRunStore
from .local_agent_pairing import DeviceBinding, DeviceSession

#: A refusal reason is a bounded label, never an echoed transport payload.
MAX_REFUSAL_REASON_CHARS = 120


class LocalAgentRestartRecoveryError(ContractError):
    """A fail-closed refusal carrying a deterministic, bounded code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class LocalAgentRecoveryChannelPort(Protocol):
    """The two recovery calls the driver is allowed to make.

    Deliberately not the whole channel: a driver that could reach execution or
    polling would be a second execution machine.
    """

    def acknowledge_recovered_run(
        self,
        *,
        binding: DeviceBinding,
        session: DeviceSession,
        command_id: str,
        admission_ref: str,
        evidence_ref: str,
        revision_ref: str,
        request_id: str,
        termination: str,
        exit_code: int | None,
        now: datetime,
    ) -> None:
        ...

    def reconcile_recovered_run(
        self,
        *,
        binding: DeviceBinding,
        session: DeviceSession,
        command_id: str,
        admission_ref: str,
        evidence_ref: str,
        revision_ref: str,
        request_id: str,
        request_fingerprint: str,
        termination: str | None,
        exit_code: int | None,
        now: datetime,
    ) -> None:
        ...


@dataclass(frozen=True, slots=True)
class LocalAgentRestartRecoveryReport:
    """Bounded, secret-free result of one reconciliation pass.

    `executor_calls` is always 0 and `replay_candidates` is always empty: this
    module is a reconciliation driver, never a replay engine.
    """

    classifications: dict[str, int] = field(default_factory=dict)
    #: Commands whose canonical broker state is now terminal and recorded locally.
    settled_command_ids: tuple[str, ...] = ()
    #: Commands still awaiting a canonical server fact (for example an exact
    #: acknowledgement that the pre-deadline window still refuses).
    pending_command_ids: tuple[str, ...] = ()
    #: (command_id, bounded reason) pairs. The reason is a fixed label, not a
    #: server response body.
    refusals: tuple[tuple[str, str], ...] = ()
    executor_calls: int = 0
    reexecution: bool = False
    replay_candidates: tuple[str, ...] = ()

    def safe_dict(self) -> dict[str, Any]:
        return {
            "classifications": dict(sorted(self.classifications.items())),
            "settled_command_ids": list(self.settled_command_ids),
            "pending_command_ids": list(self.pending_command_ids),
            "refusals": [list(item) for item in self.refusals],
            "executor_calls": self.executor_calls,
            "reexecution": self.reexecution,
            "replay_candidates": list(self.replay_candidates),
            "raw_argv": False,
            "raw_stdout": False,
            "raw_stderr": False,
            "raw_device_credential": False,
            "p01_approval_payload": False,
        }


def _reason(exc: Exception) -> str:
    """Reduce any failure to a bounded, non-echoing label."""

    text = str(exc).strip()
    if not text:
        return exc.__class__.__name__
    return text[:MAX_REFUSAL_REASON_CHARS]


class LocalAgentRestartRecoveryDriver:
    """Drive one restart reconciliation pass over the durable run store."""

    def __init__(
        self,
        *,
        store: DurableRunStore,
        channel: LocalAgentRecoveryChannelPort,
        binding: DeviceBinding,
    ) -> None:
        if not isinstance(store, DurableRunStore):
            raise ContractError("store must be DurableRunStore")
        for method_name in ("acknowledge_recovered_run", "reconcile_recovered_run"):
            if not callable(getattr(channel, method_name, None)):
                raise ContractError("channel must implement the recovery surface")
        if not isinstance(binding, DeviceBinding):
            raise ContractError("binding must be DeviceBinding")
        self._store = store
        self._channel = channel
        self._binding = binding

    def _correlation(self, record: DurableRunRecord) -> dict[str, str]:
        """Return the exact admitted correlation, or refuse to guess any of it."""

        missing = [
            name
            for name in ("admission_ref", "admission_evidence_ref", "revision_ref", "request_id")
            if getattr(record, name, None) is None
        ]
        if missing:
            raise LocalAgentRestartRecoveryError(
                "recovery_correlation_incomplete",
                "durable record is missing admitted correlation: " + ", ".join(sorted(missing)),
            )
        return {
            "command_id": record.command_id,
            "admission_ref": record.admission_ref,
            "evidence_ref": record.admission_evidence_ref,
            "revision_ref": record.revision_ref,
            "request_id": record.request_id,
        }

    def _settle(self, record: DurableRunRecord, *, session: DeviceSession, now: datetime) -> None:
        correlation = self._correlation(record)
        outcome = broker_reconciliation_outcome(record)
        if record.state is not None and record.hard_deadline_passed(now=now):
            # Past the hard deadline the canonical acknowledgement is closed, so
            # the #3121 reconciliation is the only exit left. It either carries
            # the proven local outcome or, with none, fails closed to EXPIRED.
            self._channel.reconcile_recovered_run(
                binding=self._binding,
                session=session,
                request_fingerprint=record.request_fingerprint,
                termination=outcome.termination,
                exit_code=outcome.exit_code,
                now=now,
                **correlation,
            )
            if not outcome.execution_outcome_proven:
                # The broker now holds a terminal EXPIRED outcome while this device
                # has no execution result at all. It can still state one honest
                # local fact — the hard deadline passed unobserved — and the store
                # insists on that ordering before any server fact is written.
                self._record_local_expiry(record, now=now)
        else:
            if not outcome.execution_outcome_proven:
                raise LocalAgentRestartRecoveryError(
                    "recovery_outcome_unproven",
                    "a pre-deadline acknowledgement retry requires a proven local terminal result",
                )
            self._channel.acknowledge_recovered_run(
                binding=self._binding,
                session=session,
                termination=outcome.termination,
                exit_code=outcome.exit_code,
                now=now,
                **correlation,
            )
        self._store.acknowledge(command_id=record.command_id, acknowledged_at=now)

    def _record_local_expiry(self, record: DurableRunRecord, *, now: datetime) -> None:
        """Persist the one local fact an unknown outcome always supports."""

        self._store.record_terminal(
            replace(
                record,
                state=DurableRunState.TERMINAL,
                termination=DurableRunTermination.EXPIRED,
                started_at=record.started_at or record.admitted_at,
                terminated_at=now,
            )
        )

    def recover_once(
        self,
        *,
        session: DeviceSession,
        now: datetime | None = None,
    ) -> LocalAgentRestartRecoveryReport:
        """Reconcile every durable record that is not yet settled server-side.

        Exactly one attempt per record per pass, never a re-execution, and a
        refusal leaves the record for a later pass rather than escalating it.
        """

        if not isinstance(session, DeviceSession):
            raise ContractError("session must be DeviceSession")
        moment = now if isinstance(now, datetime) else datetime.now(timezone.utc)
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ContractError("now must be timezone-aware")
        moment = moment.astimezone(timezone.utc)

        settled: list[str] = []
        pending: list[str] = []
        refusals: list[tuple[str, str]] = []
        for record in self._store.list_records():
            classification = self._store.classify(record, now=moment)
            if classification is DurableRunRecoveryClass.TERMINAL:
                continue
            if classification in {
                DurableRunRecoveryClass.ADMITTED_NONTERMINAL,
                DurableRunRecoveryClass.OFFLINE_RECONCILIATION_REQUIRED,
            }:
                # Ambiguous prior execution stays reported and untouched. It is
                # never re-executed and never acknowledged on a guess.
                pending.append(record.command_id)
                continue
            try:
                self._settle(record, session=session, now=moment)
            except Exception as exc:  # noqa: BLE001 - bounded, fail-closed refusal
                refusals.append((record.command_id, _reason(exc)))
                pending.append(record.command_id)
                continue
            settled.append(record.command_id)

        return LocalAgentRestartRecoveryReport(
            classifications=dict(self._store.recover(now=moment).classifications),
            settled_command_ids=tuple(sorted(settled)),
            pending_command_ids=tuple(sorted(pending)),
            refusals=tuple(sorted(refusals)),
            executor_calls=0,
            reexecution=False,
            replay_candidates=(),
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "restart_reconciliation_driver": True,
            "consumes_durable_run_store": True,
            "reuses_canonical_broker_acknowledgement": True,
            "reuses_3121_reconciliation": True,
            "executor_reference_held": False,
            "replay_engine": False,
            "second_recovery_authority": False,
            "second_execution_authority": False,
            "second_sequence_authority": False,
            "second_revision_authority": False,
            "second_fingerprint_authority": False,
            "old_session_resurrection": False,
            "production_mutation": False,
            "production_ready": False,
        }


RESTART_RECONCILIATION_DRIVER = True
RECOVERY_CONSUMES_DURABLE_RECORDS = True
RECOVERY_EXECUTOR_CALLS = 0
RECOVERY_REPLAY_CANDIDATES = 0
TERMINAL_REPLAY = 0
SECOND_RECOVERY_AUTHORITY = 0
SECOND_EXECUTION_AUTHORITY = 0
SECOND_SEQUENCE_AUTHORITY = 0
SECOND_REVISION_AUTHORITY = 0
SECOND_FINGERPRINT_AUTHORITY = 0
OLD_SESSION_RESURRECTION = False
TERMINAL_RESULT_DURABLE_BEFORE_ACK = True
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
