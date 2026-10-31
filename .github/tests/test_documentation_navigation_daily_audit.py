"""Focused contract tests for the daily documentation-navigation audit.

The audit is read-only and must stay silent when the index is healthy, so the
load-bearing behaviors to pin are: it detects a broken index path, it detects
an entry point that has outgrown the runtime loading limit, and it does not
comment on the maintenance issue when there is nothing to action.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github" / "scripts" / "documentation_navigation_daily_audit.py"

SPEC = importlib.util.spec_from_file_location("documentation_navigation_daily_audit", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)

HUB_TAIL = "SCOPE = NAVIGATION_ONLY\n\nDOC_STATUS = CANONICAL\n"


class TemporaryIndex(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.original_repo = audit.REPO
        audit.REPO = self.root
        self.posts = []
        self.original_post = audit.post_to_issue
        audit.post_to_issue = lambda body, issue: self.posts.append((body, issue))
        self.write_clean_index()

    def tearDown(self) -> None:
        audit.REPO = self.original_repo
        audit.post_to_issue = self.original_post
        self.directory.cleanup()

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_clean_index(self) -> None:
        self.write("README.md", "# Repository\n\n- Instructions: [AGENTS.md](AGENTS.md)\n")
        self.write(
            "AGENTS.md",
            "# Agent Rules\n\n"
            "- `docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md`\n"
            "- `docs/operations/TEST_SCOPE_AND_DELIVERY_POLICY.md`\n"
            "- `docs/operations/TECHNOLOGY_ADOPTION_POLICY.md`\n"
            "- `docs/operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md`\n"
            "- `docs/operations/GITHUB_REPORT_HANDOFF_POLICY.md`\n"
            "- `docs/operations/MULTI_MACHINE_LOCAL_WORKTREE_POLICY.md`\n"
            "- [model hub](docs/models/README.md)\n",
        )
        hub_links = "\n".join(
            f"- [{name}]({name.removeprefix('docs/')})" for name in audit.HUBS
        )
        self.write("docs/README.md", f"# Docs\n\n{hub_links}\n")
        for name in audit.HUBS:
            self.write(name, f"# {name}\n\n{HUB_TAIL}")
        self.write("docs/operations/README.md", "# Operations\n")
        self.write("docs/governance/DOCUMENTATION_AUTHORITY_MODEL.md", "# Authority\n")
        for policy in (
            "AI_DEVELOPMENT_OPERATING_POLICY.md",
            "TEST_SCOPE_AND_DELIVERY_POLICY.md",
            "TECHNOLOGY_ADOPTION_POLICY.md",
            "MODEL_CHANGE_OWNER_APPROVAL_POLICY.md",
            "GITHUB_REPORT_HANDOFF_POLICY.md",
            "MULTI_MACHINE_LOCAL_WORKTREE_POLICY.md",
        ):
            self.write(f"docs/operations/{policy}", f"# {policy}\n")


class DocumentationNavigationAuditTests(TemporaryIndex):
    def test_clean_index_is_silent_and_reports_ok(self) -> None:
        code = audit.main(["--no-post"])
        self.assertEqual(code, 0, "a healthy index must not be reported as work")
        self.assertEqual(self.posts, [], "a healthy index must not touch the issue")

    def test_clean_index_without_no_post_still_does_not_comment(self) -> None:
        code = audit.main([])
        self.assertEqual(code, 0)
        self.assertEqual(self.posts, [])

    def test_broken_index_path_is_a_failure_and_is_reported(self) -> None:
        self.write("AGENTS.md", "# Agent Rules\n\n- `docs/operations/GONE_POLICY.md`\n")
        code = audit.main([])
        self.assertEqual(code, 1)
        self.assertEqual(len(self.posts), 1)
        body, issue = self.posts[0]
        self.assertIn("GONE_POLICY.md", body)
        self.assertEqual(issue, "5002")

    def test_entry_point_above_runtime_loading_limit_is_a_failure(self) -> None:
        filler = "- rule " + ("a" * (audit.HARD_LIMIT_BYTES + 10)) + "\n"
        self.write("AGENTS.md", filler)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = audit.main(["--no-post"])
        self.assertEqual(code, 1)
        self.assertIn("above the 32768 byte limit", buffer.getvalue())

    def test_size_below_the_goal_is_reported_as_information_only(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = audit.main(["--no-post"])
        self.assertEqual(code, 0)
        self.assertIn("AGENTS_BYTES=", buffer.getvalue())
        self.assertIn("[INFO]", buffer.getvalue())
        self.assertNotIn("[FAIL]", buffer.getvalue())

    def test_hub_that_lost_its_navigation_marker_is_a_failure(self) -> None:
        self.write("docs/models/README.md", "# Model hub\n\nno markers here\n")
        code = audit.main(["--no-post"])
        self.assertEqual(code, 1)

    def test_entry_point_that_dropped_a_canonical_pointer_is_a_failure(self) -> None:
        self.write("AGENTS.md", "# Agent Rules\n\n- short entry point\n")
        code = audit.main(["--no-post"])
        self.assertEqual(code, 1)

    def test_missing_index_file_is_an_audit_error_not_a_finding(self) -> None:
        (self.root / "AGENTS.md").unlink()
        code = audit.main([])
        self.assertEqual(code, 2)
        self.assertEqual(self.posts, [])


if __name__ == "__main__":
    unittest.main()
