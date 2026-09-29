"""#3217 — shared canonical broker terminal-result projection."""

from datetime import datetime, timedelta, timezone

from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_state import (
    LocalAgentBrokerStateSnapshot,
    terminal_command_result_from_snapshot,
)

BASE = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
PEPPER = b"terminal-result-3217-broker-pepper"
CREDENTIAL = b"terminal-result-3217-device-credential"
FINGERPRINT = "a" * 64


def _terminal_snapshot() -> LocalAgentBrokerStateSnapshot:
    authority = InMemoryLocalAgentBrokerAuthority(
        pepper=PEPPER,
        authority_ref="broker.3217",
    )
    authority.register_binding(
        binding_ref="binding.3217",
        device_id="device.3217",
        account_ref="account.3217",
        workspace_ref="workspace.3217",
        credential=CREDENTIAL,
        now=BASE,
    )
    session = authority.open_session(
        session_id="session.3217",
        binding_ref="binding.3217",
        credential=CREDENTIAL,
        account_ref="account.3217",
        workspace_ref="workspace.3217",
        now=BASE + timedelta(seconds=1),
    )
    command = authority.enqueue_command(
        command_id="command.3217",
        binding_ref="binding.3217",
        run_id="run.3217",
        tool_request_ref="tool.3217",
        request_fingerprint=FINGERPRINT,
        now=BASE + timedelta(seconds=2),
    )
    authority.admit_command(
        admission_ref="admission.3217",
        evidence_ref="evidence.3217",
        session_id=session.session_id,
        binding_ref="binding.3217",
        credential=CREDENTIAL,
        command_id=command.command_id,
        request_fingerprint=FINGERPRINT,
        request_id="request.3217",
        now=BASE + timedelta(seconds=3),
    )
    authority.acknowledge(
        session_id=session.session_id,
        binding_ref="binding.3217",
        credential=CREDENTIAL,
        command_id=command.command_id,
        admission_ref="admission.3217",
        evidence_ref="evidence.3217",
        revision_ref=command.revision_ref,
        termination="exited",
        request_id="request.3217",
        exit_code=0,
        now=BASE + timedelta(seconds=4),
    )
    return LocalAgentBrokerStateSnapshot.capture(authority)


def test_terminal_projection_reads_only_canonical_snapshot_state():
    snapshot = _terminal_snapshot()
    before = snapshot

    result = terminal_command_result_from_snapshot(
        snapshot,
        {
            "account_ref": "account.3217",
            "workspace_ref": "workspace.3217",
            "run_id": "run.3217",
        },
    )

    assert snapshot == before
    assert result["ok"] is True
    assert result["available"] is True
    assert result["command_identity"]["command_id"] == "command.3217"
    terminal = result["command_result"]
    assert terminal["command_id"] == "command.3217"
    assert terminal["run_id"] == "run.3217"
    assert terminal["request_id"] == "request.3217"
    assert terminal["state"] == "acknowledged"
    assert terminal["termination"] == "exited"
    assert terminal["exit_code"] == 0
    assert terminal["raw_argv"] is False
    assert terminal["raw_file_content"] is False
    assert terminal["raw_device_credential"] is False
    assert terminal["p01_approval_payload"] is False


def test_terminal_projection_is_owner_workspace_scoped_and_closed():
    snapshot = _terminal_snapshot()

    foreign = terminal_command_result_from_snapshot(
        snapshot,
        {
            "account_ref": "account.3217",
            "workspace_ref": "workspace.foreign",
            "run_id": "run.3217",
        },
    )
    assert foreign == {"ok": True, "available": False, "reason": "no_device_binding"}

    injected = terminal_command_result_from_snapshot(
        snapshot,
        {
            "account_ref": "account.3217",
            "workspace_ref": "workspace.3217",
            "run_id": "run.3217",
            "conversation_id": "conversation.browser.chosen",
        },
    )
    assert injected["ok"] is False
    assert injected["error"]["code"] == "invalid_terminal_result_request"
