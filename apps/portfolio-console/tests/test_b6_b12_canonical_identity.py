from __future__ import annotations

import re
import unittest
from pathlib import Path


PORTFOLIO_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PORTFOLIO_DIR.parents[1]
MANIFEST = PORTFOLIO_DIR / "business-manifest.js"
REGISTRY = REPO_ROOT / "docs" / "portfolio" / "BUSINESS_REGISTRY.md"
APPS_README = REPO_ROOT / "apps" / "README.md"


EXPECTED = {
    6: ("world-feed", "World Feed", "apps/world-feed/", "research"),
    7: ("personal-meaning-map", "Personal Meaning Map", "reference/business-07-personal-meaning-map-v1/", "visual_reference"),
    8: ("family-newspaper", "Family Newspaper", "reference/business-08-family-newspaper-v1/", "visual_reference"),
    9: ("personalized-childrens-story", "Personalized Children’s Story", "reference/business-09-personalized-childrens-story-v1/", "visual_reference"),
    10: ("fan-magazine", "Fan Magazine", "reference/business-10-fan-magazine-v1/", "visual_reference"),
    11: ("language-learning-magazine", "Language Learning Magazine", "reference/business-11-language-learning-magazine-v1/", "visual_reference"),
    12: ("creator-mini-media", "Creator Mini-Media", "reference/business-12-creator-mini-media-v1/", "visual_reference"),
}


class B6B12CanonicalIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = MANIFEST.read_text(encoding="utf-8")
        cls.registry = REGISTRY.read_text(encoding="utf-8")
        cls.apps_readme = APPS_README.read_text(encoding="utf-8")

    def manifest_entry(self, number: int) -> str:
        match = re.search(rf'identity\(\{{[^\n]*n:{number},[^\n]*\}}\)', self.manifest)
        self.assertIsNotNone(match, f"missing manifest entry B{number}")
        return match.group(0)

    def test_b6_b12_are_ordered_and_canonical(self) -> None:
        positions = []
        for number, (slug, title, workspace, lifecycle) in EXPECTED.items():
            entry = self.manifest_entry(number)
            positions.append(self.manifest.index(entry))
            self.assertIn(f's:"{slug}"', entry)
            self.assertIn(f't:"{title}"', entry)
            self.assertIn('a:NA.CANONICAL', entry)
            self.assertIn(f'l:"{lifecycle}"', entry)
            self.assertIn('st:"review"', entry)
            self.assertIn(f'w:"{workspace}"', entry)
            self.assertNotIn('l:"active"', entry)
            self.assertNotIn('st:"running"', entry)
        self.assertEqual(positions, sorted(positions))

    def test_b6_stable_slug_workspace_and_positioning_boundary(self) -> None:
        entry = self.manifest_entry(6)
        self.assertIn('s:"world-feed"', entry)
        self.assertIn('w:"apps/world-feed/"', entry)
        self.assertIn('l:"research"', entry)
        self.assertIn("Personal World Discovery", self.apps_readme)
        self.assertIn("current narrowed commercial positioning", self.apps_readme)

    def test_b7_b12_keep_reference_workspaces_without_duplicate_apps_placeholders(self) -> None:
        for number, (_, _, workspace, _) in EXPECTED.items():
            if number == 6:
                continue
            entry = self.manifest_entry(number)
            self.assertIn(f'w:"{workspace}"', entry)
            self.assertNotIn(f'w:"apps/', entry)

    def test_registry_and_manifest_agree_on_canonical_number_authority(self) -> None:
        for number, (slug, _, _, _) in EXPECTED.items():
            self.assertRegex(
                self.registry,
                re.compile(rf'\|\s*{number}\s*\|\s*`{re.escape(slug)}`\s*\|[^\n]*\|\s*canonical\s*\|'),
            )
            self.assertIn('a:NA.CANONICAL', self.manifest_entry(number))


if __name__ == "__main__":
    unittest.main()
