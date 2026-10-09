"""#3782 Windows Resident existing-stdio, private one-shot browser command take.

No product HUMAN P01 source, live Browser action, IPC listener or new thread.
Fixtures are synthetic and cannot grant production browser permissions.
"""
from __future__ import annotations

import json

import pytest
from kagent.contracts import ContractError
from kagent.local_agent_desktop_material import (
    COMMAND_TAKE_CONTRACT_VERSION,
    COMMAND_TAKE_REQUEST_KIND,
    COMMAND_TAKE_RESPONSE_EVENT,
    MAX_COMMAND_TAKE_RESPONSE_LINE_CHARS,
    ResidentDesktopMaterialResponder,
    parse_desktop_request,
)

COMMAND_REF = "command.3782.stdio"
PRIVATE_TEXT = "Do not retain secret user text in captured host logs"
MATERIAL = {
    "commandRef": COMMAND_REF,
    "hostLeaseRef": "hostlease.3782",
    "capability": "browser.control",
    "context": {
        "requestFingerprint": "a" * 64,
        "browserSessionRef": "browser.3782",
        "deviceRef": "device.3782",
        "runRef": "run.3782",
        "workspaceRef": "workspace.3782",
        "ownerRef": "owner.3782",
        "originScope": "https://example.org",
        "allowedActionClasses": ["type"],
        "ttlSeconds": 60,
        "maxActions": 1,
    },
    "action": {
        "action": "type",
        "browserSessionRef": "browser.3782",
        "originRef": "https://example.org",
        "elementRef": "el-0001",
        "text": PRIVATE_TEXT,
    },
}


def request(**overrides):
    value = {
        "contract_version": COMMAND_TAKE_CONTRACT_VERSION,
        "request": COMMAND_TAKE_REQUEST_KIND,
        "commandRef": COMMAND_REF,
    }
    value.update(overrides)
    return json.dumps(value, separators=(",", ":"))


def responder(owner=None):
    return ResidentDesktopMaterialResponder(
        material_projection=lambda: (_ for _ in ()).throw(AssertionError("no material fallback")),
        approved_command_take=owner,
    )


def test_no_live_broker_source_denies_without_action_material():
    result = json.loads(responder().respond(request()))
    assert result == {
        "event": COMMAND_TAKE_RESPONSE_EVENT,
        "contract_version": COMMAND_TAKE_CONTRACT_VERSION,
        "command_ref": COMMAND_REF,
        "ok": False,
        "reason": "command_take_unavailable",
        "command": None,
    }
    assert PRIVATE_TEXT not in json.dumps(result)


def test_authenticated_broker_port_only_receives_exact_bounded_ref_once():
    refs = []
    def owner(ref):
        refs.append(ref)
        if len(refs) != 1:
            raise ContractError("already consumed in Broker")
        return MATERIAL
    resident = responder(owner)
    first = json.loads(resident.respond(request()))
    assert first["ok"] is True
    assert first["command"] == MATERIAL
    assert refs == [COMMAND_REF]
    again = json.loads(resident.respond(request()))
    assert again["ok"] is False
    assert again["reason"] == "command_take_refused"
    assert again["command"] is None
    assert refs == [COMMAND_REF, COMMAND_REF]


@pytest.mark.parametrize("bad", [
    {"commandRef": ""},
    {"commandRef": "command 1"},
    {"commandRef": "a" * 257},
    {"contract_version": "wrong"},
    {"request": "execute_anything"},
    {"credentials": "must-not-pass"},
])
def test_bad_opaque_command_ref_or_extra_wire_cannot_hit_broker(bad):
    hits = []
    value = request(**bad)
    try:
        parse_desktop_request(value)
    except ContractError:
        pass
    else:
        pytest.fail("malformed command take was parsed")
    result = json.loads(responder(lambda ref: hits.append(ref)).respond(value))
    assert result["ok"] is False
    assert result.get("command") is None
    assert hits == []


@pytest.mark.parametrize("bad_material", [
    {"commandRef": "other.command"},
    {"capability": "browser.open"},
    {"credentials": "should-not-leak"},
])
def test_malformed_broker_material_refused_closed(bad_material):
    malformed = {**MATERIAL, **bad_material}
    result = json.loads(responder(lambda _: malformed).respond(request()))
    assert result["ok"] is False
    assert result["command"] is None
    assert PRIVATE_TEXT not in json.dumps(result)


def test_oversized_action_material_never_sent_to_desktop():
    material = {
        **MATERIAL,
        "action": {**MATERIAL["action"], "text": "S" * MAX_COMMAND_TAKE_RESPONSE_LINE_CHARS},
    }
    result = json.loads(responder(lambda _: material).respond(request()))
    assert result["ok"] is False and result["command"] is None


def test_no_new_stdio_listener_or_public_rpc_from_closed_take():
    result = parse_desktop_request(request())
    assert result == {"kind": COMMAND_TAKE_REQUEST_KIND, "payload": {"commandRef": COMMAND_REF}}
    assert len(request()) < 256



def test_actual_broker_durable_one_shot_take_crosses_resident_pipe_without_new_rpc():
    """Real Broker CAS with synthetic HUMAN-P01 fixture; NEVER production grant."""
    registration = pytest.importorskip("test_local_agent_broker_browser_registration_3782")
    authenticated = pytest.importorskip("test_local_agent_broker_browser_authenticated_take_3782")
    take_store = pytest.importorskip("test_local_agent_broker_browser_control_take_3782")

    storage, broker, scope, approved_material = registration.empty_fixture()
    registered = registration.register(broker, scope, approved_material)
    assert registered["stored"] is True

    def broker_owned_take(ref):
        if ref != scope.command_ref:
            raise ContractError("command ref not admitted by Broker")
        return broker._take_authenticated_browser_control_command(
            scope=scope, credential=authenticated.DEVICE_CREDENTIAL, now=authenticated.NOW,
        )

    resident = responder(broker_owned_take)
    first = json.loads(resident.respond(request(commandRef=scope.command_ref)))
    assert first["ok"] is True
    assert first["command"] == approved_material
    assert take_store.taken_count(storage) == 1
    second = json.loads(resident.respond(request(commandRef=scope.command_ref)))
    assert second["ok"] is False and second["command"] is None
    assert take_store.taken_count(storage) == 1
