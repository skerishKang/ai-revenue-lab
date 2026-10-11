"""Issue #3121 — expired-ADMITTED reconciliation without replay.

These tests exercise the canonical broker authority's single fail-closed
reconciliation exit for an admitted command whose hard deadline passed:

* ADMITTED before expiry keeps the existing canonical acknowledge path;
* ADMITTED past expiry with a provable outcome reconciles to ACKNOWLEDGED
  exactly once, preserving every correlation verbatim;
* ADMITTED past expiry with no provable outcome fails closed to the terminal
  EXPIRED state instead of disappearing or fabricating an execution fact;
* nothing here replays, re-enqueues, re-executes, reopens a terminal command
  or mints a second sequence/revision/fingerprint.

Reconciliation is driven from the admission receipt — the exact correlation
facts a device durably stores after `admit_command`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker import (
    AUTOMATIC_COMMAND_REPLAY,
    AUTOMATIC_REEXECUTION,
    EXPIRED_ADMITTED_PERMANENT_STUCK,
    EXPIRED_ADMITTED_RECONCILIATION_PATH,
    LATE_TERMINAL_RESULT_RECONCILIATION,
    RAW_CREDENTIAL_LOG,
    RECONCILIATION_ALLOWABLE_STATES,
    RECONCILIATION_MINTS_CORRELATION,
    RECONCILIATION_TERMINAL_STATES,
    SECOND_FINGERPRINT_AUTHORITY,
    SECOND_REVISION_MINT,
    SECOND_SEQUENCE_MINT,
    TERMINAL_REOPEN,
    UNKNOWN_EXECUTION_OUTCOME_FAILS_CLOSED,
    BrokerCommandState,
    InMemoryLocalAgentBrokerAuthority,
)

NOW = datetime(2026, 9, 3, 13, 30, tzinfo=timezone.utc)
PEPPER = b"padiem-local-agent-broker-test-pepper"
CREDENTIAL_1 = b"device-credential-generation-one"
FINGERPRINT_1 = "1" * 64

#: TTL used for every enqueued command in this module.
COMMAND_TTL_SECONDS = 300
#: The moment the hard deadline has passed (enqueue at NOW+2, TTL 300).
EXPIRED_AT = NOW + timedelta(seconds=302)
AFTER_EXPIRY = EXPIRED_AT + timedelta(seconds=1)


def authority() -> InMemoryLocalAgentBrokerAuthority:
    return InMemoryLocalAgentBrokerAuthority(
        pepper=PEPPER,
        authority_ref="control-plane.local-agent-broker.v1",
    )


def register(service: InMemoryLocalAgentBrokerAuthority, *, now: datetime = NOW):
    return service.register_binding(
        binding_ref="binding.1",
        device_id="device.1",
        account_ref="account.1",
        workspace_ref="workspace.1",
        credential=CREDENTIAL_1,
        now=now,
    )


def open_session(
    service: InMemoryLocalAgentBrokerAuthority,
    *,
    session_id: str = "session.1",
    now: datetime = NOW + timedelta(seconds=1),
):
    return service.open_session(
        session_id=session_id,
        binding_ref="binding.1",
        credential=CREDENTIAL_1,
        account_ref="account.1",
        workspace_ref="workspace.1",
        now=now,
    )


def enqueue(
    service: InMemoryLocalAgentBrokerAuthority,
    *,
    command_id: str = "command.1",
    now: datetime = NOW + timedelta(seconds=2),
):
    return service.enqueue_command(
        command_id=command_id,
        binding_ref="binding.1",
        run_id="run.1",
        tool_request_ref=f"tool-request.{command_id}",
        request_fingerprint=FINGERPRINT_1,
        now=now,
        ttl_seconds=COMMAND_TTL_SECONDS,
    )


def admit(
    service: InMemoryLocalAgentBrokerAuthority,
    *,
    command_id: str = "command.1",
    session_id: str = "session.1",
    now: datetime = NOW + timedelta(seconds=3),
):
    return service.admit_command(
        admission_ref=f"admission.{command_id}",
        evidence_ref=f"evidence.{command_id}",
        session_id=session_id,
        binding_ref="binding.1",
        credential=CREDENTIAL_1,
        command_id=command_id,
        request_fingerprint=FINGERPRINT_1,
        request_id=f"request.{command_id}",
        now=now,
    )


def stored(service: InMemoryLocalAgentBrokerAuthority, admission):
    return service._commands[admission.command_id]


def reconcile(
    service: InMemoryLocalAgentBrokerAuthority,
    *,
    admission,
    session_id: str = "session.1",
    admission_ref: str | None = None,
    revision_ref: str | None = None,
    request_id: str | None = None,
    request_fingerprint: str | None = None,
    termination: str | None = None,
    exit_code: int | None = None,
    now: datetime = EXPIRED_AT,
):
    """Reconcile from the admission receipt — the facts a device durably stores."""

    return service.reconcile_expired_command(
        session_id=session_id,
        binding_ref="binding.1",
        credential=CREDENTIAL_1,
        command_id=admission.command_id,
        admission_ref=admission_ref if admission_ref is not None else admission.admission_ref,
        revision_ref=revision_ref if revision_ref is not None else admission.revision_ref,
        request_id=request_id if request_id is not None else admission.request_id,
        request_fingerprint=request_fingerprint if request_fingerprint is not None else admission.request_fingerprint,
        termination=termination,
        exit_code=exit_code,
        now=now,
    )


def error_code(exc_info) -> str:
    assert isinstance(exc_info.value, ControlPlaneContractError)
    return exc_info.value.code


def poll_now(service, *, session_id: str = "session.1", now: datetime = AFTER_EXPIRY):
    return service.poll(
        session_id=session_id,
        binding_ref="binding.1",
        credential=CREDENTIAL_1,
        after_sequence=0,
        now=now,
    )


def test_expired_admitted_reconciles_to_acknowledged_with_late_terminal_result():
    service = authority()
    register(service)
    session = open_session(service)
    enqueue(service)
    admission = admit(service)
    admitted_before = stored(service, admission)

    reconciled = reconcile(
        service,
        admission=admission,
        termination="exited",
        exit_code=0,
    )

    assert reconciled.state is BrokerCommandState.ACKNOWLEDGED
    assert reconciled.acknowledged_at == EXPIRED_AT
    assert reconciled.termination == "exited"
    assert reconciled.exit_code == 0
    # Correlation is preserved verbatim: reconciliation mints nothing.
    assert reconciled.sequence == admission.sequence
    assert reconciled.revision_ref == admission.revision_ref
    assert reconciled.request_fingerprint == admission.request_fingerprint
    assert reconciled.admission_ref == admission.admission_ref
    assert reconciled.evidence_ref == admission.evidence_ref
    assert reconciled.request_id == admission.request_id
    assert reconciled.admitted_session_id == session.session_id
    assert reconciled.admitted_at == admitted_before.admitted_at
    # A reconciled command is terminal: never pollable, never re-admittable.
    assert poll_now(service) == ()
    with pytest.raises(ControlPlaneContractError) as readmit:
        admit(service, now=AFTER_EXPIRY)
    assert error_code(readmit) == "broker_command_replay"


def test_expired_admitted_without_execution_evidence_fails_closed_to_expired():
    service = authority()
    register(service)
    open_session(service)
    enqueue(service)
    admission = admit(service)

    reconciled = reconcile(service, admission=admission)

    assert reconciled.state is BrokerCommandState.EXPIRED
    # The fail-closed outcome fabricates no execution fact.
    assert reconciled.acknowledged_at is None
    assert reconciled.termination is None
    assert reconciled.exit_code is None
    assert reconciled.revision_ref == admission.revision_ref
    assert reconciled.request_fingerprint == admission.request_fingerprint
    assert poll_now(service) == ()
    with pytest.raises(ControlPlaneContractError) as readmit:
        admit(service, now=AFTER_EXPIRY)
    assert error_code(readmit) == "broker_command_replay"
    with pytest.raises(ControlPlaneContractError) as late_ack:
        service.acknowledge(
            session_id="session.1",
            binding_ref="binding.1",
            credential=CREDENTIAL_1,
            command_id=admission.command_id,
            admission_ref=admission.admission_ref,
            evidence_ref=admission.evidence_ref,
            revision_ref=admission.revision_ref,
            termination="exited",
            request_id=admission.request_id,
            exit_code=0,
            now=AFTER_EXPIRY,
        )
    assert error_code(late_ack) == "broker_ack_without_admission"


def test_reconciliation_before_expiry_is_refused_so_the_canonical_path_stays_authoritative():
    service = authority()
    register(service)
    open_session(service)
    enqueue(service)
    admission = admit(service)

    with pytest.raises(ControlPlaneContractError) as early:
        reconcile(
            service,
            admission=admission,
            termination="exited",
            exit_code=0,
            now=NOW + timedelta(seconds=4),
        )
    assert error_code(early) == "broker_command_not_expired"

    # The pre-deadline terminal path is unchanged.
    acknowledged = service.acknowledge(
        session_id="session.1",
        binding_ref="binding.1",
        credential=CREDENTIAL_1,
        command_id=admission.command_id,
        admission_ref=admission.admission_ref,
        evidence_ref=admission.evidence_ref,
        revision_ref=admission.revision_ref,
        termination="exited",
        request_id=admission.request_id,
        exit_code=0,
        now=NOW + timedelta(seconds=5),
    )
    assert acknowledged.state is BrokerCommandState.ACKNOWLEDGED


def test_reconciliation_requires_exact_admission_correlation():
    service = authority()
    register(service)
    open_session(service)
    enqueue(service)
    admission = admit(service)

    with pytest.raises(ControlPlaneContractError) as wrong_admission:
        reconcile(service, admission=admission, admission_ref="admission.other")
    assert error_code(wrong_admission) == "broker_reconcile_correlation_mismatch"

    with pytest.raises(ControlPlaneContractError) as wrong_revision:
        reconcile(service, admission=admission, revision_ref="rev." + "0" * 32)
    assert error_code(wrong_revision) == "broker_reconcile_revision_mismatch"

    with pytest.raises(ControlPlaneContractError) as wrong_request_id:
        reconcile(service, admission=admission, request_id="request.other")
    assert error_code(wrong_request_id) == "broker_reconcile_request_id_mismatch"

    with pytest.raises(ControlPlaneContractError) as wrong_fingerprint:
        reconcile(service, admission=admission, request_fingerprint="f" * 64)
    assert error_code(wrong_fingerprint) == "broker_reconcile_fingerprint_mismatch"

    with pytest.raises(ControlPlaneContractError) as wrong_binding:
        service.reconcile_expired_command(
            session_id="session.1",
            binding_ref="binding.other",
            credential=CREDENTIAL_1,
            command_id=admission.command_id,
            admission_ref=admission.admission_ref,
            revision_ref=admission.revision_ref,
            request_id=admission.request_id,
            request_fingerprint=admission.request_fingerprint,
            termination=None,
            exit_code=None,
            now=EXPIRED_AT,
        )
    assert error_code(wrong_binding) == "device_binding_not_found"

    assert stored(service, admission).state is BrokerCommandState.ADMITTED


def test_reconciliation_from_a_fresh_session_after_restart_is_admission_correlated():
    service = authority()
    register(service)
    open_session(service)
    enqueue(service)
    admission = admit(service)

    # The device restarts: a brand-new session on the same binding reconciles.
    # Correlation binds to the admission, not to the session that admitted it.
    restarted_session = service.open_session(
        session_id="session.2",
        binding_ref="binding.1",
        credential=CREDENTIAL_1,
        account_ref="account.1",
        workspace_ref="workspace.1",
        now=NOW + timedelta(seconds=200),
    )
    reconciled = reconcile(
        service,
        admission=admission,
        session_id=restarted_session.session_id,
        termination="exited",
        exit_code=3,
    )
    assert reconciled.state is BrokerCommandState.ACKNOWLEDGED
    assert reconciled.admitted_session_id == "session.1"


def test_reconciliation_is_terminal_and_never_reopens():
    service = authority()
    register(service)
    open_session(service)
    enqueue(service)
    admission = admit(service)

    acknowledged = reconcile(service, admission=admission, termination="exited", exit_code=0)
    with pytest.raises(ControlPlaneContractError) as repeated_result:
        reconcile(service, admission=admission, termination="exited", exit_code=0, now=AFTER_EXPIRY)
    assert error_code(repeated_result) == "broker_command_not_reconcilable"
    with pytest.raises(ControlPlaneContractError) as unknown_after_result:
        reconcile(service, admission=admission, now=AFTER_EXPIRY)
    assert error_code(unknown_after_result) == "broker_command_not_reconcilable"
    assert stored(service, admission) == acknowledged

    enqueue(service, command_id="command.2", now=NOW + timedelta(seconds=6))
    second = admit(service, command_id="command.2", now=NOW + timedelta(seconds=7))
    # command.2 expires at NOW+306, so its reconciliation moment is its own.
    expired = reconcile(service, admission=second, now=NOW + timedelta(seconds=307))
    assert expired.state is BrokerCommandState.EXPIRED
    with pytest.raises(ControlPlaneContractError) as repeat_expired:
        reconcile(service, admission=second, now=NOW + timedelta(seconds=308))
    assert error_code(repeat_expired) == "broker_command_not_reconcilable"
    assert stored(service, second) == expired


def test_reconciliation_rejects_invalid_outcome_payloads():
    service = authority()
    register(service)
    open_session(service)
    enqueue(service)
    admission = admit(service)

    with pytest.raises(ControlPlaneContractError) as fabricated_termination:
        reconcile(service, admission=admission, termination="raw_stdout_passthrough")
    assert error_code(fabricated_termination) == "broker_reconcile_invalid_termination"

    with pytest.raises(ControlPlaneContractError) as exit_code_without_outcome:
        reconcile(service, admission=admission, exit_code=0)
    assert error_code(exit_code_without_outcome) == "broker_reconcile_invalid_termination"

    assert stored(service, admission).state is BrokerCommandState.ADMITTED


def test_source_truth_constants_preserve_expired_reconciliation_boundaries():
    assert EXPIRED_ADMITTED_PERMANENT_STUCK is False
    assert EXPIRED_ADMITTED_RECONCILIATION_PATH is True
    assert LATE_TERMINAL_RESULT_RECONCILIATION is True
    assert UNKNOWN_EXECUTION_OUTCOME_FAILS_CLOSED is True
    assert AUTOMATIC_COMMAND_REPLAY is False
    assert AUTOMATIC_REEXECUTION is False
    assert TERMINAL_REOPEN is False
    assert SECOND_SEQUENCE_MINT is False
    assert SECOND_REVISION_MINT is False
    assert SECOND_FINGERPRINT_AUTHORITY is False
    assert RECONCILIATION_MINTS_CORRELATION is False
    assert RECONCILIATION_ALLOWABLE_STATES == frozenset({BrokerCommandState.ADMITTED})
    assert RECONCILIATION_TERMINAL_STATES == frozenset(
        {BrokerCommandState.ACKNOWLEDGED, BrokerCommandState.EXPIRED}
    )
    assert RAW_CREDENTIAL_LOG is False
