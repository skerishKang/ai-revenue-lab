"""B66 documented stage boundaries must stay unambiguous (network-free).

This test protects the owner-approved source-engineering vs interpretation
vs calculation vs PDF rendering distinction. It does not approve a model or
infer customer readiness.
"""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "docs/products/b66/README.md"
FIDELITY = ROOT / "docs/products/b66/SOURCE_TEMPLATE_FIDELITY.md"
PROTOCOL = ROOT / "docs/operations/B14_B66_QUOTE_MODEL_EVALUATION_PROTOCOL.md"
POLICY = ROOT / "docs/operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md"
SECTION = "## Stage ownership — one canonical answer for Sol, B14 and final PDF"
CANONICAL_LINK = "README.md#stage-ownership--one-canonical-answer-for-sol-b14-and-final-pdf"


class B66StageAuthorityContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.product = README.read_text(encoding="utf-8")
        cls.fidelity = FIDELITY.read_text(encoding="utf-8")
        cls.protocol = PROTOCOL.read_text(encoding="utf-8")
        cls.policy = POLICY.read_text(encoding="utf-8")

    def test_one_canonical_product_stage_table(self):
        self.assertEqual(self.product.count(SECTION), 1)
        section = self.product.split(SECTION, 1)[1].split("## Current authority map", 1)[0]
        self.assertIn("| Stage / trigger | Responsible component | Model call contract | Output |", section)
        for stage in ("**A. Source onboarding", "**B1. Repeat quote from natural language",
                      "**B2. Repeat quote from complete structured inputs",
                      "**C. Amounts and tax", "**D. Preview / final downloadable PDF"):
            self.assertEqual(section.count(stage), 1, stage)
        for literal in (
            "REPEAT_PDF_RENDER_PROVIDER_CALLS=0",
            "REPEAT_PDF_RENDER_SOL_CALLS=0",
            "REPEAT_PDF_RENDER_B14_CALLS=0",
            "QUOTE_FACT_INTERPRETATION_B14_CALLS=0_OR_1_IF_REQUESTED",
            "QUOTECORE_MODEL_CALLS=0",
            "CUSTOMER_STRUCTURED_REPEAT:",
            "CUSTOMER_FREEFORM_REPEAT:",
            "ONBOARD_ONCE:",
        ):
            self.assertIn(literal, section)
        self.assertIn("Sol 6.1", section)
        self.assertIn("customer-selected B14", section)
        self.assertIn("zero retry, auto-pick or fallback", section)
        self.assertIn("independent certification", section)

    def test_downstream_docs_reference_single_stage_authority(self):
        self.assertIn(CANONICAL_LINK, self.fidelity)
        self.assertIn("products/b66/README.md#stage-ownership--one-canonical-answer-for-sol-b14-and-final-pdf",
                      self.protocol)
        self.assertIn("model calls", self.protocol)
        self.assertIn("Sol is not invoked per repeat", self.protocol)
        self.assertIn("**B14 does not draw the PDF", self.protocol)
        self.assertIn("does **not** turn Sol or B14 into a per-download PDF renderer",
                      self.fidelity)

    def test_existing_fidelity_execution_contract_stays_explicit(self):
        for expression in (
            "SOURCE_REANALYSIS_PER_REPEAT = 0",
            "CERTIFICATION_PER_QUOTE = 0",
            "QUOTECORE_CALCULATION_AUTHORITY = YES",
            "STRUCTURED_TEMPLATE_RENDER_MODEL_CALLS = 0",
        ):
            self.assertIn(expression, self.fidelity)
        self.assertIn("renderer/converter, not by asking an AI model", self.fidelity)

    def test_existing_model_choice_authority_not_replaced(self):
        for expression in (
            "B66_ROUTE_CHOICE=USER_SELECTED_EXACT_MODEL_ID",
            "B66_AUTOMATIC_MODEL_PICKER=OFF",
            "B66_PROVIDER_ATTEMPTS_MAX=1",
            "B66_RETRY=NO",
            "B66_AUTOMATIC_FALLBACK=NO",
            "B66_MODEL_TASK=document_quote_field_extraction",
        ):
            self.assertIn(expression, self.policy)
        self.assertIn("Owner model policy §0A", self.product)
        self.assertIn("The user can override the prefilled default.", self.policy)

    def test_explicit_multipage_vs_pdf_render_stage(self):
        product_section = self.product.split(SECTION, 1)[1].split("## Current authority map", 1)[0]
        self.assertIn("#3839", product_section)
        self.assertIn("must pass independent certification before", product_section)
        self.assertIn("new PDF pages must not be AI-generated at request time", product_section)


if __name__ == "__main__":
    unittest.main()
