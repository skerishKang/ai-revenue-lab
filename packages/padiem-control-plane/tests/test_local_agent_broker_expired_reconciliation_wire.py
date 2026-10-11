"""Issue #3121 — reconciliation survives a durable restart without replay.

Drives the real durable composition (StateBacked authority over the
serialized wire state port) through the real RPC facade payload shape:

* one expired ADMITTED command reconciles to ACKNOWLEDGED with its late
  terminal result, one fails closed to EXPIRED with no execution fact;
* the broker state is then reloaded from its serialized wire bytes — a
  restart — and both terminal states persist;
* after the restart nothing is pollable, nothing re-admits, repeated
  reconciliation is refused and no second correlation is ever minted.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker import BrokerCommandState
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
from padiem_control_plane.local_agent_broker_state import StateBackedLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_state_wire import (
    InMemorySerializedLocalAgentBrokerStateBackend,
    SerializedLocalAgentBrokerStatePort,
)

BASE = datetime(2026, 9, 4, 2, 0, tzinfo=timezone.utc)
PEPPER = b"serialized-broker-state-test-pepper"
CREDENTIAL_1 = b"serialized-device-credential-1"
FINGERPRINT_1 = "a" * 64
AUTHORITY_REF = "control-plane.local-agent-broker.wire-reconcile-test.v1"
COMMAND_TTL_SECONDS = 300
#: enqueue at BASE+2 with the module TTL, so the deadline passes here.
EXPIRED_AT = BASE + timedelta(seconds=2 + COMMAND_TTL_SECONDS)


def _credential_b64() -> str:
    return base64.b64encode(CREDENTIAL_1).decode("ascii")


def _authority(port: SerializedLocalAgentBrokerStatePort) -> StateBackedLocalAgentBrokerAuthority:
    return StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        state_port=port,
    )


def _reconcile_payload(admission, *, session_id: str, termination: str | None, exit_code: int | None) -> dict:
    return {
        "session_id": session_id,
        "binding_ref": "binding.wire.1",
        "credential_b64": _credential_b64(),
        "command_id": admission.command_id,
        "admission_ref": admission.admission_ref,
        "revision_ref": admission.revision_ref,
        "request_id": admission.request_id,
        "request_fingerprint": admission.request_fingerprint,
        "termination": termination,
        "exit_code": exit_code,
        "now": (EXPIRED_AT + timedelta(seconds=admission.sequence)).isoformat(),
    }


def test_reconciled_terminal_states_survive_a_restart_and_never_replay():
    backend = InMemorySerializedLocalAgentBrokerStateBackend()
    port = SerializedLocalAgentBrokerStatePort(backend=backend)
    authority = _authority(port)
    binding = authority.register_binding(
        binding_ref="binding.wire.1",
        device_id="device.wire.1",
        account_ref="account.wire.1",
        workspace_ref="workspace.wire.1",
        credential=CREDENTIAL_1,
        now=BASE,
    )
    authority.open_session(
        session_id="session.wire.1",
        binding_ref=binding.binding_ref,
        credential=CREDENTIAL_1,
        account_ref="account.wire.1",
        workspace_ref="workspace.wire.1",
        now=BASE + timedelta(seconds=1),
    )
    authority.enqueue_command(
        command_id="command.wire.1",
        binding_ref=binding.binding_ref,
        run_id="run.wire.1",
        tool_request_ref="tool-request.wire.1",
        request_fingerprint=FINGERPRINT_1,
        now=BASE + timedelta(seconds=2),
        ttl_seconds=COMMAND_TTL_SECONDS,
    )
    authority.enqueue_command(
        command_id="command.wire.2",
        binding_ref=binding.binding_ref,
        run_id="run.wire.1",
        tool_request_ref="tool-request.wire.2",
        request_fingerprint=FINGERPRINT_1,
        now=BASE + timedelta(seconds=2),
        ttl_seconds=COMMAND_TTL_SECONDS,
    )
    proven = authority.admit_command(
        admission_ref="admission.wire.1",
        evidence_ref="evidence.wire.1",
        session_id="session.wire.1",
        binding_ref=binding.binding_ref,
        credential=CREDENTIAL_1,
        command_id="command.wire.1",
        request_fingerprint=FINGERPRINT_1,
        request_id="request.wire.1",
        now=BASE + timedelta(seconds=3),
    )
    unproven = authority.admit_command(
        admission_ref="admission.wire.2",
        evidence_ref="evidence.wire.2",
        session_id="session.wire.1",
        binding_ref=binding.binding_ref,
        credential=CREDENTIAL_1,
        command_id="command.wire.2",
        request_fingerprint=FINGERPRINT_1,
        request_id="request.wire.2",
        now=BASE + timedelta(seconds=3),
    )

    # Reconcile through the real RPC facade payload shape.
    facade = LocalAgentBrokerRpcFacade(authority=authority)
    late_result = facade.reconcile_expired_command(
        _reconcile_payload(proven, session_id="session.wire.1", termination="exited", exit_code=0)
    )
    assert late_result["ok"] is True
    assert late_result["command"]["state"] == BrokerCommandState.ACKNOWLEDGED.value
    unknown = facade.reconcile_expired_command(
        _reconcile_payload(unproven, session_id="session.wire.1", termination=None, exit_code=None)
    )
    assert unknown["ok"] is True
    assert unknown["command"]["state"] == BrokerCommandState.EXPIRED.value
    assert unknown["command"]["termination"] is None
    assert unknown["command"]["exit_code"] is None
    assert unknown["command"]["acknowledged_at"] is None

    # Restart: a brand-new authority over the same serialized state.
    restarted_port = SerializedLocalAgentBrokerStatePort(backend=backend)
    restarted_authority = _authority(restarted_port)
    restarted_facade = LocalAgentBrokerRpcFacade(authority=restarted_authority)

    poll = restarted_facade.poll(
        {
            "session_id": "session.wire.1",
            "binding_ref": binding.binding_ref,
            "credential_b64": _credential_b64(),
            "after_sequence": 0,
            "now": (EXPIRED_AT + timedelta(seconds=10)).isoformat(),
        }
    )
    assert poll["ok"] is True
    assert poll["commands"] == []

    for admission in (proven, unproven):
        with pytest.raises(ControlPlaneContractError) as repeated:
            restarted_authority.reconcile_expired_command(
                session_id="session.wire.1",
                binding_ref=binding.binding_ref,
                credential=CREDENTIAL_1,
                command_id=admission.command_id,
                admission_ref=admission.admission_ref,
                revision_ref=admission.revision_ref,
                request_id=admission.request_id,
                request_fingerprint=admission.request_fingerprint,
                termination=None,
                exit_code=None,
                now=EXPIRED_AT + timedelta(seconds=20),
            )
        assert repeated.value.code == "broker_command_not_reconcilable"
        with pytest.raises(ControlPlaneContractError) as readmit:
            restarted_authority.admit_command(
                admission_ref=f"replay.{admission.command_id}",
                evidence_ref=f"replay-evidence.{admission.command_id}",
                session_id="session.wire.1",
                binding_ref=binding.binding_ref,
                credential=CREDENTIAL_1,
                command_id=admission.command_id,
                request_fingerprint=admission.request_fingerprint,
                request_id=admission.request_id,
                now=EXPIRED_AT + timedelta(seconds=20),
            )
        assert readmit.value.code == "broker_command_replay"

    # A brand-new command still enqueues with the next monotonic sequence —
    # reconciliation minted no second sequence for either terminal command.
    followup = restarted_authority.enqueue_command(
        command_id="command.wire.3",
        binding_ref=binding.binding_ref,
        run_id="run.wire.1",
        tool_request_ref="tool-request.wire.3",
        request_fingerprint=FINGERPRINT_1,
        now=EXPIRED_AT + timedelta(seconds=20),
    )
    assert followup.sequence == 3
