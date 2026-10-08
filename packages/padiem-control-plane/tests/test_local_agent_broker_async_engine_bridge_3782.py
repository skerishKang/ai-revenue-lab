"""#3782 exact independent Engine P01 -> Broker DO CAS (hermetic ports).

The Engine receipt is a test projection, NOT a real human approval. Only the
existing Engine-owned D1 read route can provide Production evidence.
No new Worker endpoint, browser input or product authority is activated.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, replace
from datetime import timedelta

import pytest
from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime
from local_agent_broker_engine_p01_bridge import (
    AsyncBrokerEngineBrowserP01Bridge,
    AuthenticatedAsyncEngineReceiptClientPort,
)
from test_local_agent_broker_browser_authenticated_take_3782 import (
    DEVICE_CREDENTIAL,
    NOW,
    _Env,
)
from test_local_agent_broker_browser_control_take_3782 import taken_count
from test_local_agent_broker_browser_registration_3782 import registered_rows
from test_local_agent_broker_engine_p01_bridge_3782 import _harness


class _FakeAuthenticatedEngineClient:
    """Deliberately synthetic, does not establish a real Engine identity."""

    def __init__(self, join, projection):
        self.app_id = join.engine_app_id
        self.join = join
        self.projection = projection
        self.fail = False
        self.calls = []

    async def read_browser_control_broker_receipt(self, **kwargs):
        self.calls.append(kwargs)
        await asyncio.sleep(0)
        if self.fail:
            raise ValueError("Engine P01 receipt revoked")
        assert kwargs == {
            "continuation_ref": self.join.engine_continuation_ref,
            "user_subject_id": self.join.engine_user_subject_id,
            "original_request_fingerprint": self.join.engine_request_sha256,
            "original_admission_decision_id": self.join.engine_original_admission_decision_id,
            "run_id": self.join.engine_run_id,
            "invocation_sha256": self.join.browser_invocation_sha256,
            "user_approval_evidence_ref": self.join.user_p01_evidence_ref,
        }
        p = asdict(self.projection)
        p["approved_at"] = p["approved_at"].isoformat()
        p["expires_at"] = p["expires_at"].isoformat()
        return p


def _system():
    storage, _old_broker, scope, material, join, projection_port, local = _harness()
    client = _FakeAuthenticatedEngineClient(join.result, projection_port.projection)
    adapter = AuthenticatedAsyncEngineReceiptClientPort(engine_client=client)
    bridge = AsyncBrokerEngineBrowserP01Bridge(
        join_port=join, engine_port=adapter, local_port=local,
    )
    broker = LocalAgentBrokerDurableRuntime(
        storage=storage, env=_Env(), p01_approval_source=bridge,
    )
    return storage, broker, scope, material, join, local, client


def _bind(broker, scope, material):
    return asyncio.run(broker._bind_browser_material_to_admitted_command_async(
        scope=scope, credential=DEVICE_CREDENTIAL, material=material, now=NOW,
    ))


def _take(broker, scope):
    return asyncio.run(broker._take_authenticated_browser_control_command_async(
        scope=scope, credential=DEVICE_CREDENTIAL, now=NOW,
    ))


def test_three_original_authorities_async_register_restart_take_once():
    storage, broker, scope, material, join, local, client = _system()
    assert join.result.broker_request_fingerprint != join.result.engine_request_sha256
    assert join.result.engine_run_id != scope.run_ref
    assert _bind(broker, scope, material)["stored"] is True
    assert registered_rows(storage) == 1
    assert join.calls == len(client.calls) == local.calls == 1
    restarted = LocalAgentBrokerDurableRuntime(
        storage=storage, env=_Env(), p01_approval_source=broker._p01_approval_source,
    )
    assert _take(restarted, scope) == material
    assert taken_count(storage) == 1
    assert join.calls == len(client.calls) == local.calls == 2
    with pytest.raises(ValueError, match="already taken"):
        _take(broker, scope)
    assert taken_count(storage) == 1


def test_engine_revocation_after_registration_blocks_desktop_take():
    storage, broker, scope, material, _join, _local, client = _system()
    _bind(broker, scope, material)
    client.fail = True
    with pytest.raises(ValueError, match="revoked"):
        _take(broker, scope)
    assert taken_count(storage) == 0
    assert registered_rows(storage) == 1


@pytest.mark.parametrize("mutation", [
    "wrong_owner", "wrong_original_sha", "wrong_engine_evidence",
    "wrong_engine_run", "expired_receipt", "local_denied", "missing_client",
])
def test_any_authority_mismatch_refuses_before_broker_command_registration(mutation):
    storage, broker, scope, material, join, local, client = _system()
    if mutation == "wrong_owner":
        join.result = replace(join.result, engine_user_subject_id="other.owner")
    elif mutation == "wrong_original_sha":
        join.result = replace(join.result, engine_request_sha256="f" * 64)
    elif mutation == "wrong_engine_evidence":
        client.projection = replace(client.projection, evidence_ref="other.evidence")
    elif mutation == "wrong_engine_run":
        client.projection = replace(client.projection, run_id="other.run")
    elif mutation == "expired_receipt":
        client.projection = replace(client.projection, expires_at=NOW - timedelta(seconds=1))
    elif mutation == "local_denied":
        local.result = replace(local.result, result="denied")
    elif mutation == "missing_client":
        broker._p01_approval_source = None
    with pytest.raises((ValueError, AssertionError)):
        _bind(broker, scope, material)
    assert registered_rows(storage) == 0
    assert taken_count(storage) == 0


def test_client_port_never_accepts_sync_fake_or_foreign_app():
    storage, broker, scope, material, join, _local, client = _system()
    client.app_id = "foreign.engine.app"
    with pytest.raises(ValueError, match="does not own"):
        _bind(broker, scope, material)
    assert client.calls == []
    assert registered_rows(storage) == 0
    client.app_id = join.result.engine_app_id
    client.read_browser_control_broker_receipt = lambda **_: {
        "app_id": client.app_id,
    }
    with pytest.raises(ValueError, match="asynchronous"):
        _bind(broker, scope, material)
    assert registered_rows(storage) == 0


def test_windows_resident_private_stdio_consumes_broker_async_engine_command_once():
    """Real DO CAS -> bounded Resident stdio, synthetic Engine receipt only."""
    kagent = pytest.importorskip("kagent.local_agent_desktop_material")
    storage, broker, scope, material, join, local, client = _system()
    _bind(broker, scope, material)

    def broker_port(command_ref):
        if command_ref != scope.command_ref:
            raise ValueError("command not admitted by Broker")
        # Test-only synchronous harness around the async Broker authority.
        # No Worker/DO transport uses asyncio.run; real service binding is async.
        return _take(broker, scope)

    def no_fallback():
        raise AssertionError("Resident must never expose unapproved action material")

    resident = kagent.ResidentDesktopMaterialResponder(
        material_projection=no_fallback,
        approved_command_take=broker_port,
    )
    request = json.dumps({
        "contract_version": kagent.COMMAND_TAKE_CONTRACT_VERSION,
        "request": kagent.COMMAND_TAKE_REQUEST_KIND,
        "commandRef": scope.command_ref,
    })
    first = json.loads(resident.respond(request))
    assert first["event"] == kagent.COMMAND_TAKE_RESPONSE_EVENT
    assert first["ok"] is True
    assert first["command"] == material
    assert taken_count(storage) == 1
    assert len(client.calls) == 2  # once for registration, once for take
    again = json.loads(resident.respond(request))
    assert again["ok"] is False
    assert again["command"] is None
    assert taken_count(storage) == 1
    assert join.calls == local.calls == 2
