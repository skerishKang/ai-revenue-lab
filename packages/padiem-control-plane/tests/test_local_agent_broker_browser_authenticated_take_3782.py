"""#3782 Windows-first: internal device-authenticated broker take, no public issuer.

Fixtures inject a canonical admitted browser command and matching SQLite row.
They do NOT model or mint production P01 approval decisions.
"""
from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import timedelta

import pytest
from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime
from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker import (
    BrokerCommandCapability,
    BrokerCommandRecord,
    BrokerCommandState,
)
from test_local_agent_broker_browser_control_take_3782 import (
    NOW,
    _Storage,
    correlation,
    payload,
    taken_count,
)

DEVICE_CREDENTIAL = b"device-browser-command-credential-3782"


class _Env:
    LOCAL_AGENT_BROKER_AUTHORITY_REF = "broker.browser-authenticated-take.3782"
    LOCAL_AGENT_BROKER_PEPPER = "browser-authenticated-take-2026-secure-pepper"


def _encoded(value):
    return base64.b64encode(value).decode("ascii")


def prepared(*, capability=BrokerCommandCapability.BROWSER_CONTROL, state=BrokerCommandState.ADMITTED):
    storage = _Storage()
    broker = LocalAgentBrokerDurableRuntime(storage=storage, env=_Env())
    scope = correlation()
    bound = broker.register_binding({
        "binding_ref": scope.binding_ref, "device_id": scope.device_ref,
        "account_ref": "account.3782.1", "workspace_ref": scope.workspace_ref,
        "credential_b64": _encoded(DEVICE_CREDENTIAL),
        "now": (NOW - timedelta(minutes=2)).isoformat(),
    })
    assert bound["ok"] is True
    sess = broker.open_session({
        "session_id": scope.session_ref, "binding_ref": scope.binding_ref,
        "credential_b64": _encoded(DEVICE_CREDENTIAL),
        "account_ref": "account.3782.1",
        "workspace_ref": scope.workspace_ref,
        "now": (NOW - timedelta(minutes=1)).isoformat(),
    })
    assert sess["ok"] is True
    snapshot_record = broker.state_port.load(authority_ref=broker.authority_ref())
    if state is BrokerCommandState.QUEUED:
        admissions = {}
    else:
        admissions = {
            "admission_ref": scope.admission_ref,
            "evidence_ref": "p01.evidence.test.3782",
            "admitted_session_id": scope.session_ref,
            "admitted_at": NOW - timedelta(seconds=15),
            "request_id": scope.request_id,
        }
    command = BrokerCommandRecord(
        command_id=scope.command_ref, run_id=scope.run_ref,
        tool_request_ref="tool.request.3782.1", binding_ref=scope.binding_ref,
        credential_generation=1, sequence=1,
        request_fingerprint=scope.request_fingerprint,
        issued_at=NOW - timedelta(seconds=30),
        expires_at=NOW + timedelta(seconds=120),
        revision_ref=scope.revision_ref,
        capability=capability, state=state, **admissions,
    )
    previous = snapshot_record.snapshot
    inserted = replace(
        previous, commands=(command,),
        last_sequence_by_binding=((scope.binding_ref, 1),),
    )
    broker.state_port.compare_and_swap(
        authority_ref=broker.authority_ref(),
        expected_version=snapshot_record.version,
        snapshot=inserted,
        new_command_ids=(scope.command_ref,),
    )
    # Only a fixture can insert the approved material. No product P01
    # issuer or registration endpoint is introduced here.
    wire = payload(scope)
    storage.sql.exec(
        "INSERT INTO local_agent_browser_control_command_take "
        "(command_ref,session_ref,binding_ref,request_id,run_ref,workspace_ref,"
        "owner_ref,device_ref,request_fingerprint,admission_ref,revision_ref,"
        "expires_at,material_text,taken_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
        scope.command_ref, scope.session_ref, scope.binding_ref,
        scope.request_id, scope.run_ref, scope.workspace_ref,
        scope.owner_ref, scope.device_ref, scope.request_fingerprint,
        scope.admission_ref, scope.revision_ref,
        (NOW + timedelta(seconds=100)).isoformat(),
        json.dumps(wire, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )
    return storage, broker, scope


def take(broker, scope, *, credential=DEVICE_CREDENTIAL, when=NOW):
    return broker._take_authenticated_browser_control_command(
        scope=scope, credential=credential, now=when
    )


def test_authentic_broker_take_is_one_shot_and_restart_refuses():
    storage, broker, scope = prepared()
    assert take(broker, scope) == payload(scope)
    assert taken_count(storage) == 1
    restarted = LocalAgentBrokerDurableRuntime(storage=storage, env=_Env())
    with pytest.raises(ValueError, match="already taken"):
        take(restarted, scope)
    assert taken_count(storage) == 1


def test_wrong_live_device_credential_does_not_consume():
    storage, broker, scope = prepared()
    with pytest.raises((ControlPlaneContractError, ValueError)):
        take(broker, scope, credential=b"wrong-credential-3782")
    assert taken_count(storage) == 0
    assert take(broker, scope) == payload(scope)


@pytest.mark.parametrize("key", [
    "session_ref", "binding_ref", "device_ref", "workspace_ref",
    "run_ref", "request_id", "request_fingerprint",
    "admission_ref", "revision_ref", "command_ref",
])
def test_broker_take_refuses_any_canonical_correlation_drift(key):
    storage, broker, scope = prepared()
    value = "b" * 64 if key == "request_fingerprint" else "unmatched.3782"
    with pytest.raises((ControlPlaneContractError, ValueError)):
        take(broker, replace(scope, **{key: value}))
    assert taken_count(storage) == 0
    assert take(broker, scope) == payload(scope)


@pytest.mark.parametrize("capability,state", [
    (BrokerCommandCapability.PROCESS_EXECUTE, BrokerCommandState.ADMITTED),
    (BrokerCommandCapability.BROWSER_CONTROL, BrokerCommandState.QUEUED),
])
def test_process_or_unadmitted_browser_command_cannot_take(capability, state):
    storage, broker, scope = prepared(capability=capability, state=state)
    with pytest.raises(ValueError, match="live admitted command"):
        take(broker, scope)
    assert taken_count(storage) == 0


@pytest.mark.parametrize("operation", ["rotate", "revoke"])
def test_live_binding_rotation_or_revoke_fails_closed(operation):
    storage, broker, scope = prepared()
    if operation == "rotate":
        result = broker.rotate_credential({
            "binding_ref": scope.binding_ref, "expected_generation": 1,
            "new_credential_b64": _encoded(b"replacement-credential-3782"),
            "now": (NOW - timedelta(seconds=1)).isoformat(),
        })
    else:
        result = broker.revoke_binding({
            "binding_ref": scope.binding_ref,
            "now": (NOW - timedelta(seconds=1)).isoformat(),
        })
    assert result["ok"] is True
    assert storage.connection.execute(
        "SELECT count(*) FROM local_agent_browser_control_command_take"
    ).fetchone()[0] == 0
    with pytest.raises((ControlPlaneContractError, ValueError)):
        take(broker, scope)


def test_expired_command_and_session_refuse_without_burning():
    storage, broker, scope = prepared()
    with pytest.raises((ControlPlaneContractError, ValueError)):
        take(broker, scope, when=NOW + timedelta(minutes=20))
    assert taken_count(storage) == 0


def test_private_method_does_not_expose_public_worker_rpc_or_product_source():
    storage, broker, _scope = prepared()
    assert not hasattr(broker, "register_browser_control_work_ticket")
    assert not hasattr(broker, "take_browser_control_rpc")
    assert not hasattr(broker, "enqueue_browser_control_rpc")
    assert taken_count(storage) == 0
