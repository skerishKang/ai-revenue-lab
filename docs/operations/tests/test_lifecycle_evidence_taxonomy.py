"""Doc taxonomy guarantees stable evidence ownership and immutable dated sources."""
import hashlib
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[3]
INDEXES = (
    "docs/lifecycle/README.md",
    "docs/evidence/README.md",
    "docs/history/README.md",
)
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
ARCHIVES_SHA256 = {'docs/history/2026-09-01/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.audit.md': 'f0c897fafb898f04090c91b00d90bc62bfdef5025c25f827083f5b226aedec31', 'docs/history/2026-09-01/PADIEM_AI_CORE_README.snapshot.md': 'faf046fe8ecebf1ab1437b3271b343aac36a71a28373bf357f157d0778b5fdda', 'docs/history/2026-09-02/PADIEM_CLAW_README.snapshot.md': 'c4a83933b39a6269392a4fcaa14d5b7a6d7e9b3f8114aa45882341e5e2cbbf24', 'docs/history/2026-10-08/B66_DOCUMENT_FIDELITY_DEVELOPMENT_MODEL_HEURISTICS.snapshot.md': 'eb66f5f3ab1443777cf63b32f7cb31ed7a967f0cab03ab18ad6bfde26102bf2d', 'docs/history/2026-10-08/B66_MVP_RUNTIME_REPAIR_2026-10-08.snapshot.md': 'c0587a8df41e5cb2505261b9c279ca7296e82e8d1f287ee2693a714e399214c1', 'docs/history/2026-10-08/B66_QUOTE_BETA_DEMO_GUIDE.snapshot.md': 'e47bc790dc0b9ffcd8a7faac39eef27538d058adde9fb770f238460cc486a3d4', 'docs/history/2026-10-08/B66_QUOTE_BETA_REFERENCE_README.snapshot.md': '8ba1a0d479df99352c5c980b9d1038ef0a22e5a75f388a9f8213666472d4bf36', 'docs/history/2026-10-08/B66_QUOTE_SERVER_ADAPTER_README.snapshot.md': '8218d5cede9d015fab544900d49843ee86768300e06ba3b6ba347ea31b79c0c4'}


class StageEvidenceTaxonomyTests(unittest.TestCase):
    def test_indexes_only_link_to_authority(self):
        for relative in INDEXES:
            with self.subTest(relative=relative):
                content = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("DOC_STATUS = CANONICAL", content)
                self.assertIn("SCOPE = NAVIGATION_ONLY", content)
                self.assertIn("~~~text", content)
                self.assertNotIn("??", content)

    def test_lifecycle_stages_link_to_evidence_and_policy(self):
        lifecycle = (ROOT / INDEXES[0]).read_text(encoding="utf-8")
        for source in (
            "../operations/AI_DEVELOPMENT_OPERATING_POLICY.md",
            "../operations/TEST_SCOPE_AND_DELIVERY_POLICY.md",
            "../operations/DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md",
            "../evidence/README.md",
            "../models/README.md",
        ):
            with self.subTest(source=source):
                self.assertIn("("+source+")", lifecycle)
        self.assertNotIn("MODEL_SOURCE_MERGED = NO", lifecycle)
        self.assertNotIn("CUSTOMER_READY = YES", lifecycle)

    def test_evidence_hub_is_not_a_second_approval_policy(self):
        evidence = (ROOT / INDEXES[1]).read_text(encoding="utf-8")
        for source in (
            "../operations/EVIDENCE_REQUIREMENTS.md",
            "../operations/TEST_SCOPE_AND_DELIVERY_POLICY.md",
            "../operations/GITHUB_REPORT_HANDOFF_POLICY.md",
            "../operations/WORKFLOW_STATUS_MODEL.md",
            "../history/README.md",
        ):
            with self.subTest(source=source):
                self.assertIn("("+source+")", evidence)
        self.assertNotIn("GOOGLE_MODEL_SOURCE_MERGED =", evidence)
        self.assertNotIn("PRODUCTION_READY = YES", evidence)

    def test_hub_links_are_real_not_vacuous(self):
        for relative in INDEXES:
            p = ROOT / relative
            links = LINK.findall(p.read_text(encoding="utf-8"))
            self.assertGreater(len(links), 4, relative)
            for href in links:
                if href.startswith(("https://", "http://", "mailto:", "#")):
                    continue
                target = href.split("#", 1)[0].strip()
                if not target:
                    continue
                with self.subTest(relative=relative, href=href):
                    resolved = (p.parent / target).resolve()
                    self.assertTrue(resolved.is_relative_to(ROOT.resolve()), "outside repo: "+href)
                    self.assertTrue(resolved.is_file(), "broken link: "+relative+" -> "+href)

    def test_history_snapshot_bytes_and_index_are_unchanged(self):
        index = (ROOT / INDEXES[2]).read_text(encoding="utf-8")
        self.assertEqual(len(ARCHIVES_SHA256), 8)
        found = sorted(p.relative_to(ROOT).as_posix()
                       for p in (ROOT / "docs/history").glob("20??-??-??/*.md"))
        self.assertEqual(found, sorted(ARCHIVES_SHA256))
        for relative, expected_sha in ARCHIVES_SHA256.items():
            with self.subTest(relative=relative):
                actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
                self.assertEqual(actual, expected_sha, "historical source mutated")
                link = relative.removeprefix("docs/history/")
                self.assertIn("("+link+")", index)


if __name__ == "__main__":
    unittest.main()
