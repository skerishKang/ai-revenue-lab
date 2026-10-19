"""Current independent final-round Gemma4 26B evidence guard."""
from pathlib import Path
import json
import unittest
ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/"B14_FINAL_GEMMA_4_26B_2026-10-09.md"
LEDGER=ROOT/"B14_FINAL_MODEL_EVALUATION_2026-10-09.md"
QUOTAS=ROOT/"GOOGLE_AI_STUDIO_FREE_TIER_QUOTAS_2026-10-09.json"
class Gemma426bTests(unittest.TestCase):
    def test_exact_registered_id_and_new_score(self):
        s=DOC.read_text(encoding="utf-8")
        t=LEDGER.read_text(encoding="utf-8")
        for v in ("gemma-4-26b-a4b-it","8/10","0/10","20,622ms","33,078ms","2,765ms","7,150,000원","NOT_TESTED","Minimal","High"):
            with self.subTest(v=v):self.assertIn(v,s)
        self.assertIn("B14_FINAL_GEMMA_4_26B_2026-10-09.md",t)
        self.assertIn("B14_FINAL_MODEL_EVALUATION_2026-10-09",s)
    def test_free_tier_matches_owner_snapshot(self):
        x=json.loads(QUOTAS.read_text(encoding="utf-8"))
        g=[m for m in x["models"] if m["display_name"]=="Gemma 4 26B"]
        self.assertEqual(len(g),1)
        self.assertEqual((g[0]["rpm"],g[0]["input_tpm"],g[0]["rpd"]),(30,16000,14400))
    def test_high_not_mislabeled_general_intelligence(self):
        s=DOC.read_text(encoding="utf-8")
        self.assertIn("JSONDecodeError",s)
        self.assertIn("length",s)
        self.assertIn("이번 견적",s)
        self.assertIn("공식 최대 출력 UNKNOWN",LEDGER.read_text(encoding="utf-8"))
if __name__=="__main__":unittest.main()
