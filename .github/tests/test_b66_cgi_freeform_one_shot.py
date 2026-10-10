"""No-network, fail-closed contract for CGI one-shot freeform proof."""
import importlib.util
from pathlib import Path
import sys
import unittest

SCRIPT=Path(__file__).parents[1]/"scripts"/"b66_cgi_freeform_one_shot.py"
spec=importlib.util.spec_from_file_location("b66_cgi_freeform_one_shot",SCRIPT)
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)

class FreeformContract(unittest.TestCase):
    def test_only_canonical_login_logout_and_single_interpret_are_allowed_posts(self):
        for path in (
            "/api/padiem/auth/password/login",
            "/api/padiem/auth/logout",
            "/api/padiem/b66/quote/interpret",
        ):
            self.assertTrue(module.allowed("POST","https://quick-quote-kr.pages.dev"+path))
            self.assertFalse(module.allowed("POST","https://evil.example"+path))
        for path in (
            "/api/padiem/b66/quotes",
            "/api/padiem/b66/guided-draft",
            "/api/padiem/b66/quote/pdf",
            "/api/padiem/b66/saved-skills",
            "/api/padiem/b66/company-profile",
        ):
            for method in ("POST","PUT","DELETE","PATCH"):
                self.assertFalse(module.allowed(method,"https://quick-quote-kr.pages.dev"+path))
        self.assertTrue(module.allowed("GET","https://quick-quote-kr.pages.dev/api/padiem/b66/guided-draft"))
        self.assertFalse(module.allowed("DELETE","https://quick-quote-kr.pages.dev/api/padiem/b66/guided-draft"))

    def test_existing_one_shot_code_guards(self):
        source=SCRIPT.read_text(encoding="utf-8")
        self.assertIn('counts["interpret"]>=1',source)
        self.assertIn("service_workers=\"block\"",source)
        self.assertIn("base._complete_free_form(page,live_counters,model)",source)
        self.assertNotIn("base._guided(page",source)
        self.assertNotIn("base._require_empty_guided_slot(page",source)
        self.assertIn("base._logout_after_verified_pdf_handoff(page)",source)
        self.assertIn("PASSWORD_OUTPUT=0",source)

if __name__=="__main__":
    unittest.main()
