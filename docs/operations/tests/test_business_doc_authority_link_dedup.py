"""Keep business-specific boundaries separate from shared platform governance.

This is a static document test; it performs no network, Provider or Production actions.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCS = (
    "apps/korean-ai-code-agent/README.md",
    "docs/products/padiem-sidecar/README.md",
    "docs/products/b66/README.md",
)
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


class BusinessDocumentationAuthorityTests(unittest.TestCase):
    def test_businesses_link_to_common_and_lifecycle_authority(self):
        for name in DOCS:
            content = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertIn("common/README.md", content)
                self.assertIn("lifecycle/README.md", content)

    def test_shared_vertical_stack_is_not_copied_into_business_diagrams(self):
        claw = (ROOT / DOCS[0]).read_text(encoding="utf-8")
        sidecar = (ROOT / DOCS[1]).read_text(encoding="utf-8")
        for name, content in ((DOCS[0], claw), (DOCS[1], sidecar)):
            with self.subTest(name=name):
                self.assertIn("PADIEM_AI_VERTICAL_STACK.md", content)
                self.assertNotIn("Provider / Model\\n", content)
        self.assertIn("B54 task / run / repository / workspace adapter", claw)
        self.assertIn("IP-SIDECAR embedded shell and context boundary", sidecar)

    def test_product_unique_gates_and_safety_stay_local(self):
        claw = (ROOT / DOCS[0]).read_text(encoding="utf-8")
        sidecar = (ROOT / DOCS[1]).read_text(encoding="utf-8")
        quote = (ROOT / DOCS[2]).read_text(encoding="utf-8")
        self.assertIn("git mutation     = off by default", claw)
        self.assertIn("waiting_approval", claw)
        self.assertIn("PRODUCT_SPECIFIC_DOMAIN_SEMANTICS_STAY_IN_ADAPTER = YES", sidecar)
        self.assertIn("PRODUCTION_ACTIVATION = NO", sidecar)
        self.assertIn("QuoteCore remains the sole calculation authority", quote)
        self.assertIn("CUSTOMER_READY = NO", quote)

    def test_new_documentation_links_exist_in_repository(self):
        for name in DOCS:
            doc = ROOT / name
            links = LINK.findall(doc.read_text(encoding="utf-8"))
            self.assertGreater(len(links), 0, f"no links parsed in {name}")
            for href in links:
                if href.startswith(("https://", "http://", "mailto:", "#")):
                    continue
                target = href.split("#", 1)[0]
                if not target:
                    continue
                with self.subTest(source=name, target=href):
                    self.assertTrue((doc.parent / target).resolve().is_file())


if __name__ == "__main__":
    unittest.main()
