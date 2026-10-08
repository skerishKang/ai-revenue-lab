"""#3782: distinct durable capability with legacy process-only RPC preserved."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker import (
    BrokerCommandCapability,
    InMemoryLocalAgentBrokerAuthority,
)
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
from padiem_control_plane.local_agent_broker_state import LocalAgentBrokerStateSnapshot
from padiem_control_plane.local_agent_broker_state_wire import (
    LocalAgentBrokerStateJsonCodec,
)

NOW = datetime(2026, 10, 8, 10, tzinfo=timezone.utc)
CREDENTIAL = b"distinct-capability-device-credential"
FINGERPRINT = "a" * 64


def prepared():
    broker = InMemoryLocalAgentBrokerAuthority(
        pepper=b"distinct-capability-broker-pepper", authority_ref="broker.capability.3782"
    )
    broker.register_binding(
        binding_ref="binding.capability", device_id="device.capability",
        account_ref="account.capability", workspace_ref="workspace.capability",
        credential=CREDENTIAL, now=NOW - timedelta(seconds=20),
    )
    broker.open_session(
        session_id="session.capability", binding_ref="binding.capability",
        credential=CREDENTIAL, account_ref="account.capability",
        workspace_ref="workspace.capability", now=NOW - timedelta(seconds=10),
    )
    return broker


def enqueue(broker, capability=BrokerCommandCapability.BROWSER_CONTROL, command_id="command.browser"):
    return broker.enqueue_command(
        command_id=command_id, binding_ref="binding.capability",
        run_id="run.capability", tool_request_ref="tool.capability",
        request_fingerprint=FINGERPRINT, now=NOW,
        capability=capability,
    )


def test_typed_browser_work_survives_canonical_v2_state_recovery():
    broker = prepared()
    command = enqueue(broker)
    assert command.capability is BrokerCommandCapability.BROWSER_CONTROL
    snapshot = LocalAgentBrokerStateSnapshot(
        authority_ref=broker.authority_ref,
        bindings=tuple(broker._bindings.values()),
        sessions=tuple(broker._sessions.values()),
        commands=tuple(broker._commands.values()),
        last_sequence_by_binding=tuple(broker._last_sequence_by_binding.items()),
    )
    codec = LocalAgentBrokerStateJsonCodec()
    wire = codec.encode(snapshot)
    decoded = codec.decode(wire)
    assert decoded.commands[0].capability is BrokerCommandCapability.BROWSER_CONTROL
    assert codec.encode(decoded) == wire
    assert b'"capability":"browser.control"' in wire


def test_legacy_v2_without_capability_decodes_only_as_process_execute():
    broker = prepared()
    enqueue(broker, BrokerCommandCapability.PROCESS_EXECUTE)
    snapshot = LocalAgentBrokerStateSnapshot(
        authority_ref=broker.authority_ref,
        bindings=tuple(broker._bindings.values()),
        sessions=tuple(broker._sessions.values()),
        commands=tuple(broker._commands.values()),
        last_sequence_by_binding=tuple(broker._last_sequence_by_binding.items()),
    )
    codec = LocalAgentBrokerStateJsonCodec()
    old = json.loads(codec.encode(snapshot))
    del old["commands"][0]["capability"]
    restored = codec.decode(json.dumps(old).encode("utf-8"))
    assert restored.commands[0].capability is BrokerCommandCapability.PROCESS_EXECUTE
    assert b'"capability":"process.execute"' in codec.encode(restored)


@pytest.mark.parametrize("forgery", ["browser.open", "process.exec", "", None, True])
def test_unknown_capability_is_never_restored(forgery):
    broker = prepared()
    enqueue(broker, BrokerCommandCapability.PROCESS_EXECUTE)
    snapshot = LocalAgentBrokerStateSnapshot(
        authority_ref=broker.authority_ref,
        bindings=tuple(broker._bindings.values()),
        sessions=tuple(broker._sessions.values()),
        commands=tuple(broker._commands.values()),
        last_sequence_by_binding=tuple(broker._last_sequence_by_binding.items()),
    )
    codec = LocalAgentBrokerStateJsonCodec()
    wire = json.loads(codec.encode(snapshot))
    wire["commands"][0]["capability"] = forgery
    with pytest.raises((ControlPlaneContractError, ValueError)):
        codec.decode(json.dumps(wire).encode("utf-8"))


def test_old_process_poll_does_not_advertise_browser_control_command():
    broker = prepared()
    enqueue(broker)
    process = enqueue(
        broker, BrokerCommandCapability.PROCESS_EXECUTE, "command.process"
    )
    polled = broker.poll(
        session_id="session.capability", binding_ref="binding.capability",
        credential=CREDENTIAL, after_sequence=0, now=NOW + timedelta(seconds=1),
    )
    assert [command.command_id for command in polled] == [process.command_id]
    assert [command.capability for command in polled] == [
        BrokerCommandCapability.PROCESS_EXECUTE
    ]


def test_old_process_admission_refuses_browser_control_without_mutating_state():
    broker = prepared()
    command = enqueue(broker)
    with pytest.raises(ControlPlaneContractError) as exc:
        broker.admit_command(
            admission_ref="admission.browser", evidence_ref="evidence.browser",
            session_id="session.capability", binding_ref="binding.capability",
            credential=CREDENTIAL, command_id=command.command_id,
            request_fingerprint=FINGERPRINT, request_id="request.browser",
            now=NOW + timedelta(seconds=1),
        )
    assert exc.value.code == "broker_command_capability_mismatch"
    assert broker._commands[command.command_id].state.value == "queued"


def test_existing_facade_cannot_mint_browser_control_by_extra_wire_key():
    broker = prepared()
    facade = LocalAgentBrokerRpcFacade(authority=broker)
    result = facade.enqueue_command({
        "command_id": "command.rpc", "binding_ref": "binding.capability",
        "run_id": "run.capability", "tool_request_ref": "tool.capability",
        "request_fingerprint": FINGERPRINT, "now": NOW.isoformat(),
        "capability": "browser.control",
    })
    assert result["ok"] is True
    assert "capability" not in result["command"]  # legacy closed projection unchanged
    assert broker._commands["command.rpc"].capability is BrokerCommandCapability.PROCESS_EXECUTE


def test_retry_cannot_change_work_class_and_process_retry_remains_exact():
    broker = prepared()
    enqueue(broker)
    with pytest.raises(ControlPlaneContractError) as exc:
        enqueue(broker, BrokerCommandCapability.PROCESS_EXECUTE)
    assert exc.value.code == "duplicate_broker_command"
    exact = enqueue(broker)
    assert exact.capability is BrokerCommandCapability.BROWSER_CONTROL


def test_untyped_and_string_capability_refused_even_to_internal_core():
    broker = prepared()
    with pytest.raises(ControlPlaneContractError):
        enqueue(broker, "browser.control")
    assert not broker._commands


def test_process_argv_material_store_rejects_typed_browser_command():
    from local_agent_broker_material_store import (
        CloudflareDurableObjectCommandMaterialStore,
    )

    broker = prepared()
    browser_command = enqueue(broker)
    # The old local command material format MUST NOT become an argv shim for
    # browser.control, even when a caller names the exact canonical command.
    old_process_wire = {
        "contract_version": "claw-local-command-material.v2",
        "command_id": browser_command.command_id,
        "binding_ref": browser_command.binding_ref,
        "sequence": browser_command.sequence,
        "request_fingerprint": browser_command.request_fingerprint,
        "revision_ref": browser_command.revision_ref,
        "material": {"argv": ["python", "-c", "print('wrong lane')"]},
    }
    store = object.__new__(CloudflareDurableObjectCommandMaterialStore)
    with pytest.raises(ValueError, match="process.execute material"):
        store._validate_wire(old_process_wire, command=browser_command)


def test_legacy_process_command_public_projection_is_exactly_unchanged():
    broker = prepared()
    process = enqueue(
        broker, BrokerCommandCapability.PROCESS_EXECUTE, "command.process"
    )
    projection = process.safe_dict()
    assert "capability" not in projection
    assert "raw_argv" in projection and projection["raw_argv"] is False
    assert "p01_approval_payload" in projection and projection["p01_approval_payload"] is False
