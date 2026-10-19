"""Pure mock task timeline and report projections, never carrier evidence."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phone_mock import MockPhoneTasks, TaskError
from phone_reports import task_timeline, task_report, stage_usage


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class ReportsTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.tasks = MockPhoneTasks(clock=self.clock)
        self.payload = {
            "request_id": "report_req001",
            "destination": "가상 상담회사",
            "goal": "확인할 목적 테스트",
            "source": "web",
            "scenario": "standard",
            "questions": "문의할 항목이 무엇인가요?",
            "notes": "변경 승인하지 말 것",
        }

    def test_only_reached_stages_are_reported(self):
        created = self.tasks.create(self.payload)
        events = task_timeline(created)
        self.assertEqual([x["state"] for x in events], ["DIALING"])
        self.assertEqual(events[-1]["phase"], "current")
        self.clock.now = 2.7
        mid = self.tasks.get(created["task_id"])
        self.assertEqual(mid["state"], "HOLD")
        self.assertEqual([x["state"] for x in task_timeline(mid)], ["DIALING", "IVR", "HOLD"])
        self.assertTrue(all(x["simulation_only"] for x in task_timeline(mid)))
        self.assertNotIn("COMPLETED", [x["state"] for x in task_timeline(mid)])

    def test_terminal_timeline_and_text_report(self):
        created = self.tasks.create(self.payload)
        self.clock.now = 30
        snap = self.tasks.get(created["task_id"])
        states = [x["state"] for x in task_timeline(snap)]
        self.assertEqual(states, ["DIALING", "IVR", "HOLD", "CONSULTING", "COMPLETED"])
        self.assertEqual(task_timeline(snap)[-1]["phase"], "complete")
        report = task_report(snap)
        for value in ("모의 전화 업무 보고서", "실제 발신", "가상 경과시간", "변경 승인하지 말 것", "실제 통신요금: 0원"):
            self.assertIn(value, report)
        self.assertNotIn("실제 상담 처리 완료", report)

    def test_cancelled_does_not_add_future_steps(self):
        task = self.tasks.create(self.payload)
        self.clock.now = 2.7
        snap = self.tasks.cancel(task["task_id"])
        states = [x["state"] for x in task_timeline(snap)]
        self.assertEqual(states, ["DIALING", "IVR", "HOLD", "CANCELLED"])
        self.assertNotIn("CONSULTING", states)
        self.assertEqual(task_timeline(snap)[-1]["phase"], "stopped")

    def test_no_answer_does_not_claim_consultation(self):
        snap = self.tasks.create({**self.payload, "scenario": "no_answer"})
        self.clock.now = 10
        snap = self.tasks.get(snap["task_id"])
        self.assertEqual([x["state"] for x in task_timeline(snap)], ["DIALING", "NO_ANSWER"])
        self.assertNotIn("상담 진행", task_report(snap))

    def test_reboot_interruption_is_explicit(self):
        task = self.tasks.create(self.payload)
        snap = {**task, "state": "INTERRUPTED", "terminal": True}
        trail = task_timeline(snap)
        self.assertEqual(trail[-1]["state"], "INTERRUPTED")
        self.assertIn("중단", task_report(snap))

    def test_stage_usage_breakdown_is_only_mock_data(self):
        first = self.tasks.create(self.payload)
        second = self.tasks.create({**self.payload, "request_id": "report_req002", "scenario": "extended"})
        self.clock.now = 20
        first_snap = self.tasks.get(first["task_id"])
        second_snap = self.tasks.get(second["task_id"])
        summary = stage_usage([first_snap, second_snap])
        values = {row["state"]: row["simulated_minutes"] for row in summary["stages"]}
        self.assertEqual(values["DIALING"], 4)
        self.assertEqual(values["IVR"], 6)
        self.assertEqual(values["HOLD"], 75)
        self.assertEqual(values["CONSULTING"], 10)
        self.assertEqual(summary["real_calls"], 0)
        self.assertEqual(summary["real_charges"], 0)
        self.assertTrue(summary["simulation_only"])

    def test_malformed_timeline_fails_closed(self):
        task = self.tasks.create(self.payload)
        for invalid in [
            {}, {"scenario": "foreign"},
            {**task, "stage_index": -1},
            {**task, "stage_index": 100},
            {**task, "simulated_elapsed_minutes": True},
        ]:
            with self.subTest(value=str(invalid)[:35]), self.assertRaises(TaskError):
                task_timeline(invalid)


if __name__ == "__main__":
    unittest.main()
