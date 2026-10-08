"""Guard federated documentation navigation without duplicating volatile model facts.

No provider calls, network access, credentials or Production mutations.
"""
from pathlib import Path
from urllib.parse import unquote
import re
import unittest

ROOT = Path(__file__).resolve().parents[3]
HUBS = (
    "docs/common/README.md",
    "docs/lifecycle/README.md",
    "docs/businesses/README.md",
    "docs/models/README.md",
    "docs/history/README.md",
)
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


class DocumentationNavigationHubTests(unittest.TestCase):
    def test_all_hubs_are_index_only(self):
        for name in HUBS:
            with self.subTest(name=name):
                content = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("SCOPE = NAVIGATION_ONLY", content)
                self.assertIn("DOC_STATUS = CANONICAL", content)

    def test_hub_unicode_and_markdown_integrity(self):
        for name in HUBS:
            with self.subTest(name=name):
                content = (ROOT / name).read_text(encoding="utf-8")
                heading = content.splitlines()[0]
                self.assertTrue(any("\uac00" <= c <= "\ud7a3" for c in heading))
                self.assertNotIn("??", content)
                self.assertIn("~~~text", content)
                self.assertEqual(content.count("~~~"), 2)
                self.assertNotIn("\\\\", content[:150])

        root_index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        self.assertIn("\uBB38\uC11C \uD0D0\uC0C9", root_index)
        nav = root_index.split("## Start here", 1)[0]
        self.assertNotIn("??", nav)

    def test_root_links_to_each_hub_once(self):
        content = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        for name in HUBS:
            with self.subTest(name=name):
                rel = name.removeprefix("docs/")
                self.assertEqual(content.count(f"({rel})"), 1)

    def test_hub_links_resolve_to_current_repo_files(self):
        for name in HUBS:
            file = ROOT / name
            for href in LINK.findall(file.read_text(encoding="utf-8")):
                if href.startswith(("https://", "http://", "mailto:", "#")):
                    continue
                path = unquote(href.split("#", 1)[0])
                if not path:
                    continue
                with self.subTest(source=name, destination=href):
                    dest = (file.parent / path).resolve()
                    self.assertTrue(dest.is_relative_to(ROOT.resolve()), f"outside repo: {href}")
                    self.assertTrue(dest.is_file(), f"missing link: {name} -> {href}")

    def test_agents_point_to_single_model_hub(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("(docs/models/README.md)", agents)

    def test_governance_links_back_to_navigation_hubs(self):
        governance = (ROOT / "docs/governance/DOCUMENTATION_AUTHORITY_MODEL.md").read_text(encoding="utf-8")
        for name in HUBS:
            with self.subTest(name=name):
                self.assertIn(f"(../{name.removeprefix('docs/')})", governance)

    def test_model_hub_does_not_duplicate_model_inventory(self):
        content = (ROOT / "docs/models/README.md").read_text(encoding="utf-8").lower()
        for fragment in ("gemini-3.", "gemma-4", "nemotron-3", "model_id ="):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, content)
        self.assertIn("apps/korean-ai-platform/app/pilot/catalog.py", content)
        self.assertIn("model_change_owner_approval_policy.md", content)


if __name__ == "__main__":
    unittest.main()
