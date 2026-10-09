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
        pr_workflows = []
        for file in WORKFLOWS.glob("b62-*.yml"):
            if file.name in ("b62-browser-cache-seed.yml", "b62-browser-qa-unified.yml"):
                continue
            data = file.read_text(encoding="utf-8")
            if "Cache pinned Playwright Chromium" in data:
                pr_workflows.append(file)
                self.assertIn(seed_key, data, file.name)
        self.assertEqual(len(pr_workflows), 16)


if __name__ == "__main__":
    unittest.main()