from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "business-manifest.js"
PHASE_CORE = ROOT / "business-identity-core.js"


class B64ManifestRegistrationTest(unittest.TestCase):
    def test_b21_founder_strategy_letter_is_preserved(self):
        text = MANIFEST.read_text(encoding="utf-8")
        self.assertIn('n:21, s:"founder-strategy-letter"', text)
        self.assertNotIn('n:21, s:"ai-reward-router"', text)

    def test_b64_reward_router_is_registered_once(self):
        text = MANIFEST.read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r'n:64,\s*s:"ai-reward-router"', text)), 1)
        self.assertIn('t:"AI Reward Router"', text)
        self.assertIn('l:"incubation"', text)
        self.assertIn('a:NA.PROPOSED', text)

    def test_b64_phase_authority_is_explicit(self):
        text = PHASE_CORE.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            r'\{ n:64,\s*ui:"IN_PROGRESS",\s*ux:"IN_PROGRESS",\s*be:"IN_PROGRESS" \}',
        )

    def test_sparse_post_b60_registration_is_documented(self):
        manifest = MANIFEST.read_text(encoding="utf-8")
        phase_core = PHASE_CORE.read_text(encoding="utf-8")
        self.assertIn("B61-B63 are not yet represented in this manifest", manifest)
        self.assertIn("B61-B63 are not yet", phase_core)


if __name__ == "__main__":
    unittest.main()
