"""Validate the independent SenseNova 6.8 final-round evidence document (no live API)."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/"B14_FINAL_SENSENOVA_6_8_FLASH_LITE_2026-10-09.md"
LEDGER=ROOT/"B14_FINAL_MODEL_EVALUATION_2026-10-09.md"
class SenseNova68IndependentFinalEval(unittest.TestCase):
 def test_provider_model_source_and_spec(self):
  text=DOC.read_text(encoding="utf-8")
  for term in ("sensenova/sensenova-6.8-flash-lite","token.sensenova.ai","262,144","65,536","이미지","reasoning_effort"):
   with self.subTest(term=term):self.assertIn(term,text)
 def test_actual_10_case_route_and_direct_accuracy(self):
  text=DOC.read_text(encoding="utf-8")
  self.assertIn("10/10",text)
  self.assertIn("7,125ms",text)
  self.assertIn("5,233ms",text)
  self.assertIn("B14_FINAL_MODEL_EVALUATION_2026-10-09",text)
 def test_four_reasoning_efforts_both_usage_and_accuracy(self):
  text=DOC.read_text(encoding="utf-8")
  for effort,ms,tokens in (("none","2,633","428"),("low","6,528","832"),("medium","6,278","795"),("high","6,503","812")):
   with self.subTest(level=effort):
    self.assertIn(effort,text)
    self.assertIn(ms,text)
    self.assertIn(tokens,text)
  self.assertIn("40건",text)
  self.assertIn("10/10",text)
 def test_pdf_and_unknown_quota_are_honest(self):
  text=DOC.read_text(encoding="utf-8")
  for term in ("12/12","6,500,000원","650,000원","7,150,000원","2페이지","NOT_TESTED","UNKNOWN"):
   with self.subTest(term=term):self.assertIn(term,text)
 def test_ledger_linked_not_historical_score(self):
  report=DOC.read_text(encoding="utf-8")
  ledger=LEDGER.read_text(encoding="utf-8")
  self.assertIn(DOC.name,ledger)
  self.assertIn("sensenova/sensenova-6.8-flash-lite",ledger)
  self.assertIn("제품 최종 승인",report)
if __name__=="__main__":unittest.main()
