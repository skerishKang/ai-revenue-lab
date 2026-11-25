"""Guard exactly seventeen pinned B62 browser QA lanes inside one workflow."""
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
        self.assertEqual(len(jobs), 17)
        self.assertEqual(text.count("Cache pinned Playwright Chromium"), 17)
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
                self.assertIn("id: playwright-browser-cache", block)
                self.assertIn("path: ~/.cache/ms-playwright", block)
                self.assertIn("key: b62-playwright-headless-shell-1.55.0-", block)
                self.assertIn("runner.os", block)
                self.assertIn("runner.arch", block)
                hosted = "runs-on: ubuntu-24.04\n" in block
                browser_if = (
                    "if: steps.playwright-browser-cache.outputs.cache-hit != 'true'"
                    if hosted else
                    "if: runner.environment != 'self-hosted' && steps.playwright-browser-cache.outputs.cache-hit != 'true'"
                )
                self.assertIn(browser_if, block)
                if not hosted:
                    self.assertIn("Prepare reusable QA environment (self-hosted)", block)
                    self.assertIn("b62_qa_prepare.sh", block)
                self.assertLess(
                    block.index("Cache pinned Playwright Chromium"),
                    block.index("name: Install Chromium system libraries"),
                )
                self.assertLess(
                    block.index("name: Install Chromium system libraries"),
                    block.index("name: Install Chromium browser"),
                )
        self.assertRegex(text, r"(?m)^  pull_request:")
        self.assertRegex(text, r"(?m)^  workflow_dispatch:")
        self.assertRegex(text, r"(?m)^concurrency:")
        self.assertRegex(text, r"(?m)^  cancel-in-progress: true$")


if __name__ == "__main__":
    unittest.main()
