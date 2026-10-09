"""Focused contract for B14 model-evaluation document and relevant reporting rule."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs/operations/B14_MODEL_SELECTION_AND_EVALUATION_STANDARD_2026-10-09.md"

class ModelDocumentationScopeTests(unittest.TestCase):
    def test_model_selection_report_is_discoverable(self):
        self.assertTrue(DOC.is_file())
        for path in (
            "AGENTS.md",
            "docs/models/README.md",
            "docs/operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md",
            "docs/operations/B14_B66_QUOTE_MODEL_EVALUATION_PROTOCOL.md",
        ):
            with self.subTest(path=path):
                self.assertIn(DOC.name, (ROOT / path).read_text(encoding="utf-8"))

    def test_exact_nine_real_test_summary_and_step5(self):
        text=DOC.read_text(encoding="utf-8")
        for expected in (
            "41개", "7/10", "2/3", "1/3", "0/3", "9개", "StepFun Step 5",
            "RPM", "TPM", "RPD", "65,536", "4,096",
            "모델", "Poolside", "QuoteCore",
        ):
            with self.subTest(token=expected):
                self.assertIn(expected,text)
        self.assertIn("**미확인**",text)
        self.assertIn("PDF",text)

    def test_workflow_reporting_focus_no_offtopic_lectures(self):
        for path in ("AGENTS.md",
                     "docs/operations/AI_DEVELOPMENT_OPERATING_POLICY.md",
                     "docs/governance/AI_OPERATING_MODEL.md",
                     "docs/operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md"):
            s=(ROOT/path).read_text(encoding="utf-8").lower()
            with self.subTest(path=path):
                self.assertIn("unsolicited",s)
                self.assertIn("privacy",s)

    def test_old_registry_drift_no_longer_reported_as_current(self):
        text=(ROOT / "docs/operations/B14_B66_QUOTE_MODEL_EVALUATION_PROTOCOL.md").read_text(encoding="utf-8")
        self.assertIn("11 served IDs against nine", text)
        self.assertIn("9/9 MATCH", text)
        self.assertIn("41 total", text)
        self.assertNotIn("Actual inference quality per model: NOT TESTED",text)

if __name__=="__main__":
    unittest.main()
