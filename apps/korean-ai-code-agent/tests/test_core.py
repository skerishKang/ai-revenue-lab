from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kagent.core import AgentBoundaryError, AgentSession, redact_secrets


class AgentSessionTests(unittest.TestCase):
    def make_repo(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "README.md").write_text("# fixture\n", encoding="utf-8")
        return temp, root

    def test_plan_only_contract_has_no_mutation_permission(self):
        temp, root = self.make_repo()
        self.addCleanup(temp.cleanup)
        session = AgentSession.open(root, "저장 버튼 오류를 분석해줘")
        session.inspect()
        self.assertFalse(session.permissions.write)
        self.assertFalse(session.permissions.command)
        self.assertFalse(session.permissions.network)
        self.assertFalse(session.permissions.git_mutation)
        self.assertGreaterEqual(len(session.plan()), 5)

    def test_korean_task_contract_rejects_english_only(self):
        temp, root = self.make_repo()
        self.addCleanup(temp.cleanup)
        with self.assertRaises(AgentBoundaryError):
            AgentSession.open(root, "fix the save button")

    def test_korean_task_contract_accepts_mixed_code_terms(self):
        temp, root = self.make_repo()
        self.addCleanup(temp.cleanup)
        session = AgentSession.open(root, "README save flow를 수정해줘")
        self.assertIn("수정", session.task)

    def test_outside_root_is_rejected(self):
        temp, root = self.make_repo()
        self.addCleanup(temp.cleanup)
        session = AgentSession.open(root, "범위를 확인해줘")
        with self.assertRaises(AgentBoundaryError):
            session.contained("../outside.txt")

    def test_symlink_escape_is_rejected_and_not_inspected(self):
        temp, root = self.make_repo()
        self.addCleanup(temp.cleanup)
        outside_dir = Path(temp.name).parent / f"{Path(temp.name).name}-outside"
        outside_dir.mkdir(exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(outside_dir, ignore_errors=True))
        outside_file = outside_dir / "secret.txt"
        outside_file.write_text("outside\n", encoding="utf-8")
        link = root / "escape.txt"
        try:
            link.symlink_to(outside_file)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is unavailable on this platform")

        session = AgentSession.open(root, "심볼릭 링크 경계를 확인해줘")
        with self.assertRaises(AgentBoundaryError):
            session.contained("escape.txt")
        self.assertNotIn("escape.txt", session.inspect(limit=50))

    def test_write_denied_leaves_file_unchanged(self):
        temp, root = self.make_repo()
        self.addCleanup(temp.cleanup)
        session = AgentSession.open(root, "README를 검토해줘")
        session.inspect()
        before = (root / "README.md").read_text(encoding="utf-8")
        session.prepare_demo_patch("README.md")
        with self.assertRaises(AgentBoundaryError):
            session.apply()
        self.assertEqual((root / "README.md").read_text(encoding="utf-8"), before)

    def test_approved_patch_changes_only_selected_file(self):
        temp, root = self.make_repo()
        self.addCleanup(temp.cleanup)
        other = root / "other.txt"
        other.write_text("keep\n", encoding="utf-8")
        session = AgentSession.open(root, "README 변경 미리보기")
        session.prepare_demo_patch("README.md")
        session.permissions.write = True
        changed = session.apply()
        self.assertEqual(changed, root / "README.md")
        self.assertIn("KAGENT SYNTHETIC PREVIEW", changed.read_text(encoding="utf-8"))
        self.assertEqual(other.read_text(encoding="utf-8"), "keep\n")

    def test_apply_fails_closed_if_file_changed_after_preview(self):
        temp, root = self.make_repo()
        self.addCleanup(temp.cleanup)
        target = root / "README.md"
        session = AgentSession.open(root, "동시 변경을 보호해줘")
        session.prepare_demo_patch("README.md")
        target.write_text("# someone else changed it\n", encoding="utf-8")
        session.permissions.write = True
        with self.assertRaises(AgentBoundaryError):
            session.apply()
        self.assertEqual(target.read_text(encoding="utf-8"), "# someone else changed it\n")

    def test_reject_discards_pending_patch_and_preserves_original(self):
        temp, root = self.make_repo()
        self.addCleanup(temp.cleanup)
        target = root / "README.md"
        before = target.read_text(encoding="utf-8")
        session = AgentSession.open(root, "README 변경을 거부해줘")
        session.prepare_demo_patch("README.md")
        session.reject()
        self.assertIsNone(session.proposed_path)
        self.assertFalse(session.permissions.write)
        self.assertEqual(target.read_text(encoding="utf-8"), before)

    def test_business14_mock_response_is_deterministic_and_network_free(self):
        temp, root = self.make_repo()
        self.addCleanup(temp.cleanup)
        first = AgentSession.open(root, "로그인 오류를 분석해줘").business14_mock_response()
        second = AgentSession.open(root, "로그인 오류를 분석해줘").business14_mock_response()
        self.assertEqual(first, second)
        self.assertEqual(first["route"], "b14/auto")
        self.assertEqual(first["provider_mode"], "mock")
        self.assertFalse(first["network_called"])
        self.assertEqual(first["status"], "resolved_not_called")
        self.assertTrue(str(first["request_id"]).startswith("kagent_"))

    def test_git_status_probe_is_read_only_command(self):
        temp, root = self.make_repo()
        self.addCleanup(temp.cleanup)
        session = AgentSession.open(root, "Git 상태를 확인해줘")
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=" M README.md\n", stderr=""
        )
        with mock.patch("kagent.core.subprocess.run", return_value=completed) as run:
            status = session.git_worktree_status()
        run.assert_called_once_with(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        self.assertEqual(status["status"], "dirty")
        self.assertEqual(status["changed_count"], 1)
        self.assertNotIn("commit", run.call_args.args[0])
        self.assertNotIn("push", run.call_args.args[0])

    @unittest.skipUnless(shutil.which("git"), "git executable required")
    def test_git_clean_and_dirty_detection_without_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            session = AgentSession.open(root, "Git 상태를 확인해줘")
            clean = session.git_worktree_status()
            self.assertTrue(clean["is_git_repository"])
            self.assertTrue(clean["clean"])
            (root / "new.txt").write_text("dirty\n", encoding="utf-8")
            dirty = session.git_worktree_status()
            self.assertFalse(dirty["clean"])
            self.assertEqual(dirty["status"], "dirty")
            self.assertGreaterEqual(dirty["changed_count"], 1)


class SecretRedactionTests(unittest.TestCase):
    def test_redacts_bearer_and_api_key_shapes(self):
        raw = (
            "Authorization: Bearer abcdef1234567890\n"
            "OPENROUTER_API_KEY=sk-or-v1-abcdef1234567890\n"
            "token=tokenvalue123456\n"
        )
        rendered = redact_secrets(raw)
        self.assertNotIn("abcdef1234567890", rendered)
        self.assertNotIn("tokenvalue123456", rendered)
        self.assertIn("[REDACTED", rendered)


if __name__ == "__main__":
    unittest.main()
