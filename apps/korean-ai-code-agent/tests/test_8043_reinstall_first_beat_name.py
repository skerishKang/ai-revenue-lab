"""#8043: the first presence beat after a reinstall carries the NEW tag.

Before this fix the pairing half of the beat dropped a tagged node whose
MeshCentral ``conn`` flag was still 0. A freshly restarted agent stamps its new
tag into its name immediately, but the node can read conn=0 for a short window;
dropping it left only the OLD, still-connected tags on the first beat, and the
next beat could be an hour away — far past the code's ten-minute TTL. The tag is
the claim proof and liveness is re-derived by the server, so it must ride now.
"""
from __future__ import annotations

import re
from unittest.mock import patch

import kagent.local_agent_mesh_failover as failover
import kagent.local_agent_oracle_mesh_executor as entry
import pytest
from kagent.local_agent_oracle_mesh_executor import OracleMeshExecutor

SECRET = "s" * 32
OLD_TAG = "pd-9e8f7a6b"
NEW_TAG = "pd-1a2b3c4d"


class _Table:
    """A presence object with the one-table ``listing()`` the beat reads."""

    def __init__(self, rows):
        self._rows = rows

    def listing(self):
        return list(self._rows)


class _Stop(Exception):
    pass


def _captured_pairing_provider(rows):
    captured = {}

    def factory(**kwargs):
        captured["pairing"] = kwargs["pairing_provider"]
        raise _Stop()

    env = {
        "MESH_FAILOVER_DEVICE_ID": "node-old, node-new",
        "ORACLE_MESH_PASSWORD_FILE": "fake",
        "ORACLE_MESH_CHANNEL_SECRET_FILE": "fake",
        "ORACLE_MESH_MESHCTRL_JS": "fake",
        "ORACLE_MESH_LOGIN_USER": "synthetic",
        "ORACLE_MESH_CHAT_ORIGIN": "https://chat.example.test",
    }
    with patch.object(entry, "deployment_secret_password_provider",
                      return_value=lambda: "fake"), \
         patch.object(entry, "_read_secret_file", return_value=SECRET), \
         patch.object(entry, "make_oracle_mesh_executor", side_effect=factory), \
         patch.object(failover, "MeshCentralDevicePresence", lambda **kw: _Table(rows)), \
         pytest.raises(_Stop):
        entry.main(env)
    return captured["pairing"]


def _rows(*, new_connected):
    return [
        {"id": "node-old", "name": f"PADIEM {OLD_TAG} OLDPC", "conn": 1},
        {"id": "node-new", "name": f"PADIEM {NEW_TAG} NEWPC", "conn": 1 if new_connected else 0},
    ]


def test_first_beat_after_reinstall_carries_new_tag_even_before_conn_flips():
    pairing = _captured_pairing_provider(_rows(new_connected=False))
    beat = pairing()
    by_id = {row["device_id"]: row for row in beat}
    # The new node's name — with the NEW tag — is on the very first beat, even
    # though MeshCentral still reports it as not connected.
    assert by_id["node-new"]["agent_name"] == f"PADIEM {NEW_TAG} NEWPC"
    assert by_id["node-new"]["connected"] is False
    assert by_id["node-old"]["connected"] is True


def test_tag_is_still_carried_once_conn_has_flipped():
    pairing = _captured_pairing_provider(_rows(new_connected=True))
    beat = pairing()
    by_id = {row["device_id"]: row for row in beat}
    assert by_id["node-new"]["agent_name"] == f"PADIEM {NEW_TAG} NEWPC"
    assert by_id["node-new"]["connected"] is True


def test_beat_measurement_line_carries_only_time_and_node_count(capsys):
    class _Port:
        def read_bytes(self, **kwargs):
            raise AssertionError("not used")

    seen = []
    executor = OracleMeshExecutor(
        chat_origin="https://chat.example.test", channel_secret=SECRET,
        read_port=_Port(),
        presence_provider=lambda: [{"device_id": "node-old", "connected": True}],
        pairing_provider=lambda: [
            {"device_id": "node-new", "connected": False,
             "agent_name": f"PADIEM {NEW_TAG} NEWPC"},
        ],
        transport=lambda path, payload: (seen.append(payload) or (200, {"ok": True, "dispatch": None})),
    )
    executor.poll_once()
    lines = capsys.readouterr().out.splitlines()
    beat_lines = [line for line in lines if "presence_beat" in line]
    assert len(beat_lines) == 1
    assert re.fullmatch(
        r"oracle-mesh-executor presence_beat at=\S+ nodes=2", beat_lines[0]
    ), beat_lines[0]
    # No value the beat carries — no tag, node id or name — is printed.
    assert OLD_TAG not in beat_lines[0] and NEW_TAG not in beat_lines[0]
    assert "node-old" not in beat_lines[0] and "node-new" not in beat_lines[0]
