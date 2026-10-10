"""Guard exactly sixteen pinned B62 browser QA lanes inside one workflow."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / ".github/workflows/b62-browser-qa-unified.yml"
MANIFEST = ROOT / ".github/ci/b62_browser_qa_paths.json"


class B62BrowserCacheContractTests(unittest.TestCase):
    def test_all_unified_browser_qa_jobs_have_safe_reusable_caches(self):
        import json
        text = MASTER.read_text(encoding="utf-8")
        jobs = json.loads(MANIFEST.read_text(encoding="utf-8"))["jobs"]
        self.assertEqual(len(jobs), 16)
        self.assertEqual(text.count("Cache pinned Playwright Chromium"), 16)
        for job in jobs:
            match = re.search(
                r"(?ms)^  " + re.escape(job) + r":\n(.*?)(?=^  [a-z][a-z0-9_-]*:\n|\Z)",
                text,
            )
            with self.subTest(job=job):
                self.assertIsNotNone(match)
                block = match.group(1)
                self.assertIn("enable-cache: true", block)
                self.assertIn("cache-dependency-glob: apps/padiem-chat/uv.lock", block)
                self.assertEqual(block.count("Cache pinned Playwright Chromium"), 1)
                self.assertEqual(block.count("actions/cache@v4"), 1)
                self.assertIn("path: ~/.cache/ms-playwright", block)
                self.assertIn("key: b62-playwright-1.55.0-", block)
                self.assertIn("runner.os", block)
                self.assertIn("runner.arch", block)
                self.assertLess(
                    block.index("Cache pinned Playwright Chromium"),
                    block.index("name: Install Chromium runtime"),
                )
        self.assertRegex(text, r"(?m)^  pull_request:")
        self.assertRegex(text, r"(?m)^  workflow_dispatch:")
        self.assertRegex(text, r"(?m)^concurrency:")
        self.assertRegex(text, r"(?m)^  cancel-in-progress: true$")


if __name__ == "__main__":
    unittest.main()
