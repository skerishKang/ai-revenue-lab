from __future__ import annotations

import unittest

from kagent.contracts import ClawRunStatus, ClawTaskIntent, ExecutionMode
from kagent.runs import ClawRun, InMemoryRunStore, RunStateError


class ClawRunTests(unittest.TestCase):
    def intent(self, *, mode: ExecutionMode = ExecutionMode.LOCAL) -> ClawTaskIntent:
        return ClawTaskIntent(
            task_id="task_001",
            task="로그인 오류를 분석하고 수정해줘",
            repository_ref="skerishKang/example",
            execution_mode=mode,
        )

    def test_full_product_lifecycle_and_approval_projection(self):
        run = ClawRun.create("run_001", self.intent(mode=ExecutionMode.CLOUD))
        self.assertEqual(run.status, ClawRunStatus.QUEUED)

        run.transition(ClawRunStatus.PREPARING, summary="환경 준비")
        run.transition(ClawRunStatus.RUNNING, summary="작업 실행")
        run.record_changed_files(["src/a.py", "tests/test_a.py"])
        run.transition(ClawRunStatus.WAITING_APPROVAL, summary="사용자 승인 대기")
        paused = run.projection().safe_dict()
        self.assertTrue(paused["approval_required"])
        self.assertFalse(paused["terminal"])
        self.assertEqual(paused["changed_files"], ["src/a.py", "tests/test_a.py"])

        run.transition(ClawRunStatus.RUNNING, summary="승인 후 계속")
        run.transition(ClawRunStatus.COMPLETED, summary="완료")
        completed = run.projection().safe_dict()
        self.assertTrue(completed["terminal"])
        self.assertFalse(completed["approval_required"])

    def test_illegal_shortcut_transition_fails_closed(self):
        run = ClawRun.create("run_002", self.intent())
        with self.assertRaises(RunStateError):
            run.transition(ClawRunStatus.COMPLETED)
        self.assertEqual(run.status, ClawRunStatus.QUEUED)

    def test_terminal_run_cannot_resume_or_change_files(self):
        run = ClawRun.create("run_003", self.intent())
        run.transition(ClawRunStatus.PREPARING)
        run.transition(ClawRunStatus.RUNNING)
        run.transition(ClawRunStatus.CANCELLED, summary="사용자 취소")
        with self.assertRaises(RunStateError):
            run.transition(ClawRunStatus.RUNNING)
        with self.assertRaises(RunStateError):
            run.record_changed_files(["late.py"])
        self.assertEqual(run.status, ClawRunStatus.CANCELLED)
        self.assertEqual(run.changed_files, ())

    def test_invalid_projection_data_does_not_mutate_current_state(self):
        run = ClawRun.create("run_004", self.intent())
        with self.assertRaises(ValueError):
            run.transition(ClawRunStatus.PREPARING, summary="x" * 2_001)
        self.assertEqual(run.status, ClawRunStatus.QUEUED)
        self.assertEqual(run.summary, "")

    def test_in_memory_store_rejects_duplicate_and_unknown_run(self):
        store = InMemoryRunStore()
        run = ClawRun.create("run_005", self.intent())
        store.add(run)
        self.assertEqual(len(store), 1)
        self.assertEqual(store.get("run_005"), run)
        with self.assertRaises(RunStateError):
            store.add(ClawRun.create("run_005", self.intent()))
        with self.assertRaises(RunStateError):
            store.get("run_missing")

    def test_projection_redacts_accidental_secret_summary(self):
        run = ClawRun.create("run_006", self.intent())
        run.transition(
            ClawRunStatus.PREPARING,
            summary="token=supersecretvalue 준비 중",
        )
        rendered = str(run.projection().safe_dict())
        self.assertNotIn("supersecretvalue", rendered)
        self.assertIn("REDACTED", rendered)


if __name__ == "__main__":
    unittest.main()
