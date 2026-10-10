"""#3217 — non-Production trusted broker result Service Binding assembly."""

from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

import pytest

from kagent.contracts import ContractError
from kagent.local_agent_broker_pairing_handoff_entry import (
    LoopbackBrokerAuthorityServiceBinding,
    LoopbackPairingBroker,
    TERMINAL_RESULT_SERVICE_ROUTE,
)

BASE = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
FINGERPRINT = "b" * 64


def _terminal_broker() -> LoopbackPairingBroker:
    # #3650: the host principal is now injected, never defaulted.
    broker = LoopbackPairingBroker(account_ref="account.1", workspace_ref="workspace.1")
    authority = broker.authority
    authority.register_binding(
        binding_ref="binding.3217",
        device_id="device.3217",
        account_ref="account.1",
        workspace_ref="workspace.1",
        credential=b"3217-loopback-test-credential",
        now=BASE,
    )
    session = authority.open_session(
        session_id="session.3217",
        binding_ref="binding.3217",
        credential=b"3217-loopback-test-credential",
        account_ref="account.1",
        workspace_ref="workspace.1",
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
        credential=b"3217-loopback-test-credential",
        command_id=command.command_id,
        request_fingerprint=FINGERPRINT,
        request_id="request.3217",
        now=BASE + timedelta(seconds=3),
    )
    authority.acknowledge(
        session_id=session.session_id,
        binding_ref="binding.3217",
        credential=b"3217-loopback-test-credential",
        command_id=command.command_id,
        admission_ref="admission.3217",
        evidence_ref="evidence.3217",
        revision_ref=command.revision_ref,
        termination="exited",
        request_id="request.3217",
        exit_code=0,
        now=BASE + timedelta(seconds=4),
    )
    return broker


def test_loopback_result_read_uses_the_exact_execution_authority():
    broker = _terminal_broker()
    authority_identity = id(broker.authority)

    result = broker.terminal_command_result(
        {
            "account_ref": "account.1",
            "workspace_ref": "workspace.1",
            "run_id": "run.3217",
        }
    )

    assert id(broker.authority) == authority_identity
    assert result["ok"] is True
    assert result["command_result"]["command_id"] == "command.3217"
    assert result["command_result"]["state"] == "acknowledged"
    assert result["command_result"]["termination"] == "exited"


def test_result_binding_is_loopback_only_and_read_only():
    for url in (
        "https://127.0.0.1:9999",
        "http://example.com:9999",
        "http://127.0.0.1",
        "http://127.0.0.1:9999/path",
        "http://user@127.0.0.1:9999",
    ):
        with pytest.raises(ContractError):
            LoopbackBrokerAuthorityServiceBinding(url)

    binding = LoopbackBrokerAuthorityServiceBinding("http://127.0.0.1:9999")
    assert callable(binding.terminal_command_result)
    assert not hasattr(binding, "enqueue_command")
    assert not hasattr(binding, "admit_command")
    assert not hasattr(binding, "acknowledge")


class _Response:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit: int) -> bytes:
        return self._body[:limit]


def test_result_binding_calls_only_the_private_terminal_route():
    expected = {
        "ok": True,
        "available": False,
        "reason": "no_command_for_run",
    }
    binding = LoopbackBrokerAuthorityServiceBinding("http://127.0.0.1:43117")

    with patch("urllib.request.urlopen", return_value=_Response(expected)) as opened:
        result = binding.terminal_command_result(
            {
                "account_ref": "account.1",
                "workspace_ref": "workspace.1",
                "run_id": "run.3217",
            }
        )

    assert result == expected
    request = opened.call_args.args[0]
    assert request.full_url == f"http://127.0.0.1:43117{TERMINAL_RESULT_SERVICE_ROUTE}"
    assert request.method == "POST"
