from __future__ import annotations
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "business-manifest.js"


class BusinessRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = MANIFEST.read_text(encoding="utf-8")

    def business_block(self, number: int) -> str:
        match = re.search(
            rf"\bn:\s*{number},(?P<body>.*?)\)\s*[,\)]",
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(match, f"Business {number} entry not found in manifest")
        return match.group(0)

    def test_registry_has_exact_ordered_unique_numbers_one_through_fiftyfive(self) -> None:
        numbers = [int(v) for v in re.findall(r"\bn:\s*(\d+),", self.script)]
        self.assertGreaterEqual(len(numbers), 55)
        self.assertEqual(numbers, list(range(1, 56)))
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_reserved_slots_seven_through_twelve_exist_as_proposed(self) -> None:
        for number in range(7, 13):
            block = self.business_block(number)
            self.assertIn("PROPOSED", block)

    def test_businesses_seven_through_twelve_use_correct_mappings(self) -> None:
        expected = {
            7: ("personal-meaning-map", "Personal Meaning Map", "개인 의미 지도", "visual_reference"),
            8: ("family-newspaper", "Family Newspaper", "우리 가족 신문", "visual_reference"),
            9: ("personalized-childrens-story", r"Personalized Children\u2019s Story", "우리 아이 이야기", "visual_reference"),
            10: ("fan-magazine", "Fan Magazine", "나만의 팬 매거진", "visual_reference"),
            11: ("language-learning-magazine", "Language Learning Magazine", "나의 언어학습 매거진", "visual_reference"),
            12: ("creator-mini-media", "Creator Mini-Media", "크리에이터 미니미디어", "visual_reference"),
        }
        for number, (slug, title, korean_title, lifecycle) in expected.items():
            block = self.business_block(number)
            self.assertIn(f's:"{slug}"', block)
            self.assertIn(f't:"{title}"', block)
            self.assertIn(f'k:"{korean_title}"', block)

    def test_business_nine_records_ui_approval(self) -> None:
        block = self.business_block(9)
        self.assertIn('ui:"UI_APPROVED"', block)
        self.assertIn('st:"review"', block)

    def test_business_fifteen_exists_as_proposed(self) -> None:
        block = self.business_block(15)
        self.assertIn('"global-ai-newsroom"', block)
        self.assertIn('l:"visual_reference"', block)


if __name__ == "__main__":
    unittest.main()
