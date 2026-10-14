"""Mock task durability: no simulation claims continuity after a server restart."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phone_history import DurableMockPhoneTasks
from phone_mock import TaskError


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, value):
        self.now += value


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "mock_tasks.json"
        self.clock = FakeClock()
        self.payload = dict(
            request_id="durable_0001", goal="가상 상담 목적 확인",
            destination="가상 문의처", scenario="standard", source="claw",
            questions="질문 1", notes="주의사항", script_id="sample-general",
        )
        self.store = DurableMockPhoneTasks(self.path, clock=self.clock)

    def test_restart_while_active_marks_interrupted_and_preserves_id(self):
        created = self.store.create(self.payload)
        restored = DurableMockPhoneTasks(self.path, clock=self.clock)
        result = restored.get(created["task_id"])
        self.assertEqual(result["state"], "INTERRUPTED")
        self.assertTrue(result["terminal"])
        self.assertEqual(result["network_calls"], 0)
        self.assertEqual(result["real_charges"], 0)
        self.assertEqual(restored.create(self.payload)["task_id"], created["task_id"])
        with self.assertRaises(TaskError) as err:
            restored.create({**self.payload, "goal": "다른 업무"})
        self.assertEqual(err.exception.status, 409)

    def test_completion_survives_restart(self):
        created = self.store.create(self.payload)
        self.clock.advance(100)
        finished = self.store.get(created["task_id"])
        self.assertEqual(finished["state"], "COMPLETED")
        restored = DurableMockPhoneTasks(self.path, clock=self.clock)
        self.assertEqual(restored.get(created["task_id"])["state"], "COMPLETED")
        self.assertEqual(restored.get(created["task_id"])["simulated_elapsed_minutes"], 30)
        self.assertEqual(restored.summary()["completed"], 1)
        self.assertEqual(restored.get(created["task_id"])["questions"], "질문 1")

    def test_cancel_survives_restart(self):
        created = self.store.create(self.payload)
        self.clock.advance(2)
        stopped = self.store.cancel(created["task_id"])
        restored = DurableMockPhoneTasks(self.path, clock=self.clock)
        self.assertEqual(restored.get(created["task_id"])["state"], "CANCELLED")
        self.assertEqual(restored.get(created["task_id"])["simulated_elapsed_minutes"], stopped["simulated_elapsed_minutes"])

    def test_list_commits_terminal_states(self):
        created = self.store.create(self.payload)
        self.clock.advance(20)
        self.assertEqual(self.store.list()[0]["state"], "COMPLETED")
        reopened = DurableMockPhoneTasks(self.path, clock=self.clock)
        self.assertEqual(reopened.get(created["task_id"])["state"], "COMPLETED")

    def test_corruption_is_not_silently_replaced(self):
        created = self.store.create(self.payload)
        text = json.loads(self.path.read_text(encoding="utf-8"))
        text["tasks"][0]["snapshot"]["network_calls"] = 1
        self.path.write_text(json.dumps(text), encoding="utf-8")
        with self.assertRaises(ValueError):
            DurableMockPhoneTasks(self.path, clock=self.clock)
        self.assertTrue(self.path.exists())

    def test_max_tasks_rejected_without_corruption(self):
        limited = DurableMockPhoneTasks(self.path, clock=self.clock, max_tasks=1)
        limited.create(self.payload)
        with self.assertRaises(TaskError):
            limited.create({**self.payload, "request_id": "durable_0002"})
        self.assertEqual(len(DurableMockPhoneTasks(self.path, clock=self.clock).list()), 1)


if __name__ == "__main__":
    unittest.main()
