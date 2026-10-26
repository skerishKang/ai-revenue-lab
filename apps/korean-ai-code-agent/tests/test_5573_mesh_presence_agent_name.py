"""#5573 PR-4a: the executor reports the agent NAME it already sees.

The PC cannot name its own MeshCentral node identity, but the executor host can
read both the id and the name from `meshctrl listdevices`. The pairing tag the
installer stamps into that name is therefore the one thing that lets the server
finish a claim it was handed a code for. The name is carried, never kept.
"""
from __future__ import annotations
from unittest.mock import patch

import pytest

from kagent.local_agent_mesh_failover import (
    MeshCentralDevicePresence,
)
from kagent.local_agent_oracle_mesh_executor import (
    ContractError,
    OracleMeshExecutor,
)

SECRET = "s" * 32
LISTDEVICES = """Device group: default
id, name, icon, conn, pwr
--------------------
"pc@mesh+1", "PADIEM pd-4decc834 beta-notebook", 1, 1, 1
"pc@mesh+2", "DESKTOP-7Q41B2X", 1, 0, 0
"pc@mesh+3", , 1, 1, 1
"""


class _StubPort:
    def read_bytes(self, **kwargs):
        raise AssertionError("not used")


def _presence(text=LISTDEVICES):
    presence = MeshCentralDevicePresence.__new__(MeshCentralDevicePresence)
    presence._run_listdevices = lambda: text  # type: ignore[assignment]
    return presence


def test_name_of_reads_the_name_meshctrl_prints_and_nothing_else():
    presence = _presence()
    assert presence.name_of("pc@mesh+1") == "PADIEM pd-4decc834 beta-notebook"
    assert presence.name_of("pc@mesh+2") == "DESKTOP-7Q41B2X"
    # An unprintable row and an unknown device yield no name rather than a guess.
    assert presence.name_of("pc@mesh+3") is None
    assert presence.name_of("pc@mesh+9") is None
    with pytest.raises(ContractError):
        presence.name_of(" ")


class _Presence:
    def __init__(self, **kwargs):
        pass

    def is_connected(self, device):
        return device.endswith("1")

    def name_of(self, device):
        return "PADIEM pd-4decc834 beta-notebook" if device.endswith("1") else None


class _LegacyPresence:
    """A presence object from before the name was read: still works."""

    def __init__(self, **kwargs):
        pass

    def is_connected(self, device):
        return True


def _beats(presence_class, configured="pc@mesh+1, pc@mesh+2"):
    import kagent.local_agent_oracle_mesh_executor as entry
    import kagent.local_agent_mesh_failover as failover

    class Stop(Exception):
        pass

    captured = {}

    def factory(**kwargs):
        captured["provider"] = kwargs["presence_provider"]
        raise Stop()

    env = {
        "MESH_FAILOVER_DEVICE_ID": configured, "ORACLE_MESH_PASSWORD_FILE": "fake",
        "ORACLE_MESH_CHANNEL_SECRET_FILE": "fake", "ORACLE_MESH_MESHCTRL_JS": "fake",
        "ORACLE_MESH_LOGIN_USER": "synthetic",
        "ORACLE_MESH_CHAT_ORIGIN": "https://chat.example.test",
    }
    with patch.object(entry, "deployment_secret_password_provider",
                      return_value=lambda: "fake"), \
         patch.object(entry, "_read_secret_file", return_value=SECRET), \
         patch.object(entry, "make_oracle_mesh_executor", side_effect=factory), \
         patch.object(failover, "MeshCentralDevicePresence", presence_class):
        with pytest.raises(Stop):
            entry.main(env)

    seen = []
    executor = OracleMeshExecutor(
        chat_origin="https://chat.example.test", channel_secret=SECRET,
        read_port=_StubPort(), presence_provider=captured["provider"],
        transport=lambda path, payload: (seen.append(payload) or (200, {"ok": True, "dispatch": None})),
    )
    executor.run_once()
    return seen[0]


def test_the_poll_carries_the_agent_name_only_where_it_has_one():
    beat = _beats(_Presence)
    assert beat == {"presence": [
        {"device_id": "pc@mesh+1", "connected": True,
         "agent_name": "PADIEM pd-4decc834 beta-notebook"},
        {"device_id": "pc@mesh+2", "connected": False},
    ]}


def test_a_presence_without_name_support_keeps_the_old_envelope():
    assert _beats(_LegacyPresence) == {"presence": [
        {"device_id": "pc@mesh+1", "connected": True},
        {"device_id": "pc@mesh+2", "connected": True},
    ]}


def test_the_beat_accepts_the_new_key_and_still_refuses_a_malformed_one():
    def provider():
        return [{"device_id": "pc@mesh+1", "connected": True, "agent_name": "ok name"}]

    seen = []
    executor = OracleMeshExecutor(
        chat_origin="https://chat.example.test", channel_secret=SECRET,
        read_port=_StubPort(), presence_provider=provider,
        transport=lambda path, payload: (seen.append(payload) or (200, {"ok": True, "dispatch": None})),
    )
    executor.run_once()
    assert seen[0]["presence"][0]["agent_name"] == "ok name"

    def broken():
        return [{"device_id": "pc@mesh+1", "connected": True, "agent_name": "bad\tname"}]

    refused = []
    executor = OracleMeshExecutor(
        chat_origin="https://chat.example.test", channel_secret=SECRET,
        read_port=_StubPort(), presence_provider=broken,
        transport=lambda path, payload: (refused.append(payload) or (200, {"ok": True, "dispatch": None})),
    )
    executor.run_once()
    # A beat this host cannot vouch for is dropped whole rather than sent partly
    # formed, and the poll itself still goes out: presence is evidence, never the
    # reason the queue stalls.
    assert len(refused) == 1
    assert "agent_name" not in str(refused[0])
