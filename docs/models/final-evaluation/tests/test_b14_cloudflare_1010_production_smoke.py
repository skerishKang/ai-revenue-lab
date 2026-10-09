"""B14 Cloudflare Error 1010 and live Mercury/Atria proof: offline-documentary guards."""
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
DIR=Path(__file__).resolve().parents[1]
LEDGER=DIR/"B14_FINAL_MODEL_EVALUATION_2026-10-09.md"
MERCURY=DIR/"B14_FINAL_MERCURY_2_5_2026-10-09.md"
ATRIA=DIR/"B14_FINAL_ATRIA_DAWN_PREVIEW_2026-10-09.md"
OPS=ROOT/"docs/operations/B14_CLOUDFLARE_1010_PRODUCTION_SMOKE_2026-10-09.md"
HARNESS=ROOT/".github/scripts/b66_quote_model_benchmark.py"


class B14Live1010OutcomeGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger=LEDGER.read_text(encoding="utf-8")
        cls.mercury=MERCURY.read_text(encoding="utf-8")
        cls.atria=ATRIA.read_text(encoding="utf-8")
        cls.ops=OPS.read_text(encoding="utf-8")
        cls.harness=HARNESS.read_text(encoding="utf-8")

    def test_known_client_identifier_stays_in_canonical_preflight(self):
        self.assertIn('"User-Agent": "PADIEM-Source-Eval/1.0"',self.harness)
        self.assertIn("error_code=1010",self.ops)
        self.assertIn("browser_signature_banned",self.ops)
        self.assertIn("Cloudflare's Error 1010",self.ops)
        self.assertIn("WAF policies unchanged",self.ops)

    def test_403_not_misassigned_to_upstream(self):
        self.assertIn("Python-urllib user agent: HTTP403",self.ops)
        self.assertIn("HTTP200",self.ops)
        self.assertIn("not",self.ops.lower())
        self.assertIn("Agnes 3.0 Flash B14 HTTP429 remains a separate",self.ops)

    def test_mercury_production_standard_quote_proven_only_sampled(self):
        for x in ("PRODUCTION_B14_QUOTE_STRICT_PASS","2,532ms","3,563ms",
                  "QKR-002","엄격 견적 정답 PASS","attempt 1","fallback false"):
            self.assertIn(x,self.mercury)
        self.assertIn("F4_B14_HTTP200_10/10 / F5_STRICT_8/10",self.ledger)
        self.assertIn("F6_NOT_TESTED",self.mercury)

    def test_atria_canonical_timeout_is_distinct_from_preview_pass(self):
        for x in ("PRODUCTION_B14_STREAM_PREVIEW_QUOTE_PASS","6,078ms","10,563ms",
                  "50,640ms","43,531ms","upstream_timeout","Preview-only",
                  "엄격 견적 PASS","NOT_TESTED"):
            self.assertIn(x,self.atria)
        self.assertIn("STREAM_PREVIEW_QKR001_STRICT_PASS",self.ledger)
        self.assertIn("일반 QKR-001 HTTP504",self.ledger)
        self.assertNotIn("FULL_FINAL_PASS",self.atria)

    def test_operator_report_is_bounded_no_change(self):
        self.assertIn("no canonical backend change is necessary",self.ops)
        self.assertIn("no secret mutation",self.ops)
        self.assertIn("no live deploy",self.ops)
        self.assertIn("not full 10-case confidence",self.ops)


if __name__=="__main__":
    unittest.main()
