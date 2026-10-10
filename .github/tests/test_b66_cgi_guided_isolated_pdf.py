"""Fail-closed network and mutation boundary for live CGI Guided UI/PDF canary."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import sys
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
