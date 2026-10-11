"""Document-level assertions for independent Poolside Laguna S 2.1 final round."""
from pathlib import Path
import unittest
BASE=Path(__file__).resolve().parents[1]
REPORT=BASE/"B14_FINAL_POOLSIDE_LAGUNA_S_2_1_2026-10-09.md"
MASTER=BASE/"B14_FINAL_MODEL_EVALUATION_2026-10-09.md"
class PoolsideLagunaFinalTests(unittest.TestCase):
    def test_exact_model_direct_provider_not_kilo(self):
        s=REPORT.read_text(encoding="utf-8")
        for term in ("poolside/laguna-s-2.1","inference.poolside.ai","Kilo Gateway Laguna","118B","8B","262,144","32,768"):
            with self.subTest(term=term):self.assertIn(term,s)
        self.assertIn(REPORT.name,MASTER.read_text(encoding="utf-8"))
    def test_direct_accuracy_separately_from_b14_transport(self):
        s=REPORT.read_text(encoding="utf-8")
        for term in ("30회","30/30","9/10","8/10","9/10","HTTP504","메타데이터"):
            with self.subTest(term=term):self.assertIn(term,s)
        self.assertIn("IN_PROGRESS",s)
    def test_thinking_both_modes_and_uncertain_quota(self):
        s=REPORT.read_text(encoding="utf-8")
        for term in ("enable_thinking=false","enable_thinking=true","4.63초","9.56초","UNKNOWN","RPM","TPM","RPD"):
            with self.subTest(term=term):self.assertIn(term,s)
    def test_real_pdf_math_recorded_but_customer_e2e_unverified(self):
        s=REPORT.read_text(encoding="utf-8")
        for term in ("12/12","6,500,000원","650,000원","7,150,000원","2","NOT_TESTED"):
            with self.subTest(term=term):self.assertIn(term,s)
if __name__=="__main__":unittest.main()
