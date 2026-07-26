from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "businesses.js"


class BusinessRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = REGISTRY.read_text(encoding="utf-8")

    def business_block(self, number: int) -> str:
        match = re.search(
            rf"  \{{\n    number: {number},\n(?P<body>.*?)\n  \}}(?:,|\n)",
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(match, f"Business {number} entry")
        return match.group(0)

    def test_registry_has_exact_ordered_unique_numbers_one_through_fifteen(self) -> None:
        numbers = [
            int(value)
            for value in re.findall(r"^\s+number:\s*(\d+),$", self.script, re.MULTILINE)
        ]
        self.assertEqual(numbers, list(range(1, 16)))
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_reserved_slots_seven_through_twelve_are_removed(self) -> None:
        for number in range(7, 13):
            self.assertNotIn(f'reserved-{number:02d}', self.script)

    def test_businesses_seven_through_twelve_use_canonical_mappings(self) -> None:
        expected = {
            7: ("personal-meaning-map", "Personal Meaning Map", "개인 의미 지도", 166, 174),
            8: ("family-newspaper", "Family Newspaper", "우리 가족 신문", 168, 176),
            9: ("personalized-childrens-story", "Personalized Children\\u2019s Story", "우리 아이 이야기", 170, 175),
            10: ("fan-magazine", "Fan Magazine", "나만의 팬 매거진", 171, 177),
            11: ("language-learning-magazine", "Language Learning Magazine", "나의 언어학습 매거진", 172, 179),
            12: ("creator-mini-media", "Creator Mini-Media", "크리에이터 미니미디어", 173, 178),
        }
        for number, (slug, title, korean_title, issue, pull_request) in expected.items():
            block = self.business_block(number)
            self.assertIn(f'slug: "{slug}"', block)
            self.assertIn(f'title: "{title}"', block)
            self.assertIn(f'koreanTitle: "{korean_title}"', block)
            self.assertIn(f'/issues/{issue}"', block)
            self.assertIn(f'/pull/{pull_request}"', block)

    def test_business_nine_records_ui_approval_without_claiming_merge(self) -> None:
        block = self.business_block(9)
        self.assertIn('state: "review"', block)
        self.assertIn('surfaceType: "Approved visual reference in Draft PR"', block)
        self.assertIn('githubLabel: "UI_APPROVED · Draft PR #175"', block)
        self.assertIn("Draft, OPEN, and unmerged", block)
        self.assertIn("pending separate Ready/merge authorization", block)
        self.assertIn("Phase 2 UX only through a separately authorized issue", block)
        self.assertNotIn("obtain exact-head CTO approval", block)

    def test_business_fifteen_remains_reserved(self) -> None:
        block = self.business_block(15)
        self.assertIn('slug: "unassigned-15"', block)
        self.assertIn('state: "reserved"', block)
        self.assertIn('lifecycle: "reserved"', block)


if __name__ == "__main__":
    unittest.main()
