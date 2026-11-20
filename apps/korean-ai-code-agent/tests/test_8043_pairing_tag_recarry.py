"""#8043: a pending pairing tag is re-offered periodically, not once per process.

The executor used to remember every carried tag for its whole lifetime, so a
pairing whose first beat was lost -- or whose agent name had not updated yet --
was never offered again until restart. The cooldown re-offers a tag after
PAIRING_TAG_RECARRY_SECONDS so a still-pending code keeps reaching the server
until it is claimed. The clock is injected; no real time passes and no other
test file is imported.
"""
from __future__ import annotations

from kagent.local_agent_oracle_mesh_executor import (
    OracleMeshExecutor,
    PAIRING_TAG_RECARRY_SECONDS,
)

SECRET = "***" * 32
NODE = "pc@mesh+9"
TAG_NAME = "PADIEM pd-7a3f9c21 beta-notebook"


class _StubPort:
    def read_bytes(self, *, node_ref, file_path, timeout_seconds=60, max_bytes=None):
        raise AssertionError("not used")


def _executor(clock, seen):
    def transport(path, payload):
        seen.append(payload)
        return 200, {"ok": True, "dispatch": None}

    return OracleMeshExecutor(
        chat_origin="https://chat.example.test",
        channel_secret=SECRET,
        read_port=_StubPort(),
        pairing_provider=lambda: [
            {"device_id": NODE, "connected": True, "agent_name": TAG_NAME}
        ],
        transport=transport,
        share_clock=lambda: clock[0],
    )


def test_a_carried_tag_is_quiet_within_the_cooldown():
    clock = [1000.0]
    seen: list = []
    executor = _executor(clock, seen)
    executor.run_once()
    assert seen[0]["presence"][0]["agent_name"] == TAG_NAME
    assert "pd-7a3f9c21" in executor._reported_pairing_tags
    # An immediate second poll is inside the cooldown: the tag is not re-offered,
    # and with no other source the beat carries nothing at all.
    executor.run_once()
    assert seen[1] is None


def test_the_same_tag_is_re_offered_after_the_cooldown():
    clock = [1000.0]
    seen: list = []
    executor = _executor(clock, seen)
    executor.run_once()
    assert seen[0]["presence"][0]["agent_name"] == TAG_NAME
    clock[0] += PAIRING_TAG_RECARRY_SECONDS + 1.0
    executor.run_once()
    assert seen[1]["presence"][0]["agent_name"] == TAG_NAME


def test_a_refused_poll_leaves_the_tag_unreported_so_it_can_be_offered_again():
    clock = [1000.0]

    def transport(path, payload):
        return 503, {"ok": False}

    executor = OracleMeshExecutor(
        chat_origin="https://chat.example.test",
        channel_secret=SECRET,
        read_port=_StubPort(),
        pairing_provider=lambda: [
            {"device_id": NODE, "connected": True, "agent_name": TAG_NAME}
        ],
        transport=transport,
        share_clock=lambda: clock[0],
    )
    try:
        executor.poll_once()
    except Exception:
        pass
    # Nothing was acknowledged, so nothing is remembered as carried.
    assert executor._reported_pairing_tags == {}
