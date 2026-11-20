"""#8150: one odd device name must not silence the whole presence beat."""
from __future__ import annotations

from kagent.local_agent_oracle_mesh_executor import OracleMeshExecutor

SECRET = "s" * 32
TAG = "pd-7a3f9c21"


class _StubPort:
    def read_bytes(self, *, node_ref, file_path, timeout_seconds=60, max_bytes=None):
        raise AssertionError("not used")


def _beat(rows, *, pairing=(), now=1000.0):
    seen = []

    def transport(path, payload):
        seen.append(payload)
        return 200, {"ok": True, "dispatch": None}

    executor = OracleMeshExecutor(
        chat_origin="https://chat.example.test",
        channel_secret=SECRET,
        read_port=_StubPort(),
        presence_provider=lambda: rows,
        pairing_provider=lambda: pairing,
        transport=transport,
        share_clock=lambda: now,
    )
    executor.run_once()
    return seen[0], executor


def test_a_korean_name_among_three_plain_nodes_keeps_all_four_presence_entries():
    rows = [
        {"device_id": "pc@mesh+1", "connected": True},
        {"device_id": "pc@mesh+2", "connected": True, "agent_name": "파디엠써피스"},
        {"device_id": "pc@mesh+3", "connected": False},
        {"device_id": "pc@mesh+4", "connected": True},
    ]
    beat, _ = _beat(rows, now=1000.0)
    assert beat is not None
    assert [e["device_id"] for e in beat["presence"]] == [
        "pc@mesh+1", "pc@mesh+2", "pc@mesh+3", "pc@mesh+4",
    ]
    # A name without a tag is private text and never travels.
    assert all("agent_name" not in e for e in beat["presence"])


def test_a_malformed_node_is_skipped_without_dropping_the_other_three():
    rows = [
        {"device_id": "pc@mesh+1", "connected": True},
        {"device_id": "", "connected": True},
        {"device_id": "pc@mesh+3", "connected": False},
        {"device_id": "pc@mesh+4", "connected": True},
    ]
    beat, _ = _beat(rows, now=2000.0)
    assert beat is not None
    assert [e["device_id"] for e in beat["presence"]] == [
        "pc@mesh+1", "pc@mesh+3", "pc@mesh+4",
    ]


def test_a_hostname_after_a_name_sync_still_reports_presence():
    rows = [
        {"device_id": "pc@mesh+1", "connected": True, "agent_name": "DESKTOP-7Q41B2X"},
        {"device_id": "pc@mesh+2", "connected": True},
    ]
    beat, _ = _beat(rows, now=3000.0)
    assert [e["device_id"] for e in beat["presence"]] == ["pc@mesh+1", "pc@mesh+2"]
    assert "agent_name" not in beat["presence"][0]


def test_a_tag_beside_a_korean_share_and_machine_name_is_still_carried():
    name = TAG + " [C D] {Z:=//NAS/공유} 파디엠써피스"
    pairing = [{"device_id": "pc@mesh+9", "connected": True, "agent_name": name}]
    beat, executor = _beat([], pairing=pairing, now=4000.0)
    assert beat is not None
    assert beat["presence"][0]["agent_name"] == name
    assert TAG in executor._reported_pairing_tags
