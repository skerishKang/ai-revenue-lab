from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "b66_cgi_final_handoff_smoke.py"
SPEC = importlib.util.spec_from_file_location("b66_cgi_final_handoff_smoke", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class FinalHandoffSmokeContractTests(unittest.TestCase):
    def test_exact_three_interpret_budget(self):
        self.assertEqual(module.MAX_INTERPRET_POSTS, 3)
        self.assertEqual(module.RETRY, 0)
        self.assertEqual(module.FALLBACK, 0)

    def test_exact_acceptance_inputs(self):
        self.assertEqual(
            module.COMPLETE_TEXT,
            "대한건설에 배관 100미터, 미터당 18000원, 부가세 별도",
        )
        self.assertEqual(
            module.PARTIAL_TEXT,
            "대한건설에 배관 100미터, 부가세 별도",
        )
        self.assertEqual(module.FOLLOWUP_TEXT, "미터당 18000원")

    def test_provider_host_detection_is_closed_to_real_provider_hosts(self):
        self.assertTrue(module._is_direct_provider("https://api.kilo.ai/v1/chat"))
        self.assertTrue(module._is_direct_provider("https://openrouter.ai/api/v1/chat"))
        self.assertFalse(
            module._is_direct_provider(
                "https://quick-quote-kr.pages.dev/api/padiem/b66/quote/interpret"
            )
        )

    def test_target_is_standalone_b66_production(self):
        self.assertEqual(module.TARGET_URL, "https://quick-quote-kr.pages.dev/")
        self.assertEqual(
            module.INTERPRET_PATH,
            "/api/padiem/b66/quote/interpret",
        )


if __name__ == "__main__":
    unittest.main()
