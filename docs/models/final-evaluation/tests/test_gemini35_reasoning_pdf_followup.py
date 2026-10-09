"""Document consistency for Gemini 3.5 post-benchmark reasoning and actual PDF evidence."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
FOLLOW=ROOT/"B14_FINAL_GEMINI_3_5_REASONING_AND_PDF_2026-10-09.md"
DETAIL=ROOT/"B14_FINAL_GEMINI_3_5_FLASH_LITE_2026-10-09.md"
LEDGER=ROOT/"B14_FINAL_MODEL_EVALUATION_2026-10-09.md"

class Gemini35ReasoningPdfFollowup(unittest.TestCase):
    def test_documented_same_model_and_final_round(self):
        for path in (FOLLOW, DETAIL, LEDGER):
            self.assertIn("B14_FINAL_MODEL_EVALUATION_2026-10-09",path.read_text(encoding="utf-8"))
        self.assertIn(FOLLOW.name,DETAIL.read_text(encoding="utf-8"))
        self.assertIn(FOLLOW.name,LEDGER.read_text(encoding="utf-8"))
    def test_reasoning_has_no_invented_accuracy_or_speed_results(self):
        text=FOLLOW.read_text(encoding="utf-8")
        self.assertIn("Please pass a valid API key",text)
        self.assertIn("HTTP 400",text)
        self.assertIn("측정 불가",text)
        self.assertIn("NOT_TESTED",text)
        for level in ("minimal","low","medium","high"):
            self.assertIn(level,text)
    def test_pdf_math_and_pagination_are_precisely_recorded(self):
        text=FOLLOW.read_text(encoding="utf-8")
        for value in ("500,000원","50,000원","550,000원","6,500,000원","650,000원","7,150,000원","12/12","PDF"):
            self.assertIn(value,text)
        self.assertIn("하단 문구",text)
        self.assertIn("2페이지",text)
        self.assertIn("IN_PROGRESS",text)
    def test_extra_failures_not_substituted_for_initial_sample(self):
        text=FOLLOW.read_text(encoding="utf-8")
        self.assertIn("두 차례",text)
        self.assertIn("프로젝트명",text)
        self.assertIn("10/10",text)
if __name__=="__main__":
    unittest.main()
