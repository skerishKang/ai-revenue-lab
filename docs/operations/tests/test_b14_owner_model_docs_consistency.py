"""Guard latest owner model decision versus current merged B14 runtime.

Static docs only: no provider, network, billing, credentials or Production calls.
"""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
GOOGLE = ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemma-4-26b-a4b-it", "gemma-4-31b-it")
EXCLUDED = ("Kilo Poolside Laguna", "B.AI Qwen", "Motif 3", "GPT-5.6 Luna", "NVIDIA Nemotron")

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

class TestOwnerModelDocTruth(unittest.TestCase):
    def test_ledger_four_google_five_excluded(self):
        s = read("docs/operations/B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md")
        for item in GOOGLE + EXCLUDED:
            with self.subTest(item=item):
                self.assertIn(item,s)
        self.assertIn("SOURCE MERGED / LIVE NOT PROVEN", s)
        self.assertIn("PR #3788", s)
        self.assertIn("image NOT VERIFIED", s)
        self.assertNotIn("google_provider.py absent", s)
        self.assertNotIn("LOCAL ONLY / NOT MERGED", s)
    def test_entrypoints_refer_to_current_owner_ledger(self):
        for p in ("AGENTS.md","docs/README.md","apps/korean-ai-platform/README.md","apps/korean-ai-platform/docs/README.md","apps/korean-ai-platform/docs/B14_ROUTER_PLATFORM_AND_PADIEM_PROFILE.md","apps/padiem-chat/README.md"):
            with self.subTest(file=p):
                self.assertIn("B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md",read(p))
    def test_root_model_index_links_to_authority_not_copied_inventory(self):
        s=read("docs/README.md").split("## Padiem model authority",1)[1].split("## Documentation authority order",1)[0]
        self.assertIn("(models/README.md)", s)
        self.assertIn("B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md", s)
        self.assertIn("MODEL_CHANGE_OWNER_APPROVAL_POLICY.md", s)
        self.assertIn("product_tier_routes.py", s)
        for item in GOOGLE + EXCLUDED:
            with self.subTest(model=item):
                self.assertNotIn(item, s)
        self.assertNotIn("MERGED_SOURCE_PLUS", s)
        self.assertNotIn("registration not merged", s)

    def test_b54_and_b66_reference_shared_model_index(self):
        self.assertIn("(../../docs/models/README.md)", read("apps/korean-ai-code-agent/README.md"))
        self.assertIn("(../../models/README.md)", read("docs/products/b66/README.md"))
    def test_current_charter_no_unselected_successor_claim(self):
        s=read("apps/korean-ai-platform/docs/B14_ROUTER_PLATFORM_AND_PADIEM_PROFILE.md").split("## 2. Current Padiem request",1)[1].split("## 3. Auto-routing rule",1)[0]
        self.assertIn("B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md", s)
        self.assertIn("CURRENT_MERGED_PLUS", s)
        self.assertIn("GOOGLE_SOURCE_AUTHORITY = apps/korean-ai-platform/app/pilot/google_provider.py", s)
        self.assertNotIn("GOOGLE_MODEL_SOURCE_MERGED = NO", s)
        self.assertNotIn("No successor is selected yet",s)
    def test_google_registration_is_current_merged_source_not_production_evidence(self):
        provider = read("apps/korean-ai-platform/app/pilot/google_provider.py")
        platform = read("apps/korean-ai-platform/app/pilot/platform.py")
        for model_id in GOOGLE:
            with self.subTest(model_id=model_id):
                self.assertIn('"google/' + model_id + '"', provider)
        self.assertIn('GOOGLE_BASE_ORIGIN = "https://generativelanguage.googleapis.com/v1beta/openai"', provider)
        self.assertIn('GOOGLE_CREDENTIAL_BINDING = "PADIEM_GEMINI_API_KEY"', provider)
        # The current source of registration is one validated JSON registry,
        # not the historical provider function and its init-time side effects.
        registry = json.loads(read("apps/korean-ai-platform/app/pilot/b14_models.json"))
        google = registry["providers"]["google"]
        self.assertEqual(google["base_origin"], "https://generativelanguage.googleapis.com/v1beta/openai")
        self.assertEqual(google["credential_binding_name"], "PADIEM_GEMINI_API_KEY")
        model_rows={m["id"]:m for m in registry["models"]}
        for model_id in GOOGLE:
            with self.subTest(model_id=model_id):
                exact_id="google/"+model_id
                self.assertIn(exact_id,model_rows)
                self.assertEqual(model_rows[exact_id]["provider_id"],"google")
        self.assertEqual(len(model_rows),10)
        self.assertNotIn("register_google_provider()", platform)
        catalog=read("apps/korean-ai-platform/app/pilot/catalog.py")
        self.assertIn("from .model_registry_file import install_models",catalog)
        self.assertIn("GOOGLE_PRODUCTION_READY = NOT_VERIFIED",
                      read("apps/korean-ai-platform/docs/B14_ROUTER_PLATFORM_AND_PADIEM_PROFILE.md"))

    def test_current_entrypoints_never_claim_google_source_unmerged(self):
        paths = (
            "apps/korean-ai-platform/README.md",
            "apps/korean-ai-platform/docs/README.md",
            "apps/korean-ai-platform/docs/B14_ROUTER_PLATFORM_AND_PADIEM_PROFILE.md",
            "apps/padiem-chat/README.md",
            "docs/operations/B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md",
        )
        for p in paths:
            with self.subTest(file=p):
                s = read(p)
                self.assertNotIn("LOCAL ONLY / NOT MERGED", s)
                self.assertNotIn("LOCAL unmerged source, NOT current main", s)
                self.assertNotIn("google_provider.py absent", s)
                self.assertNotIn("GOOGLE_MODEL_SOURCE_MERGED = NO", s)

    def test_hold_describes_runtime_not_owner_indecision(self):
        for p in ("apps/korean-ai-platform/README.md","apps/padiem-chat/README.md"):
            with self.subTest(file=p):
                s=read(p)
                self.assertIn("Google",s)
                self.assertIn("HOLD",s)
                self.assertNotIn("successor pending",s.lower())
        p=read("docs/operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md")
        self.assertIn("## 0B. Current owner-selected model facts",p)
        self.assertIn("SILENT_FALLBACK=PROHIBITED",p)

if __name__=="__main__":
    unittest.main()
