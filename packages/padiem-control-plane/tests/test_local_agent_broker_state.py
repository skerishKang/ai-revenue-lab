from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker import (
    BrokerDeviceBinding,
    BrokerDeviceSession,
)
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
from padiem_control_plane.local_agent_broker_state import (
    ATOMIC_COMPARE_AND_SWAP,
    BINDING_STATE_PERSISTABLE,
    CANONICAL_BROKER_AUTHORITY_REUSED,
    COMMAND_STATE_PERSISTABLE,
    DURABLE_BROKER_STATE_PORT_DEFINED,
    IN_MEMORY_STATE_PORT_COUNTS_AS_DURABLE,
    MONOTONIC_SEQUENCE_PERSISTABLE,
    PRODUCTION_DATABASE_SELECTED,
    PRODUCTION_MUTATION,
    PRODUCTION_READY,
    PRODUCTION_STORE_CONFIGURED,
    RAW_DEVICE_CREDENTIAL_PERSISTED,
    ROTATION_REVOCATION_ATOMIC,
    SECOND_REPLAY_SEQUENCE_AUTHORITY,
    SESSION_STATE_PERSISTABLE,
    VERSIONED_BROKER_SNAPSHOT,
    InMemoryLocalAgentBrokerStatePort,
    LocalAgentBrokerStateSnapshot,
    StateBackedLocalAgentBrokerAuthority,
)

BASE = datetime(2026, 9, 4, 1, 0, tzinfo=timezone.utc)
PEPPER = b"state-backed-broker-test-pepper"
CREDENTIAL_1 = b"state-backed-device-credential-1"
CREDENTIAL_2 = b"state-backed-device-credential-2"
FINGERPRINT_1 = "a" * 64
FINGERPRINT_2 = "b" * 64
AUTHORITY_REF = "control-plane.local-agent-broker.state-test.v1"


def _authority(port: InMemoryLocalAgentBrokerStatePort) -> StateBackedLocalAgentBrokerAuthority:
    return StateBackedLocalAgentBrokerAuthority(
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        state_port=port,
    )


def _register(authority: StateBackedLocalAgentBrokerAuthority):
    return authority.register_binding(
        binding_ref="binding.state.1",
        device_id="device.state.1",
        account_ref="account.state.1",
        workspace_ref="workspace.state.1",
        credential=CREDENTIAL_1,
        now=BASE,
    )


def _session(authority: StateBackedLocalAgentBrokerAuthority, *, credential: bytes = CREDENTIAL_1, now=BASE + timedelta(seconds=1)):
    return authority.open_session(
        session_id="session.state.1",
        binding_ref="binding.state.1",
        credential=credential,
        account_ref="account.state.1",
        workspace_ref="workspace.state.1",
        now=now,
    )


def test_snapshot_roundtrip_and_safe_projection_exclude_raw_credential() -> None:
    port = InMemoryLocalAgentBrokerStatePort()
    authority = _authority(port)
    binding = _register(authority)
    session = _session(authority)
    command = authority.enqueue_command(
        command_id="command.state.1",
        binding_ref=binding.binding_ref,
        run_id="run.state.1",
        tool_request_ref="tool-request.state.1",
        request_fingerprint=FINGERPRINT_1,
        now=BASE + timedelta(seconds=2),
    )

    stored = port.load(authority_ref=AUTHORITY_REF)
    snapshot = stored.snapshot
    assert snapshot.bindings == (binding,)
    assert snapshot.sessions == (session,)
    assert snapshot.commands == (command,)
    assert snapshot.last_sequence_by_binding == ((binding.binding_ref, 1),)
    assert snapshot.safe_dict()["raw_device_credential"] is False
    assert snapshot.safe_dict()["credential_digest_exposed"] is False
    assert CREDENTIAL_1.decode() not in repr(snapshot)

    restored = snapshot.restore(pepper=PEPPER)
    recaptured = LocalAgentBrokerStateSnapshot.capture(restored)
    assert recaptured == snapshot


def test_snapshot_rejects_cross_record_session_binding_mismatch() -> None:
    binding = BrokerDeviceBinding(
        binding_ref="binding.state.1",
        device_id="device.state.1",
        account_ref="account.state.1",
        workspace_ref="workspace.state.1",
        credential_generation=1,
        credential_digest="c" * 64,
        issued_at=BASE,
        credential_expires_at=BASE + timedelta(days=1),
    )
    mismatched = BrokerDeviceSession(
        session_id="session.state.1",
        binding_ref=binding.binding_ref,
        device_id=binding.device_id,
        account_ref="account.other",
        workspace_ref=binding.workspace_ref,
        credential_generation=1,
        issued_at=BASE + timedelta(seconds=1),
        expires_at=BASE + timedelta(minutes=10),
    )
    with pytest.raises(ControlPlaneContractError) as caught:
        LocalAgentBrokerStateSnapshot(
            authority_ref=AUTHORITY_REF,
            bindings=(binding,),
            sessions=(mismatched,),
        )
    assert caught.value.code == "invalid_local_agent_broker_state"


def test_in_memory_state_port_cas_rejects_stale_writer_and_is_not_durable() -> None:
    port = InMemoryLocalAgentBrokerStatePort()
    initial = port.load(authority_ref=AUTHORITY_REF)
    assert initial.version == 0
    first = port.compare_and_swap(
        authority_ref=AUTHORITY_REF,
        expected_version=0,
        snapshot=initial.snapshot,
    )
    assert first.version == 1
    with pytest.raises(ControlPlaneContractError) as caught:
        port.compare_and_swap(
            authority_ref=AUTHORITY_REF,
            expected_version=0,
            snapshot=initial.snapshot,
        )
    assert caught.value.code == "stale_local_agent_broker_state"
    assert port.safe_dict() == {
        "atomic_compare_and_swap": True,
        "durable": False,
        "production_store": False,
    }


def test_restart_preserves_monotonic_sequence_and_latest_poll_state() -> None:
    port = InMemoryLocalAgentBrokerStatePort()
    first_process = _authority(port)
    _register(first_process)
    session = _session(first_process)
    command1 = first_process.enqueue_command(
        command_id="command.state.1",
        binding_ref="binding.state.1",
        run_id="run.state.1",
        tool_request_ref="tool-request.state.1",
        request_fingerprint=FINGERPRINT_1,
        now=BASE + timedelta(seconds=2),
    )
    assert command1.sequence == 1

    restarted = _authority(port)
    command2 = restarted.enqueue_command(
        command_id="command.state.2",
        binding_ref="binding.state.1",
        run_id="run.state.2",
        tool_request_ref="tool-request.state.2",
        request_fingerprint=FINGERPRINT_2,
        now=BASE + timedelta(seconds=3),
    )
    assert command2.sequence == 2
    polled = restarted.poll(
        session_id=session.session_id,
        binding_ref="binding.state.1",
        credential=CREDENTIAL_1,
        after_sequence=0,
        now=BASE + timedelta(seconds=4),
    )
    assert [item.sequence for item in polled] == [1, 2]


def test_rotation_and_revocation_survive_restart_and_remove_stale_sessions_atomically() -> None:
    port = InMemoryLocalAgentBrokerStatePort()
    authority = _authority(port)
    _register(authority)
    _session(authority)
    rotated = authority.rotate_credential(
        "binding.state.1",
        expected_generation=1,
        new_credential=CREDENTIAL_2,
        now=BASE + timedelta(seconds=2),
    )
    assert rotated.credential_generation == 2
    assert port.load(authority_ref=AUTHORITY_REF).snapshot.sessions == ()

    restarted = _authority(port)
    with pytest.raises(ControlPlaneContractError) as old_credential:
        restarted.open_session(
            session_id="session.state.old",
            binding_ref="binding.state.1",
            credential=CREDENTIAL_1,
            account_ref="account.state.1",
            workspace_ref="workspace.state.1",
            now=BASE + timedelta(seconds=3),
        )
    assert old_credential.value.code == "invalid_device_credential"

    restarted.open_session(
        session_id="session.state.2",
        binding_ref="binding.state.1",
        credential=CREDENTIAL_2,
        account_ref="account.state.1",
        workspace_ref="workspace.state.1",
        now=BASE + timedelta(seconds=3),
    )
    restarted.revoke_binding("binding.state.1", now=BASE + timedelta(seconds=4))
    assert port.load(authority_ref=AUTHORITY_REF).snapshot.sessions == ()

    after_revoke_restart = _authority(port)
    with pytest.raises(ControlPlaneContractError) as revoked:
        after_revoke_restart.open_session(
            session_id="session.state.3",
            binding_ref="binding.state.1",
            credential=CREDENTIAL_2,
            account_ref="account.state.1",
            workspace_ref="workspace.state.1",
            now=BASE + timedelta(seconds=5),
        )
    assert revoked.value.code == "device_binding_revoked"


def test_admission_and_ack_replay_state_survives_restart() -> None:
    port = InMemoryLocalAgentBrokerStatePort()
    authority = _authority(port)
    _register(authority)
    session = _session(authority)
    command = authority.enqueue_command(
        command_id="command.state.1",
        binding_ref="binding.state.1",
        run_id="run.state.1",
        tool_request_ref="tool-request.state.1",
        request_fingerprint=FINGERPRINT_1,
        now=BASE + timedelta(seconds=2),
    )
    admission = authority.admit_command(
        admission_ref="admission.state.1",
        evidence_ref="evidence.state.1",
        session_id=session.session_id,
        binding_ref="binding.state.1",
        credential=CREDENTIAL_1,
        command_id=command.command_id,
        request_fingerprint=FINGERPRINT_1,
        now=BASE + timedelta(seconds=3),
    )

    restarted = _authority(port)
    with pytest.raises(ControlPlaneContractError) as replay:
        restarted.admit_command(
            admission_ref="admission.state.2",
            evidence_ref="evidence.state.2",
            session_id=session.session_id,
            binding_ref="binding.state.1",
            credential=CREDENTIAL_1,
            command_id=command.command_id,
            request_fingerprint=FINGERPRINT_1,
            now=BASE + timedelta(seconds=4),
        )
    assert replay.value.code == "broker_command_replay"

    acknowledged = restarted.acknowledge(
        session_id=session.session_id,
        binding_ref="binding.state.1",
        credential=CREDENTIAL_1,
        command_id=command.command_id,
        admission_ref=admission.admission_ref,
        evidence_ref=admission.evidence_ref,
        now=BASE + timedelta(seconds=5),
    )
    assert acknowledged.state.value == "acknowledged"

    restarted_again = _authority(port)
    with pytest.raises(ControlPlaneContractError) as ack_replay:
        restarted_again.acknowledge(
            session_id=session.session_id,
            binding_ref="binding.state.1",
            credential=CREDENTIAL_1,
            command_id=command.command_id,
            admission_ref=admission.admission_ref,
            evidence_ref=admission.evidence_ref,
            now=BASE + timedelta(seconds=6),
        )
    assert ack_replay.value.code == "broker_ack_without_admission"


def test_two_stale_writers_cannot_both_persist_same_next_sequence() -> None:
    port = InMemoryLocalAgentBrokerStatePort()
    authority = _authority(port)
    _register(authority)
    shared = port.load(authority_ref=AUTHORITY_REF)

    writer_a = shared.snapshot.restore(pepper=PEPPER)
    writer_b = shared.snapshot.restore(pepper=PEPPER)
    command_a = writer_a.enqueue_command(
        command_id="command.writer.a",
        binding_ref="binding.state.1",
        run_id="run.writer.a",
        tool_request_ref="tool-request.writer.a",
        request_fingerprint=FINGERPRINT_1,
        now=BASE + timedelta(seconds=2),
    )
    command_b = writer_b.enqueue_command(
        command_id="command.writer.b",
        binding_ref="binding.state.1",
        run_id="run.writer.b",
        tool_request_ref="tool-request.writer.b",
        request_fingerprint=FINGERPRINT_2,
        now=BASE + timedelta(seconds=2),
    )
    assert command_a.sequence == command_b.sequence == 1

    port.compare_and_swap(
        authority_ref=AUTHORITY_REF,
        expected_version=shared.version,
        snapshot=LocalAgentBrokerStateSnapshot.capture(writer_a),
    )
    with pytest.raises(ControlPlaneContractError) as stale:
        port.compare_and_swap(
            authority_ref=AUTHORITY_REF,
            expected_version=shared.version,
            snapshot=LocalAgentBrokerStateSnapshot.capture(writer_b),
        )
    assert stale.value.code == "stale_local_agent_broker_state"
    persisted = port.load(authority_ref=AUTHORITY_REF).snapshot
    assert [item.command_id for item in persisted.commands] == ["command.writer.a"]
    assert persisted.last_sequence_by_binding == (("binding.state.1", 1),)


def test_state_backed_authority_remains_compatible_with_existing_rpc_facade() -> None:
    port = InMemoryLocalAgentBrokerStatePort()
    rpc = LocalAgentBrokerRpcFacade(authority=_authority(port))
    result = rpc.register_binding(
        {
            "binding_ref": "binding.state.1",
            "device_id": "device.state.1",
            "account_ref": "account.state.1",
            "workspace_ref": "workspace.state.1",
            "credential_b64": base64.b64encode(CREDENTIAL_1).decode("ascii"),
            "now": BASE.isoformat(),
        }
    )
    assert result["ok"] is True
    assert result["binding"]["credential_digest_exposed"] is False
    assert port.load(authority_ref=AUTHORITY_REF).version == 1


def test_m2f_source_truth_does_not_claim_production_persistence() -> None:
    port = InMemoryLocalAgentBrokerStatePort()
    safe = _authority(port).safe_dict()
    assert safe["state_port_durable"] is False
    assert DURABLE_BROKER_STATE_PORT_DEFINED is True
    assert VERSIONED_BROKER_SNAPSHOT is True
    assert ATOMIC_COMPARE_AND_SWAP is True
    assert CANONICAL_BROKER_AUTHORITY_REUSED is True
    assert SECOND_REPLAY_SEQUENCE_AUTHORITY is False
    assert BINDING_STATE_PERSISTABLE is True
    assert SESSION_STATE_PERSISTABLE is True
    assert COMMAND_STATE_PERSISTABLE is True
    assert MONOTONIC_SEQUENCE_PERSISTABLE is True
    assert ROTATION_REVOCATION_ATOMIC is True
    assert RAW_DEVICE_CREDENTIAL_PERSISTED is False
    assert IN_MEMORY_STATE_PORT_COUNTS_AS_DURABLE is False
    assert PRODUCTION_DATABASE_SELECTED is False
    assert PRODUCTION_STORE_CONFIGURED is False
    assert PRODUCTION_MUTATION is False
    assert PRODUCTION_READY is False
