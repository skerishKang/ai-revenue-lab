"""Phone mock Claw tool seam stays denied without existing canonical grant."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phone_mock import MockPhoneTasks, TaskError
from phone_scripts import ScriptStore
from phone_tool_bridge import CanonicalPhoneCaller, ClawPhoneTaskBridge


class ClawPhoneBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tasks = MockPhoneTasks()
        self.scripts = ScriptStore()
        self.trusted = CanonicalPhoneCaller("user-srv-1", "workspace-srv-1")
        self.other = CanonicalPhoneCaller("user-srv-2", "workspace-srv-2")
        self.request = {
            "request_id": "claw_task_001", "goal": "필요 서류를 물어줘",
            "destination": "가상 회사", "scenario": "standard"
        }

    def test_no_authority_fails_closed(self):
        bridge = ClawPhoneTaskBridge(tasks=self.tasks, scripts=self.scripts)
        with self.assertRaises(TaskError) as error:
            bridge.execute(self.trusted, "start_mock", self.request)
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(len(self.tasks.list()), 0)

    def test_denied_and_exception_authorizers_fail_before_mutation(self):
        for fn in (lambda c, a: False, lambda c, a: (_ for _ in ()).throw(RuntimeError("deny"))):
            bridge = ClawPhoneTaskBridge(tasks=self.tasks, scripts=self.scripts, authorize=fn)
            with self.assertRaises(TaskError) as error:
                bridge.execute(self.trusted, "start_mock", self.request)
            self.assertEqual(error.exception.status, 403)
        self.assertEqual(len(self.tasks.list()), 0)

    def test_authorized_start_status_cancel_and_scoped_owner(self):
        bridge = ClawPhoneTaskBridge(tasks=self.tasks, scripts=self.scripts, authorize=lambda c, a: True)
        task = bridge.execute(self.trusted, "start_mock", self.request)
        self.assertEqual(task["source"], "claw")
        self.assertEqual(task["network_calls"], 0)
        self.assertEqual(bridge.execute(self.trusted, "start_mock", self.request)["task_id"], task["task_id"])
        self.assertEqual(bridge.execute(self.trusted, "status", {"task_id": task["task_id"]})["task_id"], task["task_id"])
        for action in ("status", "cancel"):
            with self.assertRaises(TaskError) as err:
                bridge.execute(self.other, action, {"task_id": task["task_id"]})
            self.assertEqual(err.exception.status, 404)
        cancelled = bridge.execute(self.trusted, "cancel", {"task_id": task["task_id"]})
        self.assertEqual(cancelled["state"], "CANCELLED")

    def test_different_subjects_same_request_id_are_distinct(self):
        bridge = ClawPhoneTaskBridge(tasks=self.tasks, scripts=self.scripts, authorize=lambda c, a: True)
        a = bridge.execute(self.trusted, "start_mock", self.request)
        b = bridge.execute(self.other, "start_mock", self.request)
        self.assertNotEqual(a["task_id"], b["task_id"])
        self.assertEqual(len(self.tasks.list()), 2)

    def test_claw_tool_cannot_view_browser_task(self):
        browser = self.tasks.create({**self.request, "source": "web"})
        bridge = ClawPhoneTaskBridge(tasks=self.tasks, scripts=self.scripts, authorize=lambda c, a: True)
        with self.assertRaises(TaskError) as err:
            bridge.execute(self.trusted, "status", {"task_id": browser["task_id"]})
        self.assertEqual(err.exception.status, 404)

    def test_no_client_minted_grants_or_unbound_actions(self):
        bridge = ClawPhoneTaskBridge(tasks=self.tasks, scripts=self.scripts, authorize=lambda c, a: True)
        bad = [
            ("start_mock", {**self.request, "source": "web"}),
            ("start_mock", {**self.request, "is_authorized": True}),
            ("start_mock", {**self.request, "script_id": []}),
            ("status", {"task_id": "fake", "principal": "admin"}),
        ]
        for action, args in bad:
            with self.subTest(action=action, args=str(args)[:50]), self.assertRaises(TaskError):
                bridge.execute(self.trusted, action, args)
        with self.assertRaises(TaskError):
            bridge.execute(self.trusted, "dial_live", self.request)
        self.assertEqual(len(self.tasks.list()), 0)

    def test_script_snapshot_through_tool(self):
        bridge = ClawPhoneTaskBridge(tasks=self.tasks, scripts=self.scripts, authorize=lambda c, a: True)
        example = self.scripts.resolve("sample-general")
        result = bridge.execute(self.trusted, "start_mock", {
            **self.request, "goal": example["goal"],
            "destination": example["destination"], "script_id": example["script_id"],
        })
        self.assertEqual(result["notes"], example["notes"])
        self.assertEqual(result["questions"], example["questions"])


if __name__ == "__main__":
    unittest.main()
