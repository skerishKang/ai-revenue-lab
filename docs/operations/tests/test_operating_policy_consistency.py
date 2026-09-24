from __future__ import annotations

import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
OPS = REPO / "docs" / "operations"


class OperatingPolicyConsistencyTests(unittest.TestCase):
    def read(self, path: Path) -> str:
        self.assertTrue(path.is_file(), f"missing required policy file: {path}")
        return path.read_text(encoding="utf-8")

    def test_required_policy_files_exist(self) -> None:
        required = [
            REPO / "AGENTS.md",
            REPO / "README.md",
            REPO / ".github" / "pull_request_template.md",
            OPS / "AI_DEVELOPMENT_OPERATING_POLICY.md",
            OPS / "TECHNOLOGY_ADOPTION_POLICY.md",
            REPO / "docs" / "architecture" / "PADIEM_TECHNOLOGY_COMPONENT_REGISTRY_v1.md",
            OPS / "WORKFLOW_STATUS_MODEL.md",
            OPS / "EVIDENCE_REQUIREMENTS.md",
            OPS / "UI_UX_BACKEND_PHASE_GATES.md",
            OPS / "NEW_BUSINESS_UI_FIRST_PLAYBOOK.md",
            OPS / "BACKEND_MVP_OPERATING_POLICY.md",
            OPS / "templates" / "CTO_WORK_ORDER.md",
            OPS / "templates" / "WEB_DEVELOPER_REPORT.md",
            OPS / "templates" / "LOCAL_VALIDATION_REPORT.md",
            OPS / "templates" / "CTO_FINAL_REVIEW.md",
        ]
        for path in required:
            self.assertTrue(path.is_file(), str(path))

    def test_search_before_build_policy_is_wired_into_active_contracts(self) -> None:
        policy = self.read(OPS / "TECHNOLOGY_ADOPTION_POLICY.md")
        agents = self.read(REPO / "AGENTS.md")
        dev_policy = self.read(OPS / "AI_DEVELOPMENT_OPERATING_POLICY.md")
        work_order = self.read(OPS / "templates" / "CTO_WORK_ORDER.md")
        pr_template = self.read(REPO / ".github" / "pull_request_template.md")
        final_review = self.read(OPS / "templates" / "CTO_FINAL_REVIEW.md")

        self.assertIn("SEARCH_BEFORE_BUILD=YES", policy)
        self.assertIn("BUY_ADOPT_ADAPT_BEFORE_BUILD=YES", policy)
        self.assertIn("SECOND_PRODUCT_AUTHORITY=0", policy)
        self.assertIn("BUILD_FROM_SCRATCH", policy)
        self.assertIn("REPLACEABLE_COMPONENTS=YES", policy)
        self.assertIn("EXISTING_IMPLEMENTATION_CAN_BE_REEVALUATED=YES", policy)
        registry = self.read(REPO / "docs" / "architecture" / "PADIEM_TECHNOLOGY_COMPONENT_REGISTRY_v1.md")
        self.assertIn("REPLACEABLE_COMPONENT", registry)
        self.assertIn("REPLACE_PRIMARY_KEEP_FALLBACK", registry)

        for text in (agents, dev_policy):
            self.assertIn("TECHNOLOGY_ADOPTION_POLICY.md", text)
            self.assertIn("BUILD_FROM_SCRATCH", text)

        self.assertIn("Technology adoption gate", work_order)
        self.assertIn("Technology adoption / build decision", pr_template)
        self.assertIn("Technology adoption review", final_review)

    def test_actor_separation_invariant_is_consistent(self) -> None:
        agents = self.read(REPO / "AGENTS.md")
        policy = self.read(OPS / "AI_DEVELOPMENT_OPERATING_POLICY.md")
        for text in (agents, policy):
            self.assertIn("ONE_ACTOR_MAY_PERFORM_MULTIPLE_NON_INDEPENDENT_STAGES", text)
            self.assertIn("independent Local Validation", text)
            self.assertTrue(
                "SAME_REVISION" in text or "same revision" in text.lower(),
                "same-revision independence boundary missing",
            )

    def test_active_policy_does_not_restore_mandatory_ui_ux_backend_sequence(self) -> None:
        files = [
            REPO / "AGENTS.md",
            REPO / "README.md",
            OPS / "README.md",
            OPS / "AI_DEVELOPMENT_OPERATING_POLICY.md",
            OPS / "UI_UX_BACKEND_PHASE_GATES.md",
            OPS / "NEW_BUSINESS_UI_FIRST_PLAYBOOK.md",
        ]
        for path in files:
            text = self.read(path)
            self.assertNotIn("Current portfolio mode: `UI_ONLY`", text)
            self.assertNotIn("Current mode: `UI_ONLY`", text)
        gates = self.read(OPS / "UI_UX_BACKEND_PHASE_GATES.md")
        self.assertIn("not a mandatory sequential ceremony", gates)
        self.assertIn("SERVICE_LED_PILOT", gates)
        self.assertIn("LIVE_VERTICAL_SLICE", gates)

    def test_backend_policy_is_bounded_not_frozen(self) -> None:
        policy = self.read(OPS / "BACKEND_MVP_OPERATING_POLICY.md")
        self.assertIn("Backend work is not frozen by default", policy)
        for mode in (
            "NO_BACKEND",
            "DETERMINISTIC_SIMULATION",
            "SERVICE_LED",
            "LOCAL_RUNTIME",
            "LIVE_VERTICAL_SLICE",
            "PILOT_RUNTIME",
            "COMMERCIAL_HARDENING",
        ):
            self.assertIn(mode, policy)

    def test_pr_template_requires_revision_and_independence_truth(self) -> None:
        template = self.read(REPO / ".github" / "pull_request_template.md")
        self.assertIn("Exact starting base SHA", template)
        self.assertIn("Exact current head SHA", template)
        self.assertIn("Same actor as implementation?", template)
        self.assertIn("Source modified during validation?", template)
        self.assertIn("Expected head for merge", template)
        self.assertIn("OWNER_UI_APPROVED", template)

    def test_template_links_declared_by_policy_exist(self) -> None:
        for name in (
            "CTO_WORK_ORDER.md",
            "WEB_DEVELOPER_REPORT.md",
            "LOCAL_VALIDATION_REPORT.md",
            "CTO_FINAL_REVIEW.md",
        ):
            self.assertTrue((OPS / "templates" / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
