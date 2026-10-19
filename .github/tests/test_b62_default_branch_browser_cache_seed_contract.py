"""Keep the default-branch browser cache seed isolated and compatible."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


class BrowserCacheSeedContract(unittest.TestCase):
    def test_seed_is_dispatch_only_main_and_matches_pr_consumers(self):
        text = (WORKFLOWS / "b62-browser-cache-seed.yml").read_text(encoding="utf-8")
        self.assertIn("  workflow_dispatch:", text)
        self.assertNotIn("  pull_request:", text)
        self.assertNotIn("  push:", text)
        self.assertIn("github.ref == 'refs/heads/main'", text)
        self.assertIn("runs-on: ubuntu-24.04", text)
        self.assertIn("permissions:\n  contents: read", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("uses: actions/cache@v4", text)
        self.assertIn("uvx --from 'playwright==1.55.0' playwright install chromium", text)
        self.assertNotIn("secrets.", text)
        self.assertNotIn("wrangler", text.lower())
        seed_key = next(line.strip() for line in text.splitlines() if line.strip().startswith("key: "))
        unified = (WORKFLOWS / "b62-browser-qa-unified.yml").read_text(
            encoding="utf-8"
        )
        self.assertEqual(unified.count(seed_key), 16)
        self.assertEqual(unified.count("Cache pinned Playwright Chromium"), 16)


if __name__ == "__main__":
    unittest.main()