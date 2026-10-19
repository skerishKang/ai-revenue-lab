"""#3554 — repository model-selection gate reconciliation (additive, non-weakening).

Two duties:

1. pin the section-0 clarification so a per-execution user choice of an already
   registered/allowed model is not treated as an owner model decision; and
2. pin that the reconciliation did **not** weaken the OWNER_ONLY boundary, so the
   carve-out can never silently become a model-policy bypass.

Load-bearing for the negative direction: if a future edit removes the owner gate,
drops a fail-closed rule, or reinstates a successorship/single-primary precondition,
these fail.
"""

from __future__ import annotations

import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
OPS = REPO / "docs" / "operations"
POLICY = OPS / "MODEL_CHANGE_OWNER_APPROVAL_POLICY.md"


class PerExecutionUserChoiceCarveOutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = POLICY.read_text(encoding="utf-8")

    def test_canonical_policy_file_exists(self) -> None:
        self.assertTrue(POLICY.is_file(), f"missing canonical policy: {POLICY}")

    # ── positive: the clarification is present and unambiguous ────────────────

    def test_per_execution_user_choice_is_not_a_model_policy_change(self) -> None:
        self.assertIn("PER_EXECUTION_USER_MODEL_CHOICE=NOT_A_MODEL_POLICY_CHANGE", self.text)
        self.assertIn("MODEL_DECISION_REQUIRED_FOR_PER_EXECUTION_USER_CHOICE=NO", self.text)
        self.assertIn("STOP_AND_ASK_OWNER_FOR_PER_EXECUTION_USER_CHOICE=NO", self.text)

    def test_no_successor_or_single_primary_precondition_remains(self) -> None:
        self.assertIn("SINGLE_PRIMARY_REQUIRED=NO", self.text)
        self.assertIn("SUCCESSOR_SELECTION_REQUIRED_BEFORE_MVP=NO", self.text)
        self.assertIn("GLOBAL_REPRESENTATIVE_MODEL_REQUIRED=NO", self.text)
        self.assertIn("HISTORICAL_MODEL_DECISIONS=PROVENANCE_ONLY", self.text)
        # A stale precondition must not reappear as an active requirement.
        self.assertNotIn("SUCCESSOR_SELECTED=REQUIRED", self.text)
        self.assertNotIn("PREFERRED_CANDIDATE=REQUIRED", self.text)
        self.assertNotIn("PENDING_SUCCESSOR_SELECTION=REQUIRED", self.text)
        self.assertNotIn("TEXT_PRIMARY=REQUIRED", self.text)
        self.assertNotIn("VISION_PRIMARY=REQUIRED", self.text)
        self.assertNotIn("MODEL_SELECTION_GATE=BLOCK", self.text)

    def test_registered_model_use_needs_no_repeated_owner_approval(self) -> None:
        self.assertIn("REPEATED_OWNER_APPROVAL_FOR_REGISTERED_MODEL_USE=NOT_REQUIRED", self.text)
        self.assertIn("EXACT_MODEL_ID_AND_EXECUTION_PERMISSION_VERIFIED_BY=B14", self.text)

    def test_comparison_is_optional_not_a_prerequisite(self) -> None:
        self.assertIn("BENCHMARK_REQUIRED_BEFORE_OWNER_USE=NO", self.text)
        self.assertIn("MODEL_COMPARISON=OPTIONAL", self.text)

    def test_unselected_or_unregistered_fails_closed_with_no_fallback(self) -> None:
        self.assertIn("UNREGISTERED_OR_DISALLOWED_MODEL=FAIL_CLOSED", self.text)
        self.assertIn("NO_MODEL_SELECTED=FAIL_CLOSED", self.text)
        self.assertIn("SILENT_FALLBACK=PROHIBITED", self.text)

    # ── negative: the OWNER_ONLY boundary must NOT be weakened ───────────────

    def test_owner_only_boundary_is_still_declared(self) -> None:
        self.assertIn("MODEL_DECISION_AUTHORITY=OWNER_ONLY", self.text)
        self.assertIn("DEFAULT_AGENT_ACTION=STOP_AND_ASK_OWNER", self.text)
        self.assertIn("IMPLICIT_MODEL_APPROVAL=NO", self.text)
        self.assertIn("PRIOR_MODEL_APPROVAL_CARRY_FORWARD=NO", self.text)

    def test_prohibited_actions_are_still_prohibited(self) -> None:
        for phrase in (
            "search for replacement models",
            "benchmark models",
            "create a ranked model shortlist",
            "change fallback order",
            "mutate model credentials/bindings/endpoints",
            "merge a model-routing PR",
            "deploy model-routing changes",
        ):
            self.assertIn(phrase, self.text)

    def test_carve_out_never_authorizes_the_four_owner_only_moves(self) -> None:
        """The carve-out must not name any owner-only move as allowed."""
        allowed_section = self.text.split("## 0.", 1)[1].split("## 1.", 1)[0].lower()
        for forbidden in (
            "agents may register",
            "agents may activate",
            "agents may deploy",
            "workers may choose",
            "auto-selection required",
        ):
            self.assertNotIn(forbidden, allowed_section)

    def test_reporting_duty_is_preserved_for_real_model_decisions(self) -> None:
        self.assertIn("MODEL_DECISION_REQUIRED=YES", self.text)
        self.assertIn("PROPOSED_OPTIONS", self.text)
        self.assertIn("MODEL_MUTATION_PERFORMED=NO", self.text)
        self.assertIn("LIVE_MODEL_COMPARISON_PERFORMED=NO", self.text)

    def test_unmerged_model_work_and_repository_scope_survive(self) -> None:
        self.assertIn("UNMERGED_MODEL_WORK=HOLD", self.text)
        self.assertIn("MERGE_AUTHORITY=OWNER_ONLY", self.text)
        self.assertIn("DEPLOY_AUTHORITY=OWNER_ONLY", self.text)
        self.assertIn("This policy is repository-wide", self.text)

    def test_section_ordering_keeps_scope_clarification_first(self) -> None:
        self.assertLess(self.text.index("## 0."), self.text.index("## 1. Rule"))
        self.assertIn("weakens no", self.text.replace("\n", " "))


class CanonicalSingleSourceTests(unittest.TestCase):
    """The carve-out lives in exactly one canonical place."""

    def test_agents_md_and_dev_policy_still_point_to_the_canonical_policy(self) -> None:
        agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
        dev = (OPS / "AI_DEVELOPMENT_OPERATING_POLICY.md").read_text(encoding="utf-8")
        for text in (agents, dev):
            self.assertIn("MODEL_CHANGE_OWNER_APPROVAL_POLICY.md", text)

    def test_canonical_policy_is_the_only_doc_declaring_the_stop_contract(self) -> None:
        """No duplicate copy of the gate may drift into another operating doc."""
        duplicates = []
        for path in sorted(OPS.glob("*.md")):
            if path == POLICY:
                continue
            body = path.read_text(encoding="utf-8")
            if "DEFAULT_AGENT_ACTION=STOP_AND_ASK_OWNER" in body:
                duplicates.append(path.name)
        self.assertEqual(duplicates, [], f"duplicated model gate contract in: {duplicates}")


if __name__ == "__main__":
    unittest.main()