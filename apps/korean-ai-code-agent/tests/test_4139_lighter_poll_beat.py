"""#4139 follow-up: one poll asks the local server once, not once per question.

The presence beat wants two things from the same device table - whether each named
device is connected, and which connected device carries a pairing tag. Reading them
through the per-device questions cost five full ``meshctrl.js listdevices``
enumerations for two named devices in one quiet round, on the same host that is
supposed to be idle. These tests count the enumerations.
"""
from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import kagent.local_agent_oracle_mesh_executor as entry
import kagent.local_agent_mesh_failover as failover
from kagent.local_agent_oracle_mesh_executor import (
    IDLE_POLL_BASE_SECONDS, POLL_PATH, OracleMeshExecutor, _PresenceBeat, _beat_row,
)
#: Defined here, not imported from another suite: CI discovers these files with
#: ``unittest.TestLoader().discover("tests")``, which imports each module by its own
#: name and has no ``tests`` package to import from.
SECRET = "deployment-channel-secret-value-261017"


class _StubPort:
    """Stand-in read port; the channel transport is what is under test here."""

    def read_bytes(self, *, node_ref, file_path, timeout_seconds):  # noqa: D102
        del node_ref, file_path, timeout_seconds
        return b""

NODE_ONE = "node/abcd/nodeone@Dd2cdXxSOwp"
NODE_TWO = "node/abcd/nodetwo@Dd2cdXxSOwp"
NODE_THREE = "node/abcd/nodethree@Dd2cdXxSOwp"
TAGGED = "PC-ONE pd-7f3a9c01"
UNTAGGED = "Somewhere's laptop"


class _Table:
    """A local server that can be asked for its whole table, and counts the times."""

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [
            {"id": NODE_ONE, "name": TAGGED, "conn": 1},
            {"id": NODE_TWO, "name": UNTAGGED, "conn": 1},
            {"id": NODE_THREE, "name": "PC off", "conn": 0},
        ]
        self.runs = 0

    def listing(self):
        self.runs += 1
        return [dict(row) for row in self.rows]

    # The older per-device questions, each of which used to start its own enumeration.
    def connected_device_ids(self):
        return frozenset(r["id"] for r in self._once() if int(r.get("conn", 0) or 0) == 1)

    def is_connected(self, device_id):
        return device_id in self.connected_device_ids()

    def name_of(self, device_id):
        for row in self._once():
            if row.get("id") == device_id:
                return row.get("name")
        return None

    def pairing_candidates(self):
        return [
            {"device_id": r["id"], "connected": True, "agent_name": r["name"]}
            for r in self._once()
            if int(r.get("conn", 0) or 0) == 1 and isinstance(r.get("name"), str)
        ]

    def _once(self):
        self.runs += 1
        return [dict(row) for row in self.rows]


class _LegacyTable(_Table):
    """A presence that only answers the older per-device questions."""

    def __getattribute__(self, name):
        if name == "listing":
            raise AttributeError(name)
        return object.__getattribute__(self, name)


def _wired(table, device_ids):
    """The providers the service loop really builds, from a captured ``main()``."""
    captured = {}

    def factory(**kwargs):
        captured.update(kwargs)
        raise StopIteration()

    env = {
        "MESH_FAILOVER_DEVICE_ID": ",".join(device_ids),
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
         patch.object(failover, "MeshCentralDevicePresence", lambda **kwargs: table):
        try:
            entry.main(env)
        except StopIteration:
            pass
    return captured


def _executor(captured):
    sent = []

    def transport(path, payload):
        sent.append((path, payload))
        return 200, {"ok": True, "dispatch": None}

    executor = OracleMeshExecutor(
        chat_origin="https://chat.example.test", channel_secret=SECRET,
        read_port=_StubPort(), transport=transport,
        presence_provider=captured["presence_provider"],
        pairing_provider=captured["pairing_provider"],
        presence_round_begin=captured["presence_round_begin"],
    )
    return executor, sent


class TestOneRoundOneEnumeration(unittest.TestCase):
    def test_a_quiet_round_asks_the_local_server_once_for_two_devices(self):
        table = _Table()
        captured = _wired(table, [NODE_ONE, NODE_TWO])
        executor, sent = _executor(captured)
        before = table.runs
        self.assertIsNone(executor.run_once())
        self.assertEqual(table.runs - before, 1, "one listdevices per poll round")
        path, payload = sent[0]
        self.assertEqual(path, POLL_PATH)
        self.assertIsNotNone(payload, "the beat still travels")

    def test_the_beat_still_names_every_device_the_deployment_carries(self):
        table = _Table()
        captured = _wired(table, [NODE_ONE, NODE_TWO, NODE_THREE])
        executor, sent = _executor(captured)
        executor.run_once()
        entries = sent[0][1]["presence"]
        by_id = {entry["device_id"]: entry for entry in entries}
        self.assertEqual(set(by_id), {NODE_ONE, NODE_TWO, NODE_THREE})
        self.assertIs(by_id[NODE_ONE]["connected"], True)
        self.assertIs(by_id[NODE_THREE]["connected"], False)
        # #5573: a name that carries no pairing tag is private text about somebody's
        # machine, and it is dropped before it travels.
        self.assertNotIn("agent_name", by_id[NODE_TWO])
        self.assertNotIn("agent_name", by_id[NODE_THREE])

    def test_a_connected_untagged_device_is_never_offered_as_a_pairing_candidate(self):
        table = _Table()
        captured = _wired(table, [NODE_TWO])
        _executor(captured)
        rows = captured["pairing_provider"]()
        self.assertEqual([row["device_id"] for row in rows], [NODE_ONE],
                         "the tag is what makes a candidate, and an untagged name is "
                         "private text about somebody's machine")
        captured["pairing_provider"]()
        self.assertEqual(table.runs, 1)

    def test_a_tagged_device_the_deployment_does_not_name_is_still_offered_once(self):
        table = _Table()
        captured = _wired(table, [NODE_TWO])
        executor, sent = _executor(captured)
        executor.run_once()
        entries = {entry["device_id"]: entry for entry in sent[0][1]["presence"]}
        self.assertEqual(set(entries), {NODE_ONE, NODE_TWO},
                         "the candidate scope is the whole table, not the named list")
        self.assertEqual(entries[NODE_ONE]["agent_name"], TAGGED,
                         "a tagged name travels; an untagged one stays private")
        self.assertEqual(table.runs, 1, "the candidate read and the beat read are one table")
        executor.run_once()
        # #5573: the tag is reported once per process. A second round sees the same
        # table, and the beat keeps only the devices the deployment names.
        second = {entry["device_id"] for entry in sent[1][1]["presence"]}
        self.assertEqual(second, {NODE_TWO},
                         "the tag already travelled once, and this device was never "
                         "the deployment's to name")
        self.assertEqual(table.runs, 2)

    def test_the_next_round_asks_again_even_with_no_gap_between_rounds(self):
        table = _Table()
        captured = _wired(table, [NODE_ONE, NODE_TWO])
        executor, _sent = _executor(captured)
        before = table.runs
        executor.run_once()
        executor.run_once()
        executor.run_once()
        self.assertEqual(table.runs - before, 3,
                         "a busy lane must not report last round's PC as this round's")


class TestTheShareIsBounded(unittest.TestCase):
    def test_the_table_is_not_carried_past_the_loops_shortest_gap(self):
        table = _Table()
        beat = _PresenceBeat(table, IDLE_POLL_BASE_SECONDS)
        first = beat.rows()
        second = beat.rows()
        self.assertEqual(table.runs, 1, "both halves of one round read one table")
        self.assertEqual(first, second)
        with patch.object(entry.time, "monotonic",
                          return_value=time.monotonic() + IDLE_POLL_BASE_SECONDS):
            beat.rows()
        self.assertEqual(table.runs, 2, "the next round's table is its own")

    def test_a_presence_that_cannot_hand_one_table_answers_the_older_questions(self):
        table = _LegacyTable()
        captured = _wired(table, [NODE_ONE, NODE_TWO])
        self.assertIsNone(captured["presence_round_begin"]())
        rows = captured["presence_provider"]()
        self.assertEqual([row["device_id"] for row in rows], [NODE_ONE, NODE_TWO])
        self.assertTrue(all("connected" in row for row in rows))
        self.assertGreater(table.runs, 1, "the historical per-device shape is intact")

    def test_a_named_device_the_server_does_not_list_is_reported_offline_and_nameless(self):
        table = _Table()
        captured = _wired(table, ["node/abcd/not-in-the-table@Dd2cdXxSOwp"])
        rows = captured["presence_provider"]()
        self.assertEqual(rows, [{
            "device_id": "node/abcd/not-in-the-table@Dd2cdXxSOwp", "connected": False,
        }])


class TestTheRowShapeIsClosed(unittest.TestCase):
    def test_a_row_that_is_not_a_device_row_carries_nothing_forward(self):
        for junk in (None, "text", 7, [], {}):
            row = _beat_row(junk)
            self.assertEqual(row["device_id"], "")
            self.assertFalse(row["connected"])
            self.assertFalse(row["tagged"])

    def test_a_non_numeric_connection_field_is_not_connected(self):
        self.assertFalse(_beat_row({"id": NODE_ONE, "conn": "?"})["connected"])

    def test_a_non_callable_round_boundary_is_refused(self):
        with self.assertRaises(entry.ContractError):
            OracleMeshExecutor(
                chat_origin="https://chat.example.test", channel_secret=SECRET,
                read_port=_StubPort(), presence_round_begin="now",
            )


if __name__ == "__main__":
    unittest.main()
