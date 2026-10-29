"""#82 — the ten-minute lane read, judged only from state fields.

The unit the owner named is "a stop is known within ten minutes", and the failure
that made this exist was a stop nobody knew about. So the property these tests hold
hardest is not the stall detection — it is that **not knowing never comes out as
healthy**, and that a PC with a live claim is never described as silent.
"""
from __future__ import annotations

import importlib.util
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "connector_lane_watch", ROOT / "scripts" / "connector_lane_watch.py",
)
watch = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(watch)

NOW = time.time()


def lane(*, unclaimed=(0, None), claimed=(0, None), nodes=(), beats=None) -> dict:
    return {
        "ok": True,
        "unclaimed": {"count": unclaimed[0], "oldest_seconds": unclaimed[1]},
        "claimed": {"count": claimed[0], "oldest_seconds": claimed[1]},
        "nodes": list(nodes),
        "beats": list(beats) if beats is not None else [],
    }


def node(ref="node-com1@a", *, open_=1, oldest=10, waiting=1, waiting_oldest=10) -> dict:
    return {"node_ref": ref, "oldest_seconds": oldest, "open": open_,
            "waiting": waiting, "waiting_oldest_seconds": waiting_oldest}


def beat(device="device-oracle-1", *, seen=True, seconds_ago=5) -> dict:
    return {"device_id": device, "seen": seen, "connected": True,
            "received_at": (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - seconds_ago))
                if seen else None)}


class TestQueueVerdict(unittest.TestCase):
    def test_an_idle_queue_is_ok(self) -> None:
        self.assertEqual(watch.queue_verdict(lane()), ("ok", "queue_idle"))

    def test_recent_unclaimed_work_is_still_being_picked_up(self) -> None:
        # Boundary just under the bound: waiting for a claim inside the window is the
        # lane working, not the lane stalled.
        self.assertEqual(
            watch.queue_verdict(lane(unclaimed=(2, watch.QUEUE_STATIC_SECONDS)), )[0],
            "ok",
        )
        stalled = watch.queue_verdict(lane(unclaimed=(2, watch.QUEUE_STATIC_SECONDS + 1)))
        self.assertEqual(stalled, ("stall", f"queue_unclaimed_{watch.QUEUE_STATIC_SECONDS + 1}s"))

    def test_work_present_without_a_readable_age_is_not_an_ok(self) -> None:
        for bad in (None, "120", -5, True, 1.5):
            with self.subTest(bad=bad):
                verdict = watch.queue_verdict(lane(unclaimed=(1, bad)))[0]
                self.assertEqual(verdict, "unknown", bad)

    def test_a_missing_bucket_is_unknown_rather_than_zero(self) -> None:
        for shape in ({}, {"unclaimed": None}, {"unclaimed": {}}, [], None):
            with self.subTest(shape=shape):
                self.assertEqual(watch.queue_verdict(shape)[0], "unknown")


class TestPerPcSilence(unittest.TestCase):
    def test_a_claimed_command_is_busy_and_never_silent(self) -> None:
        """The rule this whole lane exists for.

        Three hours of unclaimed-age on a PC whose work is under a live claim is the
        PC doing a long job. Standard 1 says that job has no ceiling, so no age in
        `open`/`oldest_seconds` may produce a stall: only `waiting` decides.
        """
        rows = [node(open_=3, oldest=10_800, waiting=0, waiting_oldest=None)]
        self.assertEqual(watch.pc_silence_verdict(lane(nodes=rows)),
                         ("ok", "pc_nothing_waiting"))

    def test_unclaimed_work_past_the_bound_names_the_pc_age(self) -> None:
        bound = watch.PC_SILENT_SECONDS
        stalled = watch.pc_silence_verdict(
            lane(nodes=[node(open_=1, oldest=bound + 60, waiting=1, waiting_oldest=bound + 60)]),
        )
        self.assertEqual(stalled[0], "stall")
        self.assertEqual(stalled[1], f"pc_unanswered_{bound + 60}s")
        fresh = watch.pc_silence_verdict(
            lane(nodes=[node(open_=1, oldest=10, waiting=1, waiting_oldest=10)]),
        )
        self.assertEqual(fresh, ("ok", "pc_waiting_recently"))

    def test_the_oldest_pc_wins_when_several_are_waiting(self) -> None:
        rows = [node("node-a@1", waiting_oldest=700, oldest=700),
                node("node-b@2", waiting_oldest=900, oldest=900)]
        self.assertEqual(watch.pc_silence_verdict(lane(nodes=rows))[1], "pc_unanswered_900s")

    def test_waiting_without_a_readable_age_is_unknown(self) -> None:
        for bad in (None, "900", -1):
            with self.subTest(bad=bad):
                self.assertEqual(
                    watch.pc_silence_verdict(
                        lane(nodes=[node(waiting=1, waiting_oldest=bad)]))[0],
                    "unknown", bad)
        self.assertEqual(
            watch.pc_silence_verdict(lane(nodes=[node(waiting="one")]))[0], "unknown")
        self.assertEqual(watch.pc_silence_verdict(lane(nodes=[]))[0], "ok")
        self.assertEqual(watch.pc_silence_verdict({})[0], "unknown")


class TestExecutorLiveness(unittest.TestCase):
    def test_a_recent_beat_is_alive_and_an_old_one_is_a_stall(self) -> None:
        self.assertEqual(watch.liveness_verdict(lane(beats=[beat()]), now=NOW),
                         ("ok", "executor_beating"))
        old = watch.liveness_verdict(
            lane(beats=[beat(seconds_ago=watch.BEAT_STALL_SECONDS + 30)]), now=NOW,
        )
        self.assertEqual(old[0], "stall")
        self.assertIn(f"{watch.BEAT_STALL_SECONDS + 30}s", old[1])

    def test_a_future_stamp_is_zero_age_not_a_negative_one(self) -> None:
        skewed = {"device_id": "d", "seen": True,
                  "received_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW + 400))}
        verdict, reason = watch.liveness_verdict(lane(beats=[skewed]), now=NOW)
        self.assertEqual(verdict, "ok", "clock skew on two hosts is not a stall")
        self.assertEqual(reason, "executor_beating")

    def test_no_beat_recorded_is_unknown_never_offline_and_never_ok(self) -> None:
        # Absence of a record and a recorded disconnection are different facts, and
        # neither may be read as "alive" or as "the executor stopped".
        self.assertEqual(watch.liveness_verdict(lane(beats=[beat(seen=False)]), now=NOW),
                         ("unknown", "beat_never_recorded"))
        for shape in (lane(), lane(beats=[{"device_id": "d"}]),
                      lane(beats=[beat(seconds_ago=0) | {"received_at": "yesterday"}]),
                      lane(beats=[beat(seconds_ago=0) | {"received_at": None}])):
            with self.subTest(shape=str(shape)[:34]):
                self.assertEqual(watch.liveness_verdict(shape, now=NOW)[0], "unknown")


class TestChatHealthAndSource(unittest.TestCase):
    def test_only_200_is_healthy_and_a_dropped_connection_is_unknown(self) -> None:
        self.assertEqual(watch.chat_health_verdict(200), ("ok", "chat_health_200"))
        self.assertEqual(watch.chat_health_verdict(503), ("stall", "chat_health_503"))
        for bad in (None, 404, 0, "200"):
            with self.subTest(bad=bad):
                self.assertEqual(watch.chat_health_verdict(bad)[0],
                                 "stall" if bad == 503 else "unknown")

    def test_the_backend_names_which_store_is_the_live_one(self) -> None:
        self.assertEqual(watch.source_verdict("d1"), ("ok", "source_d1"))
        self.assertEqual(watch.source_verdict(None), ("ok", "source_d1"))
        # Unset and empty are the pre-move configuration: D1 is the live store then.
        self.assertEqual(watch.source_verdict(""), ("ok", "source_d1"))
        # After the COM2 move the D1 rows stop changing. Reading them would show a
        # stopped lane as an idle one, so an unported source is UNKNOWN by name.
        self.assertEqual(watch.source_verdict("com2"),
                         ("unknown", "source_com2_read_queue_side"))
        for bad in ("mysql", 7, "com2 x"):
            with self.subTest(bad=bad):
                self.assertEqual(watch.source_verdict(bad)[0], "unknown")


class TestCombine(unittest.TestCase):
    def test_a_stall_outranks_what_cannot_be_read(self) -> None:
        state, reasons = watch.combine({
            "beat": ("unknown", "channel_secret_absent"),
            "queue": ("stall", "queue_unclaimed_601s"),
        })
        self.assertEqual(state, "stall")
        self.assertEqual(reasons, ["beat=channel_secret_absent", "queue=queue_unclaimed_601s"])

    def test_unknown_outranks_ok_and_never_becomes_ok(self) -> None:
        self.assertEqual(watch.combine({"chat": ("ok", "chat_health_200"),
                                        "source": ("unknown", "source_com2_read_queue_side")})[0],
                         "unknown")
        self.assertEqual(watch.combine({"chat": ("ok", "chat_health_200")})[0], "ok")

    def test_an_unrecognised_verdict_is_treated_as_unknown(self) -> None:
        self.assertEqual(watch.combine({"x": ("maybe", "?"), "y": ("ok", "k")})[0], "unknown")


class TestDeviceIdList(unittest.TestCase):
    def test_the_list_is_bounded_and_rejects_anything_unsafe(self) -> None:
        self.assertEqual(watch._device_ids(""), [])
        self.assertEqual(watch._device_ids(" a , b ,, a "), ["a", "b"])
        self.assertEqual(len(watch._device_ids(",".join(f"d{i}" for i in range(30)))), 8)
        self.assertEqual(
            watch._device_ids("ok-1,${jndi:ldap://x},dev/a?b,session:7"),
            ["ok-1", "session:7"],
        )


class TestCloudflareWorkerErrors(unittest.TestCase):
    """#82 (d): which way the worker failed, as a number the edge itself sends.

    On 2026-10-29 the LAX path failed 40-50% of turns with 1101/1102 while other
    paths answered, so a bare 5xx is not enough to describe it. Only the numeric
    field is read; a page containing the digits is not a verdict.
    """

    def test_the_two_known_numbers_are_read_from_either_shape(self) -> None:
        self.assertEqual(watch.cloudflare_error_code({"error_code": 1101}), 1101)
        self.assertEqual(watch.cloudflare_error_code({"error_code": 1102}), 1102)
        self.assertEqual(watch.cloudflare_error_code({"errors": [{"code": 1102}]}), 1102)

    def test_anything_that_is_not_that_field_is_not_read_as_a_code(self) -> None:
        for bad in ({"error_code": "1102"}, {"error_code": True}, {"error_code": 1100},
                    {"error_code": 1103}, {"errors": [{"code": 1000}]}, {"errors": []},
                    {"errors": "1102"}, {"body": "cloudflare_error 1102"}, None, []):
            with self.subTest(bad=bad):
                self.assertIsNone(watch.cloudflare_error_code(bad))

    def test_a_5xx_names_the_number_and_an_unnamed_5xx_does_not(self) -> None:
        self.assertEqual(watch.chat_health_verdict(503, 1102),
                         ("stall", "chat_health_503_cloudflare_1102"))
        self.assertEqual(watch.chat_health_verdict(500, 1101),
                         ("stall", "chat_health_500_cloudflare_1101"))
        self.assertEqual(watch.chat_health_verdict(503, None), ("stall", "chat_health_503"))
        self.assertEqual(watch.chat_health_verdict(200, 1102), ("ok", "chat_health_200"),
                         "a healthy answer is healthy whatever a stray body says")

    def test_the_body_reader_takes_numbers_and_never_text(self) -> None:
        self.assertEqual(watch._health_error_code(b'{"error_code": 1101}'), 1101)
        self.assertEqual(watch._health_error_code(b'{"errors":[{"code":1102}]}'), 1102)
        for bad in (b"", b"not json", b'{"error_code": "1102"}', b"<html>1102</html>"):
            with self.subTest(bad=bad):
                self.assertIsNone(watch._health_error_code(bad))


if __name__ == "__main__":
    unittest.main()
