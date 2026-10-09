"""Guard warm-cache configuration for independent B62 browser QA workflows."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / ".github" / "workflows"


class B62BrowserCacheContractTests(unittest.TestCase):
    def test_pinned_browser_workflows_have_safe_reusable_caches(self):
        eligible = []
        for file in sorted(FOLDER.glob("b62-*.yml")):
            if file.name == "b62-browser-qa-unified.yml":
                continue  # The dispatcher contains all 16 original job steps.
            text = file.read_text(encoding="utf-8")
            if not (
                "uses: astral-sh/setup-uv" in text
                and "playwright==1.55.0" in text
                and "playwright install --with-deps chromium" in text
            ):
                continue
            eligible.append(file.name)
            with self.subTest(workflow=file.name):
                self.assertIn("enable-cache: true", text)
                self.assertIn(
                    "cache-dependency-glob: apps/padiem-chat/uv.lock", text
                )
                self.assertEqual(text.count("Cache pinned Playwright Chromium"), 1)
                self.assertEqual(text.count("actions/cache@v4"), 1)
                self.assertIn("path: ~/.cache/ms-playwright", text)
                self.assertIn("key: b62-playwright-1.55.0-", text)
                self.assertIn("runner.os", text)
                self.assertIn("runner.arch", text)
                self.assertLess(
                    text.index("Cache pinned Playwright Chromium"),
                    text.index("name: Install Chromium runtime"),
                )
                self.assertRegex(text, r"(?m)^  workflow_dispatch:")
                self.assertRegex(text, r"(?m)^concurrency:")
                self.assertRegex(text, r"(?m)^  cancel-in-progress: true$")
        self.assertGreaterEqual(len(eligible), 16)


if __name__ == "__main__":
    unittest.main()