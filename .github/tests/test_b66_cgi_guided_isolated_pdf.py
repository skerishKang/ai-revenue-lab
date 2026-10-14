"""Fail-closed network and mutation boundary for live CGI Guided UI/PDF canary."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

PATH=Path(__file__).parents[1]/"scripts"/"b66_cgi_guided_isolated_pdf.py"
spec=importlib.util.spec_from_file_location("b66_cgi_guided_isolated_pdf",PATH)
assert spec and spec.loader
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)

class GuidedIsolatedContract(unittest.TestCase):
    def test_guided_state_is_browser_virtual_only(self):
        for method in ("GET","PUT","DELETE"):
            self.assertEqual(
                module.routing_decision(method,"https://quick-quote-kr.pages.dev/api/padiem/b66/guided-draft"),
                "virtual",
            )
        for method in ("POST","PATCH"):
            self.assertEqual(module.routing_decision(
                method,"https://quick-quote-kr.pages.dev/api/padiem/b66/guided-draft"),"abort")
        for method in ("PUT","DELETE","POST","PATCH"):
            self.assertEqual(module.routing_decision(
                method,"https://evil.example/api/padiem/b66/guided-draft"),"abort")
    def test_denies_any_unrelated_write_or_model(self):
        for path in ("/api/padiem/b66/quote/interpret","/api/padiem/b66/quote/pdf",
                     "/api/padiem/b66/quotes","/api/padiem/b66/saved-skills",
                     "/api/padiem/b66/company-profile"):
            for method in ("POST","PUT","DELETE","PATCH"):
                self.assertEqual(module.routing_decision(
                    method,"https://quick-quote-kr.pages.dev"+path),"abort")
        for path in ("/api/padiem/auth/password/login","/api/padiem/auth/logout"):
            self.assertEqual(module.routing_decision(
                "POST","https://quick-quote-kr.pages.dev"+path),"continue")
        self.assertEqual(module.routing_decision(
            "GET","https://quick-quote-kr.pages.dev/index.html"),"continue")
    def test_sender_company_profile_one_chips_contract(self):
        # The approved CompanyProfile owns sender identity, so the Guided
        # wizard offers only the single Continue chip, not the legacy trio.
        root=PATH.parents[1]
        source=(root/"scripts"/"b66_cgi_final_handoff_smoke.py").read_text(encoding="utf-8")
        ui=(root.parent/"reference"/"business-66-padiem-quote-v1"/"easy-mode.js").read_text(encoding="utf-8")
        self.assertIn('_click_chip_index(page, index=0, expected_count=1, stage="sender_current")', source)
        self.assertIn("function approvedRuntimeSender()", ui)
        self.assertIn('setChips([{ label: "다음으로", action: () => processGuidedInput("현재") }]);', ui)

    def test_private_reference_custody_does_not_fake_visual_parity(self):
        # Production's approved original is intentionally absent from public
        # source. Missing files are expected only with an explicit revocation.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            folder=root/"reference/b66-public-standard-templates/cgi/v1"
            folder.mkdir(parents=True)
            with self.assertRaises(module.base.SmokeFailure):
                module.approved_private_reference_paths(root)
            (folder/"README.md").write_text(
                "SOURCE_PUBLICATION_AUTHORITY=REVOKED_BY_OWNER_2026-10-14",
                encoding="utf-8")
            self.assertIsNone(module.approved_private_reference_paths(root))
            for relative in ("source/original.pdf",
                             "sol61/template/template.json",
                             "PUBLIC_RELEASE_MANIFEST.json"):
                p=folder/relative
                p.parent.mkdir(parents=True,exist_ok=True)
                p.write_bytes(b"fixture")
            paths=module.approved_private_reference_paths(root)
            self.assertEqual(len(paths),3)
            self.assertTrue(all(p.is_file() for p in paths))

    def test_generated_pdf_parser_and_not_proven_markers(self):
        source=PATH.read_text(encoding="utf-8")
        self.assertIn('CGI_BROWSER_PDF_PARSED_A4_IMAGE=PASS',source)
        self.assertIn('CGI_ORIGINAL_VISUAL_COMPARISON=NOT_PROVEN',source)
        self.assertIn('CGI_ORIGINAL_REFERENCE_HASH=NOT_VERIFIED',source)
        self.assertIn('not pdf[0].get_images(full=True)',source)

    def test_real_browser_and_virtual_slot(self):
        src=PATH.read_text(encoding="utf-8")
        self.assertIn('base._guided(page,counters)',src)
        self.assertIn('route.fulfill(',src)
        self.assertIn('service_workers="block"',src)
        self.assertIn('state["slot"]=None',src)
        self.assertIn('CGI_GUIDED_REAL_D1_MUTATIONS=0',src)
        self.assertIn('base._logout_after_verified_pdf_handoff(page)',src)
        self.assertNotIn('route.continue_()\n                    return\n                if decision=="virtual"',src)

if __name__=="__main__":
    unittest.main()
