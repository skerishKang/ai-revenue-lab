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


def test_a_configured_name_travels_only_when_it_carries_a_tag():
    tagged = "PADIEM pd-4decc834"

    def provider():
        return [
            {"device_id": "pc@mesh+1", "connected": True, "agent_name": tagged},
            {"device_id": "pc@mesh+2", "connected": True, "agent_name": "DESKTOP-7Q41B2X"},
        ]

    seen = []
    executor = OracleMeshExecutor(
        chat_origin="https://chat.example.test", channel_secret=SECRET,
        read_port=_StubPort(), presence_provider=provider,
        transport=lambda path, payload: (seen.append(payload) or (200, {"ok": True, "dispatch": None})),
    )
    executor.run_once()
    rows = seen[0]["presence"]
    assert rows[0]["agent_name"] == tagged
    # The untagged row keeps its presence and loses its name.
    assert rows[1] == {"device_id": "pc@mesh+2", "connected": True}

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


# -- PR-4c: the enumeration offers tag-carrying nodes, and only once ---------

def test_only_a_name_with_exactly_one_tag_token_becomes_a_candidate():
    rows = _presence().pairing_candidates()
    assert [(row["device_id"], row["connected"]) for row in rows] == [("pc@mesh+1", True)]
    assert rows[0]["agent_name"] == "PADIEM pd-4decc834 beta-notebook"
    # pc@mesh+2 is connected but untagged, pc@mesh+3 has no name at all, and an
    # offline node is not a pairing candidate.
    assert "DESKTOP-7Q41B2X" not in str(rows)


def test_two_tags_or_a_lookalike_are_not_a_pairing():
    from kagent.local_agent_oracle_mesh_executor import _pairing_tag_of
    assert _pairing_tag_of("pd-4decc834") == "pd-4decc834"
    assert _pairing_tag_of("pd-4decc834 pd-00000000") is None
    assert _pairing_tag_of("xpd-4decc8345") is None
    assert _pairing_tag_of("pd-4decc83") is None
    assert _pairing_tag_of(None) is None


class _Tagged:
    def __init__(self, rows):
        self.rows = rows

    def __call__(self):
        return [dict(row) for row in self.rows]


def _beat(pairing_rows, configured_rows, *, accepted=True):
    seen = []

    def transport(path, payload):
        seen.append(payload)
        return (200, {"ok": True, "dispatch": None}) if accepted else (503, {"ok": False})

    executor = OracleMeshExecutor(
        chat_origin="https://chat.example.test", channel_secret=SECRET,
        read_port=_StubPort(), presence_provider=lambda: list(configured_rows),
        pairing_provider=_Tagged(pairing_rows), transport=transport,
    )
    executor.poll_once()
    return seen[0], executor


def test_tags_take_the_budget_first_and_untagged_names_are_never_sent():
    candidate = {"device_id": "pc@mesh+9", "connected": True,
                 "agent_name": "PADIEM pd-7a3f9c21"}
    plain = {"device_id": "pc@mesh+1", "connected": True}
    untagged = {"device_id": "pc@mesh+2", "connected": True,
                "agent_name": "DESKTOP-7Q41B2X"}
    duplicate = {"device_id": "pc@mesh+9", "connected": True}
    payload, _ = _beat([candidate], [plain, untagged, duplicate])
    rows = payload["presence"]
    # The tag leads the beat, presence fills the rest, and one node is never
    # reported twice just because two sources named it.
    assert [row["device_id"] for row in rows] == ["pc@mesh+9", "pc@mesh+1", "pc@mesh+2"]
    assert rows[0]["agent_name"] == "PADIEM pd-7a3f9c21"
    # The untagged name stays on this host: it is somebody's computer name, not
    # evidence, and the receipt it would feed is keyed by the id anyway.
    assert "DESKTOP-7Q41B2X" not in str(rows)


def test_seven_ordinary_beats_still_leave_room_for_the_tag_and_the_cap_holds():
    candidate = {"device_id": "pc@mesh+9", "connected": True,
                 "agent_name": "PADIEM pd-7a3f9c21"}
    ordinary = [{"device_id": f"pc@mesh+{index}", "connected": True} for index in range(1, 8)]
    payload, _ = _beat([candidate], ordinary)
    rows = payload["presence"]
    assert len(rows) == 8 and rows[0]["device_id"] == "pc@mesh+9"


def test_a_reported_tag_is_not_offered_again_and_a_lost_beat_is():
    candidate = {"device_id": "pc@mesh+9", "connected": True,
                 "agent_name": "PADIEM pd-7a3f9c21"}
    plain = {"device_id": "pc@mesh+1", "connected": True}
    payload, executor = _beat([candidate], [plain])
    assert payload["presence"][0]["device_id"] == "pc@mesh+9"
    assert executor._reported_pairing_tags == {"pd-7a3f9c21"}

    second_call = []
    executor._transport = lambda path, payload: (
        second_call.append(payload) or (200, {"ok": True, "dispatch": None}))
    executor.poll_once()
    # Same tag, same process: the pairing already reached the server, so the
    # second beat carries only ordinary presence.
    assert [row["device_id"] for row in second_call[0]["presence"]] == ["pc@mesh+1"]


def test_a_refused_poll_leaves_the_tag_unreported_so_a_later_poll_can_carry_it():
    candidate = {"device_id": "pc@mesh+9", "connected": True,
                 "agent_name": "PADIEM pd-7a3f9c21"}
    plain = {"device_id": "pc@mesh+1", "connected": True}

    def transport(path, payload):
        return 503, {"ok": False}

    executor = OracleMeshExecutor(
        chat_origin="https://chat.example.test", channel_secret=SECRET,
        read_port=_StubPort(), presence_provider=lambda: [plain],
        pairing_provider=_Tagged([candidate]), transport=transport,
    )
    with pytest.raises(Exception):
        executor.poll_once()
    # Nothing was acknowledged, so nothing is remembered as reported.
    assert executor._reported_pairing_tags == set()
