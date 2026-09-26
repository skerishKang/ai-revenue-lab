"""Issue #3121 — Local Runner recovery reconciles expired ADMITTED commands
against the canonical broker without replay.

Every scenario drives the real paths end to end:

* the real `StateBackedLocalAgentBrokerAuthority` over its serialized wire
  state (the durable broker composition), addressed through the real RPC
  facade payload shape;
* the real SQLite `DurableRunStore`, its restart `recover()` classification
  and the `broker_reconciliation_outcome` mapping over the durable record;
* correlation on the local record is copied verbatim from the broker's own
  `safe_dict` projection.

Nothing here stubs a transition under test, re-executes a command, re-enqueues
one, or mints a second sequence/revision/fingerprint.
"""

from __future__ import annotations

import base64
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kagent.local_agent_durable_run import (
    AUTOMATIC_COMMAND_REPLAY,
    AUTOMATIC_REEXECUTION,
    TERMINAL_REOPEN,
    UNKNOWN_EXECUTION_OUTCOME_FAILS_CLOSED,
    BrokerReconciliationOutcome,
    DurableRunRecord,
    DurableRunState,
    DurableRunTermination,
    broker_reconciliation_outcome,
)
from kagent.local_agent_durable_run_store import (
    DurableRunRecoveryClass,
    DurableRunStore,
)
from padiem_control_plane.local_agent_broker import BrokerCommandState
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
from padiem_control_plane.local_agent_broker_state import StateBackedLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_state_wire import (
    InMemorySerializedLocalAgentBrokerStateBackend,
    SerializedLocalAgentBrokerStatePort,
)

BASE = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)
PEPPER = b"padiem-local-agent-broker-runner-reconcile-pepper"
CREDENTIAL = b"runner-reconcile-device-credential"
FINGERPRINT = "c" * 64
AUTHORITY_REF = "control-plane.local-agent-broker.runner-reconcile.v1"
COMMAND_TTL_SECONDS = 300
ENQUEUED_AT = BASE + timedelta(seconds=2)
ADMITTED_AT = BASE + timedelta(seconds=3)
#: The moment the hard deadline of every command in this module has passed.
EXPIRED_AT = ENQUEUED_AT + timedelta(seconds=COMMAND_TTL_SECONDS)


def _credential_b64() -> str:
    return base64.b64encode(CREDENTIAL).decode("ascii")


class ReconcileHarness:
    """Real broker + real durable store, addressed the way the device does."""

    def __init__(self, tmp_path: Path) -> None:
        self.backend = InMemorySerializedLocalAgentBrokerStateBackend()
        self.port = SerializedLocalAgentBrokerStatePort(backend=self.backend)
        self.authority = StateBackedLocalAgentBrokerAuthority(
            pepper=PEPPER,
            authority_ref=AUTHORITY_REF,
            state_port=self.port,
        )
        self.binding = self.authority.register_binding(
            binding_ref="binding.runner.1",
            device_id="device.runner.1",
            account_ref="account.1",
            workspace_ref="workspace.1",
            credential=CREDENTIAL,
            now=BASE,
        )
        self.authority.open_session(
            session_id="session.runner.1",
            binding_ref=self.binding.binding_ref,
            credential=CREDENTIAL,
            account_ref="account.1",
            workspace_ref="workspace.1",
            now=BASE + timedelta(seconds=1),
        )
        self.store = DurableRunStore(str(tmp_path / "durable-runs.sqlite3"))

    def close(self) -> None:
        self.store.close()

    def admit(self, command_id: str):
        self.authority.enqueue_command(
            command_id=command_id,
            binding_ref=self.binding.binding_ref,
            run_id="run.1",
            tool_request_ref=f"tool-request.{command_id}",
            request_fingerprint=FINGERPRINT,
            now=ENQUEUED_AT,
            ttl_seconds=COMMAND_TTL_SECONDS,
        )
        return self.authority.admit_command(
            admission_ref=f"admission.{command_id}",
            evidence_ref=f"evidence.{command_id}",
            session_id="session.runner.1",
            binding_ref=self.binding.binding_ref,
            credential=CREDENTIAL,
            command_id=command_id,
            request_fingerprint=FINGERPRINT,
            request_id=f"request.{command_id}",
            now=ADMITTED_AT,
        )

    def durable_record(self, admission) -> DurableRunRecord:
        """Copy the admitted correlation verbatim from the broker projection."""

        snapshot = self.port.load(authority_ref=AUTHORITY_REF).snapshot
        command = next(item for item in snapshot.commands if item.command_id == admission.command_id)
        projection = command.safe_dict()
        return DurableRunRecord(
            command_id=projection["command_id"],
            run_id=projection["run_id"],
            tool_request_ref=projection["tool_request_ref"],
            request_id=projection["request_id"],
            revision_ref=projection["revision_ref"],
            device_id=self.binding.device_id,
            binding_ref=projection["binding_ref"],
            session_id=projection["admitted_session_id"],
            account_ref=self.binding.account_ref,
            workspace_ref=self.binding.workspace_ref,
            sequence=projection["sequence"],
            credential_generation=projection["credential_generation"],
            request_fingerprint=projection["request_fingerprint"],
            fingerprint_source="broker",
            command_issued_at=datetime.fromisoformat(projection["issued_at"]),
            command_expires_at=datetime.fromisoformat(projection["expires_at"]),
            admitted_at=datetime.fromisoformat(projection["admitted_at"]),
            admission_ref=projection["admission_ref"],
        )

    def reconcile(self, admission, *, termination: str | None, exit_code: int | None, now: datetime = EXPIRED_AT):
        facade = LocalAgentBrokerRpcFacade(authority=self.authority)
        return facade.reconcile_expired_command(
            {
                "session_id": "session.runner.1",
                "binding_ref": self.binding.binding_ref,
                "credential_b64": _credential_b64(),
                "command_id": admission.command_id,
                "admission_ref": admission.admission_ref,
                "revision_ref": admission.revision_ref,
                "request_id": admission.request_id,
                "request_fingerprint": admission.request_fingerprint,
                "termination": termination,
                "exit_code": exit_code,
                "now": now.isoformat(),
            }
        )

    def poll(self, *, now: datetime = EXPIRED_AT + timedelta(seconds=5)):
        return self.authority.poll(
            session_id="session.runner.1",
            binding_ref=self.binding.binding_ref,
            credential=CREDENTIAL,
            after_sequence=0,
            now=now,
        )


@pytest.fixture()
def harness(tmp_path):
    fixture = ReconcileHarness(tmp_path)
    yield fixture
    fixture.close()


def test_unknown_execution_outcome_fails_closed_to_broker_expired_without_replay(harness):
    admission = harness.admit("command.1")
    record = harness.durable_record(admission)
    harness.store.put(record)

    # Restart recovery: the deadline passed with no local execution fact.
    report = harness.store.recover(now=EXPIRED_AT)
    assert report.reconciliation_command_ids == ("command.1",)
    assert report.replay_candidates == ()
    assert report.execution_authority_granted is False

    outcome = broker_reconciliation_outcome(harness.store.get(command_id="command.1"))
    assert outcome == BrokerReconciliationOutcome(
        execution_outcome_proven=False, termination=None, exit_code=None
    )

    response = harness.reconcile(admission, termination=outcome.termination, exit_code=outcome.exit_code)
    assert response["ok"] is True
    assert response["command"]["state"] == BrokerCommandState.EXPIRED.value
    assert response["command"]["termination"] is None
    assert response["command"]["exit_code"] is None
    assert response["command"]["acknowledged_at"] is None
    # Correlation preserved verbatim.
    assert response["command"]["revision_ref"] == admission.revision_ref
    assert response["command"]["request_fingerprint"] == admission.request_fingerprint
    assert response["command"]["sequence"] == admission.sequence

    # Terminal: nothing pollable, nothing re-admittable, repeats refused.
    assert harness.poll() == ()
    repeat = harness.reconcile(admission, termination=None, exit_code=None, now=EXPIRED_AT + timedelta(seconds=6))
    assert repeat["ok"] is False
    assert repeat["error"]["code"] == "broker_command_not_reconcilable"
    with pytest.raises(Exception) as readmit:
        harness.authority.admit_command(
            admission_ref="replay.command.1",
            evidence_ref="replay-evidence.command.1",
            session_id="session.runner.1",
            binding_ref=harness.binding.binding_ref,
            credential=CREDENTIAL,
            command_id="command.1",
            request_fingerprint=FINGERPRINT,
            request_id="request.command.1",
            now=EXPIRED_AT + timedelta(seconds=6),
        )
    assert readmit.value.code == "broker_command_replay"
    # The local record is unchanged by the refused repeat.
    assert harness.store.get(command_id="command.1") == record


def test_late_terminal_result_reconciles_exactly_once_and_lands_terminal(harness):
    admission = harness.admit("command.1")
    record = harness.durable_record(admission)
    # The command executed to its own exit status, but the acknowledgement
    # response was lost before the device could record it.
    terminal = replace(
        record,
        state=DurableRunState.TERMINAL,
        termination=DurableRunTermination.EXITED,
        started_at=ADMITTED_AT + timedelta(seconds=1),
        terminated_at=ADMITTED_AT + timedelta(seconds=5),
        exit_code=0,
    )
    harness.store.put(record)
    harness.store.record_terminal(terminal)

    report = harness.store.recover(now=EXPIRED_AT)
    assert report.reconciliation_command_ids == ("command.1",)

    outcome = broker_reconciliation_outcome(harness.store.get(command_id="command.1"))
    assert outcome == BrokerReconciliationOutcome(
        execution_outcome_proven=True, termination="exited", exit_code=0
    )

    response = harness.reconcile(admission, termination=outcome.termination, exit_code=outcome.exit_code)
    assert response["ok"] is True
    assert response["command"]["state"] == BrokerCommandState.ACKNOWLEDGED.value
    assert response["command"]["termination"] == "exited"
    assert response["command"]["exit_code"] == 0
    assert response["command"]["revision_ref"] == admission.revision_ref

    # The orthogonal server fact lands on the durable record — after the
    # hard deadline, via the #3121 late reconciliation.
    harness.store.acknowledge(
        command_id="command.1",
        acknowledged_at=EXPIRED_AT + timedelta(seconds=2),
    )
    acknowledged_record = harness.store.get(command_id="command.1")
    assert acknowledged_record.server_acknowledged_at == EXPIRED_AT + timedelta(seconds=2)
    assert harness.store.classify(acknowledged_record, now=EXPIRED_AT + timedelta(seconds=3)) is (
        DurableRunRecoveryClass.TERMINAL
    )
    assert harness.store.recover(now=EXPIRED_AT + timedelta(seconds=3)).reconciliation_command_ids == ()

    # Terminal: replay stays at zero, repeats refused, correlation intact.
    assert harness.poll() == ()
    repeat = harness.reconcile(
        admission,
        termination="exited",
        exit_code=0,
        now=EXPIRED_AT + timedelta(seconds=6),
    )
    assert repeat["ok"] is False
    assert repeat["error"]["code"] == "broker_command_not_reconcilable"
    assert harness.store.get(command_id="command.1") == replace(
        acknowledged_record
    )


def test_locally_expired_termination_is_never_projected_as_an_execution_result(harness):
    admission = harness.admit("command.1")
    record = harness.durable_record(admission)
    # The deadline hit while the command was still executing locally: the
    # durable EXPIRED fact proves no execution outcome.
    terminal = replace(
        record,
        state=DurableRunState.TERMINAL,
        termination=DurableRunTermination.EXPIRED,
        started_at=ADMITTED_AT + timedelta(seconds=1),
        terminated_at=EXPIRED_AT + timedelta(seconds=1),
    )
    harness.store.put(record)
    harness.store.record_terminal(terminal)

    outcome = broker_reconciliation_outcome(harness.store.get(command_id="command.1"))
    assert outcome.execution_outcome_proven is False
    assert outcome.termination is None
    assert outcome.exit_code is None

    response = harness.reconcile(admission, termination=outcome.termination, exit_code=outcome.exit_code)
    assert response["ok"] is True
    assert response["command"]["state"] == BrokerCommandState.EXPIRED.value
    assert response["command"]["termination"] is None


def test_mismatched_correlation_late_result_is_rejected_and_changes_nothing(harness):
    admission = harness.admit("command.1")
    record = harness.durable_record(admission)
    harness.store.put(record)

    facade = LocalAgentBrokerRpcFacade(authority=harness.authority)
    mismatched = {
        "session_id": "session.runner.1",
        "binding_ref": harness.binding.binding_ref,
        "credential_b64": _credential_b64(),
        "command_id": admission.command_id,
        "admission_ref": "admission.command.1",
        "revision_ref": "rev." + "0" * 32,
        "request_id": admission.request_id,
        "request_fingerprint": admission.request_fingerprint,
        "termination": "exited",
        "exit_code": 0,
        "now": EXPIRED_AT.isoformat(),
    }
    response = facade.reconcile_expired_command(mismatched)
    assert response["ok"] is False
    assert response["error"]["code"] == "broker_reconcile_revision_mismatch"

    snapshot = harness.port.load(authority_ref=AUTHORITY_REF).snapshot
    stored = next(item for item in snapshot.commands if item.command_id == admission.command_id)
    assert stored.state is BrokerCommandState.ADMITTED
    assert harness.store.get(command_id="command.1") == record


def test_runner_source_truth_constants_preserve_no_replay_boundaries():
    assert UNKNOWN_EXECUTION_OUTCOME_FAILS_CLOSED is True
    assert AUTOMATIC_COMMAND_REPLAY is False
    assert AUTOMATIC_REEXECUTION is False
    assert TERMINAL_REOPEN is False
