from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kagent.core import AgentBoundaryError, AgentSession


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

    def test_outside_root_is_rejected(self):
        temp, root = self.make_repo()
        self.addCleanup(temp.cleanup)
        session = AgentSession.open(root, "범위를 확인해줘")
        with self.assertRaises(AgentBoundaryError):
            session.contained("../outside.txt")

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

    def test_reject_discards_pending_patch(self):
        temp, root = self.make_repo()
        self.addCleanup(temp.cleanup)
        session = AgentSession.open(root, "README 변경")
        session.prepare_demo_patch("README.md")
        session.reject()
        self.assertIsNone(session.proposed_path)
        self.assertFalse(session.permissions.write)


if __name__ == "__main__":
    unittest.main()
