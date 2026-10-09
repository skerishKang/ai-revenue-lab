"""#3782 source-only original HUMAN-P01 Engine receipt -> queued Broker admission.

Every test uses a synthetic authenticated Engine client, NOT a production owner
writer or real consent. Product still has no configured issuer, P01 client, or
device Browser Use activation. Persisted pending tickets alone never admit.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from local_agent_broker_browser_control_take import BrowserControlCommandTakeCorrelation
from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime
from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker import (
    BrokerCommandCapability,
    BrokerCommandState,
)
from test_local_agent_broker_enqueue_material_atomicity import (
    CREDENTIAL,
    _Env,
    _runtime,
)
from test_local_agent_broker_pending_browser_issue_3782 import (
    CURRENT,
    _commands,
    _issue,
    _rows,
    _setup,
)


def _original():
    return {
        "app_id": "padiem.browser.test",
        "continuation_ref": "cont_3782pendingbrowser",
        "user_subject_id": "user.owner.3782",
        "original_request_fingerprint": "b" * 64,
        "original_admission_decision_id": "engine.admit.3782",
        "run_id": "engine.run.3782",
        "invocation_sha256": "c" * 64,
        "user_approval_evidence_ref": "owner.p01.approved.3782",
    }


class _AuthenticatedEngineFixture:
    """Simulates actual Engine authenticated post-human-resume D1 read."""

    app_id = "padiem.browser.test"

    def __init__(self, result=None):
        self.result = _original() if result is None else result
        self.calls = 0

    async def read_browser_control_original_admission(self, *, continuation_ref):
        self.calls += 1
        await asyncio.sleep(0)
        assert continuation_ref == "cont_3782pendingbrowser"
        return self.result


def _prepare(tmp_path, *, result=None, after_lookup=None):
    file, broker, _source = _setup(tmp_path)
    issued = _issue(broker)
    engine = _AuthenticatedEngineFixture(result)
    trusted = LocalAgentBrokerDurableRuntime(
        storage=broker._storage,
        env=_Env(),
        pending_browser_engine_client=engine,
        browser_admission_clock=lambda: CURRENT if after_lookup is None else after_lookup,
    )
    return file, trusted, engine, issued


def _admit(broker, *, credential=CREDENTIAL, binding_ref="binding.atomic.1",
           session_ref="session.atomic.1"):
    return asyncio.run(
        broker._admit_pending_browser_command_from_original_engine_async(
            command_ref=_commands(broker)[0].command_id,
            binding_ref=binding_ref, session_ref=session_ref,
            credential=credential, now=CURRENT,
        )
    )


def test_verified_original_human_p01_admits_queued_browser_only_with_atomic_join(tmp_path):
    file, broker, engine, issued = _prepare(tmp_path)
    reply = _admit(broker)
    assert engine.calls == 1
    assert reply["admitted"] is True
    assert reply["capability"] == "browser.control"
    assert reply["human_approval_evidence_recorded"] is True
    assert reply["action_material_registered"] is False
    assert reply["browser_action_executed"] is False
    assert reply["command_ref"] == issued["command_ref"]
    assert reply["request_id"].startswith("browser.req.")
    assert reply["admission_ref"].startswith("browser.adm.")
    (command,) = _commands(broker)
    assert command.state is BrokerCommandState.ADMITTED
    assert command.capability is BrokerCommandCapability.BROWSER_CONTROL
    assert command.admission_ref == reply["admission_ref"]
    assert command.evidence_ref == _original()["user_approval_evidence_ref"]
    assert command.request_id == reply["request_id"]
    scope = BrowserControlCommandTakeCorrelation(
        command_ref=command.command_id,
        session_ref="session.atomic.1",
        binding_ref=command.binding_ref,
        request_id=command.request_id,
        run_ref=command.run_id,
        workspace_ref="workspace.atomic.1",
        owner_ref="user.owner.3782",
        device_ref="device.atomic.1",
        request_fingerprint=command.request_fingerprint,
        admission_ref=command.admission_ref,
        revision_ref=command.revision_ref,
    )
    original = broker.browser_engine_join_store.resolve_for_admitted_command(
        scope=scope, now=CURRENT,
    )
    assert original.engine_request_sha256 == "b" * 64
    assert original.browser_invocation_sha256 == "c" * 64
    assert original.user_p01_evidence_ref == command.evidence_ref
    assert _rows(broker)[0][4] is None
    assert broker._storage.connection.execute(
        "SELECT COUNT(*) FROM local_agent_browser_control_command_take"
    ).fetchone()[0] == 0
    restarted = _runtime(file)
    assert _commands(restarted)[0] == command
    assert restarted.browser_engine_join_store.resolve_for_admitted_command(
        scope=scope, now=CURRENT,
    ) == original
    assert restarted._pending_browser_engine_client is None
    with pytest.raises(ValueError, match="not wired"):
        _admit(restarted)
    with pytest.raises(ValueError, match="cannot be admitted"):
        _admit(broker)


@pytest.mark.parametrize("bad_field,bad_value", [
    ("app_id", "foreign.app"),
    ("continuation_ref", "cont_foreign"),
    ("user_subject_id", "other.user"),
    ("original_request_fingerprint", "f" * 64),
    ("original_admission_decision_id", "other.engine.admission"),
    ("run_id", "other.engine.run"),
    ("invocation_sha256", "f" * 64),
    ("user_approval_evidence_ref", ""),
])
def test_wrong_original_engine_receipt_refuses_without_admission(tmp_path,bad_field,bad_value):
    original = _original()
    original[bad_field] = bad_value
    file, broker, _engine, _issued = _prepare(tmp_path, result=original)
    with pytest.raises(ValueError):
        _admit(broker)
    assert _commands(broker)[0].state is BrokerCommandState.QUEUED
    assert broker._storage.connection.execute(
        "SELECT COUNT(*) FROM local_agent_browser_engine_original_join"
    ).fetchone()[0] == 0
    assert _commands(_runtime(file))[0].state is BrokerCommandState.QUEUED


def test_missing_human_p01_receipt_cannot_admit(tmp_path):
    file, broker, _engine, _issued = _prepare(tmp_path, result={})
    with pytest.raises(ValueError, match="receipt missing"):
        _admit(broker)
    assert _commands(_runtime(file))[0].state is BrokerCommandState.QUEUED


def test_unauthenticated_device_cannot_read_original_engine_or_admit(tmp_path):
    _file, broker, engine, _issued = _prepare(tmp_path)
    with pytest.raises(ControlPlaneContractError, match="credential"):
        _admit(broker, credential=b"device.unauthorized")
    assert engine.calls == 0
    assert _commands(broker)[0].state is BrokerCommandState.QUEUED


def test_different_binding_or_session_fails_before_engine_read(tmp_path):
    _file, broker, engine, _issued = _prepare(tmp_path)
    with pytest.raises(ControlPlaneContractError, match="binding"):
        _admit(broker, binding_ref="binding.other")
    with pytest.raises(ControlPlaneContractError, match="session"):
        _admit(broker, session_ref="session.other")
    assert engine.calls == 0
    assert _commands(broker)[0].state is BrokerCommandState.QUEUED


def test_slow_engine_response_cannot_resurrect_expired_pending_command(tmp_path):
    clock = CURRENT + timedelta(minutes=6)
    file, broker, engine, _issued = _prepare(tmp_path, after_lookup=clock)
    with pytest.raises(ValueError, match="pending browser command"):
        _admit(broker)
    assert engine.calls == 1
    assert _commands(_runtime(file))[0].state is BrokerCommandState.QUEUED


def test_engine_join_storage_failure_rolls_back_canonical_admission(tmp_path):
    file, broker, _engine, _issued = _prepare(tmp_path)
    def fails(*_args, **_kwargs):
        raise RuntimeError("synthetic join D1 crash")
    broker.browser_engine_join_store._register_in_existing_transaction = fails
    with pytest.raises(RuntimeError, match="synthetic join D1 crash"):
        _admit(broker)
    assert _commands(_runtime(file))[0].state is BrokerCommandState.QUEUED
    assert broker._storage.connection.execute(
        "SELECT COUNT(*) FROM local_agent_browser_engine_original_join"
    ).fetchone()[0] == 0


def test_generic_rpc_and_process_admission_stay_process_only(tmp_path):
    _file, broker, _engine, _issued = _prepare(tmp_path)
    assert not hasattr(broker.facade(), "_admit_browser_control_command")
    from pathlib import Path
    worker = (Path(__file__).resolve().parents[1] / "local_agent_broker_worker.py").read_text(
        encoding="utf-8",
    )
    assert "pending_browser_engine_client" not in worker
    assert "_admit_pending_browser_command_from_original_engine_async" not in worker
    assert _commands(broker)[0].state is BrokerCommandState.QUEUED


def test_revoked_binding_while_engine_is_read_fails_at_final_broker_cas(tmp_path):
    file, broker, engine, _issued = _prepare(tmp_path)

    async def revoke_before_return(*, continuation_ref):
        assert continuation_ref == "cont_3782pendingbrowser"
        result = broker.revoke_binding({
            "binding_ref": "binding.atomic.1",
            "now": (CURRENT + timedelta(seconds=1)).isoformat(),
        })
        assert result["ok"] is True
        return _original()

    engine.read_browser_control_original_admission = revoke_before_return
    with pytest.raises((ValueError, ControlPlaneContractError)):
        _admit(broker)
    assert _commands(_runtime(file))[0].state is BrokerCommandState.QUEUED
    assert broker._storage.connection.execute(
        "SELECT COUNT(*) FROM local_agent_browser_engine_original_join"
    ).fetchone()[0] == 0


def test_one_human_approval_evidence_cannot_admit_a_second_broker_command(tmp_path):
    from dataclasses import replace

    from test_local_agent_broker_pending_browser_issue_3782 import (
        _VerifiedPendingTicketFixture,
    )

    _file, broker, engine, first = _prepare(tmp_path)
    second_source = _VerifiedPendingTicketFixture(
        replace(_setup_ticket_for_second(), ticket_ref="ticket.second.3782")
    )
    second_issuer = LocalAgentBrokerDurableRuntime(
        storage=broker._storage, env=_Env(),
        pending_browser_ticket_source=second_source,
        browser_admission_clock=lambda: CURRENT,
    )
    second = _issue(second_issuer, ticket_ref="ticket.second.3782")
    assert first["command_ref"] != second["command_ref"]
    assert _admit(broker)["admitted"] is True
    with pytest.raises(ControlPlaneContractError, match="evidence_ref has already been used"):
        asyncio.run(broker._admit_pending_browser_command_from_original_engine_async(
            command_ref=second["command_ref"],
            binding_ref="binding.atomic.1", session_ref="session.atomic.1",
            credential=CREDENTIAL, now=CURRENT,
        ))
    states = {c.command_id: c.state for c in _commands(broker)}
    assert states[first["command_ref"]] is BrokerCommandState.ADMITTED
    assert states[second["command_ref"]] is BrokerCommandState.QUEUED
    assert engine.calls == 2
    assert broker._storage.connection.execute(
        "SELECT COUNT(*) FROM local_agent_browser_engine_original_join"
    ).fetchone()[0] == 1


def _setup_ticket_for_second():
    from test_local_agent_broker_pending_browser_issue_3782 import _ticket
    return _ticket()
