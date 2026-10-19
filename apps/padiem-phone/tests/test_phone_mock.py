"""Local-only phone simulator contract tests. No external telephony is used."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phone_mock import MockPhoneTasks, TaskError, SCENARIOS


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class MockPhoneTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.store = MockPhoneTasks(clock=self.clock)
        self.payload = {
            "request_id": "phone_test001",
            "goal": "이용 내역을 확인해 주세요",
            "destination": "가상 고객센터",
            "source": "web",
            "scenario": "standard",
        }

    def test_starts_dialing_and_no_network_charge(self):
        task = self.store.create(self.payload)
        self.assertEqual(task["state"], "DIALING")
        self.assertEqual(task["network_calls"], 0)
        self.assertEqual(task["real_charges"], 0)
        self.assertEqual(self.store.summary()["real_calls"], 0)

    def test_idempotent_same_payload(self):
        a = self.store.create(self.payload)
        b = self.store.create(dict(self.payload))
        self.assertEqual(a["task_id"], b["task_id"])
        self.assertEqual(self.store.summary()["tasks"], 1)

    def test_conflicting_reuse_rejected(self):
        self.store.create(self.payload)
        changed = dict(self.payload, goal="다른 업무 문의")
        with self.assertRaises(TaskError) as err:
            self.store.create(changed)
        self.assertEqual(err.exception.status, 409)

    def test_standard_phase_order_and_duration(self):
        task = self.store.create(self.payload)
        task_id = task["task_id"]
        self.clock.advance(1.2)
        self.assertEqual(self.store.get(task_id)["state"], "IVR")
        self.clock.advance(1.2)
        self.assertEqual(self.store.get(task_id)["state"], "HOLD")
        self.clock.advance(2.0)
        self.assertEqual(self.store.get(task_id)["state"], "CONSULTING")
        self.clock.advance(1.6)
        done = self.store.get(task_id)
        self.assertEqual(done["state"], "COMPLETED")
        self.assertEqual(done["simulated_elapsed_minutes"], 30)
        self.assertEqual(done["simulated_connected_minutes"], 28)
        self.assertTrue(done["terminal"])

    def test_extended_wait(self):
        task = self.store.create(dict(self.payload, scenario="extended"))
        self.clock.advance(8.0)
        result = self.store.get(task["task_id"])
        self.assertEqual(result["simulated_elapsed_minutes"], 65)
        self.assertEqual(result["state"], "COMPLETED")

    def test_no_answer_and_verification_distinct(self):
        for scenario, expected in [("no_answer", "NO_ANSWER"), ("verification", "AUTH_REQUIRED")]:
            clock = FakeClock()
            store = MockPhoneTasks(clock=clock)
            task = store.create(dict(self.payload, scenario=scenario))
            clock.advance(30)
            actual = store.get(task["task_id"])
            self.assertEqual(actual["state"], expected)
            self.assertTrue(actual["terminal"])
            self.assertEqual(actual["network_calls"], 0)

    def test_cancel_freezes_usage_and_prevents_progress(self):
        task = self.store.create(self.payload)
        self.clock.advance(2)
        stopped = self.store.cancel(task["task_id"])
        recorded = stopped["simulated_elapsed_minutes"]
        self.clock.advance(60)
        again = self.store.get(task["task_id"])
        self.assertEqual(again["state"], "CANCELLED")
        self.assertEqual(again["simulated_elapsed_minutes"], recorded)
        self.assertEqual(self.store.cancel(task["task_id"])["state"], "CANCELLED")

    def test_completed_task_cannot_be_cancelled(self):
        task = self.store.create(self.payload)
        self.clock.advance(40)
        self.assertEqual(self.store.cancel(task["task_id"])["state"], "COMPLETED")

    def test_missing_unknown_task(self):
        with self.assertRaises(TaskError) as err:
            self.store.get("missing")
        self.assertEqual(err.exception.status, 404)

    def test_invalid_payloads_and_types(self):
        bads = [
            {}, dict(self.payload, request_id="x"),
            dict(self.payload, scenario=[]),
            dict(self.payload, scenario="live"),
            dict(self.payload, source="unauthorized"),
            dict(self.payload, goal=""),
            dict(self.payload, destination=""),
            dict(self.payload, goal="a" * 301),
            dict(self.payload, goal="bad\ntext"),
            [],
        ]
        for payload in bads:
            with self.subTest(payload=repr(payload)[:60]):
                with self.assertRaises(TaskError):
                    self.store.create(payload)
        self.assertEqual(self.store.summary()["tasks"], 0)

    def test_max_tasks_hard_limit(self):
        store = MockPhoneTasks(clock=self.clock, max_tasks=1)
        store.create(self.payload)
        with self.assertRaises(TaskError) as err:
            store.create(dict(self.payload, request_id="phone_test002"))
        self.assertEqual(err.exception.status, 429)

    def test_usage_summary(self):
        a = self.store.create(self.payload)
        self.store.create(dict(self.payload, request_id="phone_test002"))
        self.clock.advance(6.1)
        summary = self.store.summary()
        self.assertEqual(summary["tasks"], 2)
        self.assertEqual(summary["completed"], 2)
        self.assertEqual(summary["active"], 0)
        self.assertEqual(summary["simulated_elapsed_minutes"], 60)
        self.assertEqual(summary["real_charges"], 0)

    def test_all_scenarios_have_terminal_end(self):
        for scenario, steps in SCENARIOS.items():
            self.assertIn(steps[-1][0], ("COMPLETED", "NO_ANSWER", "AUTH_REQUIRED"))
            self.assertEqual(steps[-1][2], 0)


if __name__ == "__main__":
    unittest.main()
