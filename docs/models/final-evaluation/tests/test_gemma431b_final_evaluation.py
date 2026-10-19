"""Gemma 4 31B isolated final evaluation record guard."""
from pathlib import Path
import unittest,json
ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/"B14_FINAL_GEMMA_4_31B_2026-10-09.md"
MASTER=ROOT/"B14_FINAL_MODEL_EVALUATION_2026-10-09.md"
QUOTA=ROOT/"GOOGLE_AI_STUDIO_FREE_TIER_QUOTAS_2026-10-09.json"
class Gemma431bFinalDocumentTests(unittest.TestCase):
    def test_model_identity_and_verified_metadata(self):
        s=REPORT.read_text(encoding="utf-8")
        for k in ("gemma-4-31b-it","30.7B","262,144","32,768","Minimal","High","1.0","0.95","64"):
            with self.subTest(k=k):self.assertIn(k,s)
    def test_two_separate_extraction_grades(self):
        s=REPORT.read_text(encoding="utf-8")
        self.assertIn("엄격 원본",s)
        self.assertIn("코드블록 제거",s)
        self.assertIn("견적",s)
        self.assertIn("HTTP 504",s)
    def test_free_quota_owner_source(self):
        j=json.loads(QUOTA.read_text(encoding="utf-8"))
        row=next(x for x in j["models"] if x["display_name"]=="Gemma 4 31B")
        self.assertEqual((row["rpm"],row["input_tpm"],row["rpd"]),(30,16000,14400))
        self.assertIn("16,000",REPORT.read_text(encoding="utf-8"))
    def test_isolated_final_ledger(self):
        self.assertIn(REPORT.name,MASTER.read_text(encoding="utf-8"))
        self.assertIn("B14_FINAL_MODEL_EVALUATION_2026-10-09",REPORT.read_text(encoding="utf-8"))
        self.assertIn("IN_PROGRESS",REPORT.read_text(encoding="utf-8"))
if __name__=="__main__":unittest.main()
