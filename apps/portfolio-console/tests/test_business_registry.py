from __future__ import annotations
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "business-manifest.js"
IDENTITY_CORE = ROOT / "business-identity-core.js"

# Numbers that must always remain registered through the B59 era, with B56 as
# the single intentional historical gap. Later valid sparse registrations
# (B60+) may extend the registry above this floor, but must never duplicate,
# reorder, or insert a new number at or below B59.
REQUIRED_NUMBERS_THROUGH_59 = [*range(1, 56), 57, 58, 59]


class BusinessRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = MANIFEST.read_text(encoding="utf-8")
        cls.core_script = IDENTITY_CORE.read_text(encoding="utf-8")

    def business_block(self, number: int) -> str:
        match = re.search(
            rf"\bn:\s*{number},(?P<body>.*?)\)\s*[,\)]",
            self.script,
            re.DOTALL,
        )
        self.assertIsNotNone(match, f"Business {number} entry not found in manifest")
        return match.group(0)

    def core_block(self, number: int) -> str:
        match = re.search(rf"\bn:\s*{number},(?P<body>[^}}]*)\}}", self.core_script)
        self.assertIsNotNone(match, f"Business {number} entry not found in identity core")
        return match.group(0)

    def test_registry_has_exact_ordered_unique_numbers_through_fiftynine_with_gap_56(self) -> None:
        numbers = [int(v) for v in re.findall(r"\bn:\s*(\d+),", self.script)]
        # Ordered and unique: strictly increasing, no duplicates.
        self.assertEqual(numbers, sorted(numbers))
        self.assertEqual(len(numbers), len(set(numbers)))
        # B56 remains the single intentional gap.
        self.assertNotIn(56, numbers)
        # Every historical/canonical number through B59 is still registered.
        self.assertTrue(set(REQUIRED_NUMBERS_THROUGH_59).issubset(set(numbers)))
        # Only later sparse registrations (B60+) may extend the set beyond the
        # required baseline; nothing new may appear at or below B59.
        for number in numbers:
            if number not in REQUIRED_NUMBERS_THROUGH_59:
                self.assertGreater(number, 59, f"unexpected non-sparse Business number {number}")

    def test_reserved_slots_seven_through_twelve_exist_as_canonical(self) -> None:
        # B7-B12 were promoted from PROPOSED to CANONICAL in the 2026-08-15
        # final-surface wiring (PR #646); the authority must stay CANONICAL.
        for number in range(7, 13):
            block = self.business_block(number)
            self.assertIn("CANONICAL", block)

    def test_businesses_seven_through_twelve_use_correct_mappings(self) -> None:
        expected = {
            7: ("personal-meaning-map", "Personal Meaning Map", "개인 의미 지도"),
            8: ("family-newspaper", "Family Newspaper", "우리 가족 신문"),
            9: ("personalized-childrens-story", "Personalized Children’s Story", "우리 아이 이야기"),
            10: ("fan-magazine", "Fan Magazine", "나만의 팬 매거진"),
            11: ("language-learning-magazine", "Language Learning Magazine", "나의 언어학습 매거진"),
            12: ("creator-mini-media", "Creator Mini-Media", "크리에이터 미니미디어"),
        }
        for number, (slug, title, korean_title) in expected.items():
            block = self.business_block(number)
            self.assertIn(f's:"{slug}"', block)
            self.assertIn(f't:"{title}"', block)
            self.assertIn(f'k:"{korean_title}"', block)
            self.assertIn('l:"visual_reference"', block)

    def test_business_nine_records_ui_approval(self) -> None:
        core = self.core_block(9)
        self.assertIn('ui:"UI_APPROVED"', core)
        block = self.business_block(9)
        self.assertIn('st:"review"', block)

    def test_identity_core_matches_manifest_number_contract(self) -> None:
        manifest_numbers = [int(v) for v in re.findall(r"\bn:\s*(\d+),", self.script)]
        numbers = [int(v) for v in re.findall(r"\bn:\s*(\d+),", self.core_script)]
        # Identity core and manifest must agree on the exact same ordered
        # number sequence, so a future sparse registration cannot land in one
        # source but not the other.
        self.assertEqual(numbers, manifest_numbers)
        self.assertNotIn(56, numbers)

    def test_manifest_defines_no_phase_status_literals_single_source(self) -> None:
        for literal in ('ui:"', 'ux:"', 'be:"'):
            self.assertNotIn(literal, self.script, f"manifest must not define phase status literal {literal}")
        array_section = self.script.split("window.ARL_MANIFEST = [", 1)[1]
        for value in ("UI_APPROVED", "BLOCKED_BY_UI", "IMPLEMENTED", "FROZEN", "DECISION_PENDING", "NOT_STARTED"):
            self.assertNotIn(value, array_section, f"manifest entries must not hardcode phase status value {value}")

    def test_business_fifteen_exists_as_proposed(self) -> None:
        block = self.business_block(15)
        self.assertIn('"global-ai-newsroom"', block)
        self.assertIn('l:"visual_reference"', block)

    def test_business_38_is_ai_exercise_coach(self) -> None:
        block = self.business_block(38)
        self.assertIn('s:"ai-exercise-coach"', block)
        self.assertIn('t:"AI Exercise Coach"', block)
        self.assertIn('k:"AI 운동 코치"', block)
        self.assertIn('w:"reference/business-38-ai-exercise-coach-v1/"', block)
        self.assertNotIn('AI Learning Tutor', block)

    def test_business_54_is_korean_ai_code_agent(self) -> None:
        block = self.business_block(54)
        self.assertIn('s:"korean-ai-code-agent"', block)
        self.assertIn('t:"Korean AI Code Agent"', block)
        self.assertIn('k:"한국형 AI 코드 에이전트"', block)
        self.assertIn('w:"apps/korean-ai-code-agent/"', block)
        self.assertNotIn('AI Model Router', block)

    def test_businesses_57_58_59_exist(self) -> None:
        expected = {
            57: "classic-literature-translation-studio",
            58: "personal-writing-voice-studio",
            59: "living-archive",
        }
        for number, slug in expected.items():
            self.assertIn(f's:"{slug}"', self.business_block(number))


if __name__ == "__main__":
    unittest.main()
