"""Guard latest owner model decision versus current merged B14 runtime.

Static docs only: no provider, network, billing, credentials or Production calls.
"""
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
        self.assertIn("LOCAL ONLY / NOT MERGED",s)
        self.assertIn("image NOT VERIFIED",s)
    def test_entrypoints_refer_to_current_owner_ledger(self):
        for p in ("AGENTS.md","docs/README.md","apps/korean-ai-platform/README.md","apps/korean-ai-platform/docs/README.md","apps/korean-ai-platform/docs/B14_ROUTER_PLATFORM_AND_PADIEM_PROFILE.md","apps/padiem-chat/README.md"):
            with self.subTest(file=p):
                self.assertIn("B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md",read(p))
    def test_root_current_tier_never_old_mapping(self):
        s=read("docs/README.md").split("## Padiem tier terminology",1)[1].split("## Documentation authority order",1)[0]
        self.assertNotIn("Padiem Plus = Laguna",s)
        self.assertNotIn("Padiem Pro  = Nemotron",s)
        for item in GOOGLE + EXCLUDED:
            self.assertIn(item,s)
        self.assertIn("MERGED_SOURCE_PLUS",s)
    def test_current_charter_no_unselected_successor_claim(self):
        s=read("apps/korean-ai-platform/docs/B14_ROUTER_PLATFORM_AND_PADIEM_PROFILE.md").split("## 2. Current Padiem request",1)[1].split("## 3. Auto-routing rule",1)[0]
        for item in GOOGLE + EXCLUDED:
            self.assertIn(item,s)
        self.assertIn("CURRENT_MERGED_PLUS",s)
        self.assertIn("GOOGLE_MODEL_SOURCE_MERGED = NO",s)
        self.assertNotIn("No successor is selected yet",s)
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
