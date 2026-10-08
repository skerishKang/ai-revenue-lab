"""#3782 canonical Broker pending browser command + original ticket atomicity.

Authenticating the ticket is test-only: the real first-party signed-in B54
owner-ticket/Engine ACTIVE P01 producer is NOT installed in any product Worker.
A QUEUED browser command does not grant any browser action or local authority.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from local_agent_broker_browser_control_take import BrowserControlCommandTakeCorrelation
from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime
from local_agent_broker_pending_browser_issue import (
    PENDING_BROWSER_TICKET_PRODUCT_ISSUER_WIRED,
    AuthenticatedPendingBrowserWorkTicket,
)
from padiem_control_plane.local_agent_broker import (
    BrokerCommandCapability,
    BrokerCommandState,
)
from test_local_agent_broker_enqueue_material_atomicity import (
    BASE,
    CREDENTIAL,
    _Env,
    _register_and_open,
    _runtime,
)

CURRENT = BASE + timedelta(seconds=6)


class _VerifiedPendingTicketFixture:
    """Never product authentication; only exercises the trusted-source port."""

    def __init__(self, ticket):
        self.ticket = ticket
        self.calls = 0

    async def resolve_active_pending_browser_ticket_async(self, *, ticket_ref, now):
        self.calls += 1
        await asyncio.sleep(0)
        return self.ticket


def _ticket(**kwargs):
    values = {
        "ticket_ref": "ticket.pending.3782",
        "binding_ref": "binding.atomic.1",
        "workspace_ref": "workspace.atomic.1",
        "device_ref": "device.atomic.1",
        "owner_ref": "user.owner.3782",
        "broker_run_ref": "run.pending.browser.3782",
        "tool_request_ref": "tool.browser.3782",
        "browser_request_fingerprint": "a" * 64,
        "engine_app_id": "padiem.browser.test",
        "engine_continuation_ref": "cont_3782pendingbrowser",
        "engine_run_ref": "engine.run.3782",
        "original_request_fingerprint": "b" * 64,
        "original_admission_decision_id": "engine.admit.3782",
        "browser_invocation_sha256": "c" * 64,
        "expires_at": CURRENT + timedelta(minutes=5),
    }
    values.update(kwargs)
    return AuthenticatedPendingBrowserWorkTicket(**values)


def _setup(tmp_path: Path, *, ticket=None):
    storage_file = tmp_path / "pending-browser.sqlite3"
    initial = _runtime(storage_file)
    _register_and_open(initial)
    source = _VerifiedPendingTicketFixture(ticket if ticket is not None else _ticket())
    broker = LocalAgentBrokerDurableRuntime(
        storage=initial._storage, env=_Env(), pending_browser_ticket_source=source,
    )
    return storage_file, broker, source


def _issue(broker, ticket_ref="ticket.pending.3782"):
    return asyncio.run(broker._issue_pending_browser_command_from_current_ticket_async(
        ticket_ref=ticket_ref, now=CURRENT,
    ))


def _rows(broker):
    return broker._storage.connection.execute(
        "SELECT ticket_ref,command_ref,binding_ref,revision_ref,retired_at "
        "FROM local_agent_browser_pending_owner_ticket"
    ).fetchall()


def _commands(broker):
    return broker.state_port.load(authority_ref=broker.authority_ref()).snapshot.commands


def test_pending_owner_ticket_mints_distinct_canonical_browser_command_atomically(tmp_path):
    storage_file, broker, source = _setup(tmp_path)
    assert PENDING_BROWSER_TICKET_PRODUCT_ISSUER_WIRED is False
    issued = _issue(broker)
    assert issued["issued"] is True
    assert issued["capability"] == "browser.control"
    assert issued["command_admitted"] is False
    assert issued["approval_recorded"] is False
    assert issued["browser_action_executed"] is False
    assert issued["command_ref"].startswith("browser.cmd.")
    assert issued["binding_ref"] == source.ticket.binding_ref
    assert source.calls == 1
    (command,) = _commands(broker)
    assert command.command_id == issued["command_ref"]
    assert command.capability is BrokerCommandCapability.BROWSER_CONTROL
    assert command.state is BrokerCommandState.QUEUED
    assert command.request_fingerprint == source.ticket.browser_request_fingerprint
    assert command.revision_ref == issued["revision_ref"]
    assert len(_rows(broker)) == 1
    assert _rows(broker)[0][1:4] == (
        command.command_id, command.binding_ref, command.revision_ref,
    )
    # Generic process poll does not dispatch browser.control.
    poll = broker.poll({
        "session_id": "session.atomic.1",
        "binding_ref": "binding.atomic.1",
        "credential_b64": _encoded_credential(),
        "after_sequence": 0,
        "limit": 32,
        "now": (CURRENT + timedelta(seconds=1)).isoformat(),
    })
    assert poll["ok"] is True and poll["commands"] == []
    restarted = _runtime(storage_file)
    assert restarted._pending_browser_ticket_source is None
    (from_disk,) = _commands(restarted)
    assert from_disk == command
    assert _rows(restarted) == _rows(broker)
    with pytest.raises(ValueError, match="not wired"):
        _issue(restarted)


def _encoded_credential():
    import base64

    from test_local_agent_broker_enqueue_material_atomicity import CREDENTIAL

    return base64.b64encode(CREDENTIAL).decode("ascii")


def test_pending_ticket_cannot_be_minted_twice_or_reused_after_restart(tmp_path):
    storage_file, broker, source = _setup(tmp_path)
    first = _issue(broker)
    with pytest.raises(ValueError, match="already issued"):
        _issue(broker)
    assert source.calls == 2
    assert len(_commands(broker)) == 1
    restarted = _runtime(storage_file)
    again = LocalAgentBrokerDurableRuntime(
        storage=restarted._storage, env=_Env(), pending_browser_ticket_source=source,
    )
    with pytest.raises(ValueError, match="already issued"):
        _issue(again)
    assert _commands(again)[0].command_id == first["command_ref"]
    assert len(_rows(again)) == 1
    assert again.browser_pending_ticket_store.retire_command(
        first["command_ref"], now=CURRENT,
    ) == 1
    assert again.browser_pending_ticket_store.retire_command(
        first["command_ref"], now=CURRENT,
    ) == 0
    with pytest.raises(ValueError, match="already issued"):
        _issue(again)
    assert len(_commands(again)) == 1


@pytest.mark.parametrize("changed", [
    {"binding_ref": "binding.other"},
    {"workspace_ref": "workspace.other"},
    {"device_ref": "device.other"},
    {"expires_at": CURRENT - timedelta(seconds=1)},
    {"expires_at": CURRENT + timedelta(milliseconds=500)},
])
def test_wrong_or_expired_ticket_cannot_mint_command(tmp_path, changed):
    storage_file, broker, _ = _setup(tmp_path, ticket=_ticket(**changed))
    with pytest.raises(ValueError):
        _issue(broker)
    assert _commands(broker) == ()
    assert _rows(broker) == []
    assert _runtime(storage_file).state_port.load(
        authority_ref=broker.authority_ref()
    ).snapshot.commands == ()


def test_mismatched_requested_ticket_ref_fails_before_any_mutation(tmp_path):
    _file, broker, source = _setup(tmp_path)
    with pytest.raises(ValueError, match="not current or not requested"):
        _issue(broker, ticket_ref="ticket.another")
    assert source.calls == 1 and _commands(broker) == () and _rows(broker) == []


def test_unconfigured_or_nonasync_source_never_mints(tmp_path):
    path, broker, source = _setup(tmp_path)
    without_source = _runtime(path)
    with pytest.raises(ValueError, match="not wired"):
        _issue(without_source)
    source.resolve_active_pending_browser_ticket_async = lambda **_: source.ticket
    with pytest.raises(ValueError, match="requires authenticated async"):
        _issue(broker)
    assert _rows(broker) == [] and _commands(broker) == ()


def test_sql_failure_after_canonical_enqueue_rolls_back_both_and_used_id_ledger(tmp_path):
    _, broker, _ = _setup(tmp_path)
    def crash_after_command_mint(**_kwargs):
        raise RuntimeError("synthetic D1 failure after canonical Broker mint")
    broker.browser_pending_ticket_store._register_in_existing_transaction = crash_after_command_mint
    with pytest.raises(RuntimeError, match="synthetic D1 failure"):
        _issue(broker)
    assert _commands(broker) == ()
    assert _rows(broker) == []
    assert broker._storage.connection.execute(
        "SELECT count(*) FROM local_agent_broker_used_command_id"
    ).fetchone()[0] == 0


def test_pending_original_ticket_remains_nonapproval_even_when_association_can_be_read(tmp_path):
    _, broker, source = _setup(tmp_path)
    issued = _issue(broker)
    scope = BrowserControlCommandTakeCorrelation(
        command_ref=issued["command_ref"],
        session_ref="session.atomic.1",
        binding_ref="binding.atomic.1",
        request_id="request.pending.3782",
        run_ref=source.ticket.broker_run_ref,
        workspace_ref=source.ticket.workspace_ref,
        owner_ref=source.ticket.owner_ref,
        device_ref=source.ticket.device_ref,
        request_fingerprint=source.ticket.browser_request_fingerprint,
        admission_ref="admission.not-yet-issued",
        revision_ref=issued["revision_ref"],
    )
    association = broker.browser_pending_ticket_store.resolve_for_admitted_command(
        scope=scope, now=CURRENT,
    )
    assert association.command_ref == issued["command_ref"]
    assert association.engine_app_id == source.ticket.engine_app_id
    assert association.engine_continuation_ref == source.ticket.engine_continuation_ref
    # Merely presenting a typed scope does not change canonical command state.
    assert _commands(broker)[0].state is BrokerCommandState.QUEUED
    with pytest.raises(ValueError, match="live admitted command"):
        broker._require_live_admitted_browser_command(
            scope=scope, credential=CREDENTIAL, now=CURRENT,
        )
    wrong = replace(scope, owner_ref="other.owner")
    with pytest.raises(ValueError, match="scope changed"):
        broker.browser_pending_ticket_store.resolve_for_admitted_command(
            scope=wrong, now=CURRENT,
        )
    assert broker.browser_pending_ticket_store.retire_binding(
        "binding.atomic.1", now=CURRENT,
    ) == 1
    with pytest.raises(ValueError, match="revoked"):
        broker.browser_pending_ticket_store.resolve_for_admitted_command(
            scope=scope, now=CURRENT,
        )


def test_issuer_not_exposed_on_worker_or_generic_rpc():
    import inspect
    from pathlib import Path

    from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
    from padiem_control_plane.local_agent_broker_state import (
        StateBackedLocalAgentBrokerAuthority,
    )

    assert not hasattr(LocalAgentBrokerRpcFacade, "_enqueue_browser_control_command")
    assert not hasattr(LocalAgentBrokerRpcFacade, "_issue_pending_browser_command_from_current_ticket_async")
    assert not hasattr(StateBackedLocalAgentBrokerAuthority, "enqueue_browser_control_command")
    code = (Path(__file__).resolve().parents[1] / "local_agent_broker_worker.py").read_text(
        encoding="utf-8",
    )
    assert "pending_browser_ticket_source" not in code
    assert "_issue_pending_browser_command_from_current_ticket_async" not in code
    assert "browser_pending_ticket_store" not in code
    assert "capability" not in inspect.signature(
        LocalAgentBrokerRpcFacade.enqueue_command
    ).parameters


def test_public_process_admission_refuses_pending_browser_command(tmp_path):
    from test_local_agent_broker_enqueue_material_atomicity import _admit_payload

    _, broker, _source = _setup(tmp_path)
    issued = _issue(broker)
    (command,) = _commands(broker)
    assert issued["command_ref"] == command.command_id
    requested = _admit_payload(
        command.safe_dict(), at=CURRENT + timedelta(seconds=1),
    )
    result = broker.facade().admit_command(requested)
    assert result.get("ok") is False
    assert "capability" in str(result).lower()
    assert _commands(broker)[0].state is BrokerCommandState.QUEUED
    assert len(_rows(broker)) == 1


def test_ticket_source_object_is_not_a_privilege_bypass(tmp_path):
    _path, broker, source = _setup(tmp_path)
    source.ticket = {"ticket_ref": "ticket.pending.3782", "approved": True}
    with pytest.raises(ValueError, match="independent authenticated"):
        _issue(broker)
    assert _commands(broker) == () and _rows(broker) == []
