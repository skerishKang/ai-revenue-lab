"""Ensure broad B62 pytest runs once in Chat CI, not again in accessibility QA."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / ".github" / "workflows"


class B62AccessibilityTestDelegation(unittest.TestCase):
    def test_chat_ci_owns_full_suite_and_covers_all_chat_paths(self):
        chat = (FOLDER / "b62-padiem-chat-ci.yml").read_text(encoding="utf-8")
        unified = (FOLDER / "b62-browser-qa-unified.yml").read_text(encoding="utf-8")
        qa = unified.split("\n  accessibility-browser-qa:\n", 1)[1].split(
            "\n  auth-history-browser-qa:\n", 1
        )[0]
        self.assertIn("run: uv run --locked python -m pytest -q", chat)
        self.assertIn("name: B62 tests", chat)
        self.assertIn("  pull_request:", chat)
        self.assertIn('      - "apps/padiem-chat/**"', chat)
        self.assertIn("apps/padiem-chat/**", (FOLDER.parent / "ci" / "b62_browser_qa_paths.json").read_text(encoding="utf-8"))
        self.assertNotIn("Run B62 regression suite", qa)
        self.assertNotIn("run: uv run pytest -q", qa)
        self.assertIn("Desktop and mobile accessibility QA", qa)
        self.assertIn("All-theme small-type accessibility QA", qa)
        self.assertIn("All-theme product confirmation dialog QA", qa)
        self.assertIn("Cache pinned Playwright Chromium", qa)
        self.assertIn("cancel-in-progress: true", unified)


if __name__ == "__main__":
    unittest.main()
