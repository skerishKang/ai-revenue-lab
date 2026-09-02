from __future__ import annotations

import hashlib
import unittest

from padiem_ai_core import ApprovalOutcome, VerifiedApprovalDecision

from kagent.contracts import ContractError
from kagent.github_draft_pr import (
    AUTO_MERGE_SUPPORTED,
    DEPLOYMENT_FROM_DRAFT_PR_WRITER_SUPPORTED,
    FORCE_PUSH_SUPPORTED,
    REAL_GITHUB_WRITE_CONFIGURED,
    ApprovalGatedDraftPrWriter,
    DeterministicFakeGitHubDraftPullRequestPort,
    DraftPrApprovalBinding,
    DraftPullRequestPlan,
    server_head_branch,
)
from kagent.sandbox_conformance import VerifiedDiffEvidence


REV = "abcdef1234567890abcdef1234567890abcdef12"
SHA_A = hashlib.sha256(b"a").hexdigest()
SHA_B = hashlib.sha256(b"b").hexdigest()


def evidence(*, exit_code: int = 0, terminal_reason: str = "completed", repository: str = "skerishKang/example", changed_files=("src/app.py",)) -> VerifiedDiffEvidence:
    return VerifiedDiffEvidence(
        run_id="run_1",
        lease_id="lease_1",
        repository_ref=repository,
        input_revision=REV,
        changed_files=tuple(changed_files),
        unified_diff_sha256=SHA_A,
        verification_command_id="verify_unit",
        verification_exit_code=exit_code,
        verification_output_sha256=SHA_B,
        terminal_reason=terminal_reason,
        final_revision_ref="workspace_final_1",
    )


def decision(*, pause_id: str = "pause_1", outcome: ApprovalOutcome = ApprovalOutcome.APPROVED) -> VerifiedApprovalDecision:
    from datetime import datetime, timezone

    return VerifiedApprovalDecision(
        decision_id="decision_1",
        pause_id=pause_id,
        outcome=outcome,
        authority_ref="trusted_control_plane",
        evidence_ref="approval_evidence_1",
        decided_at=datetime(2026, 9, 3, 3, 0, tzinfo=timezone.utc),
    )


class DraftPullRequestPlanTests(unittest.TestCase):
    def make_plan(self, *, title: str = "fix: repair bounded task", body: str = "Verified by bounded unit tests.") -> DraftPullRequestPlan:
        return DraftPullRequestPlan.from_verified_diff(
            plan_id="plan_1",
            evidence=evidence(),
            title=title,
            body=body,
        )

    def test_verified_diff_creates_draft_only_server_derived_plan(self):
        plan = self.make_plan()
        self.assertEqual(plan.base_branch, "main")
        self.assertEqual(plan.base_revision, REV)
        self.assertEqual(plan.head_branch, server_head_branch("run_1"))
        self.assertTrue(plan.draft)
        self.assertFalse(plan.auto_merge)
        self.assertFalse(plan.force_push)
        self.assertFalse(plan.deployment)
        rendered = plan.safe_dict()
        self.assertFalse(rendered["raw_diff_in_plan"])
        self.assertFalse(rendered["raw_terminal_output_in_plan"])
        self.assertEqual(rendered["unified_diff_sha256"], SHA_A)
        self.assertEqual(rendered["verification_output_sha256"], SHA_B)
        self.assertFalse(AUTO_MERGE_SUPPORTED)
        self.assertFalse(FORCE_PUSH_SUPPORTED)
        self.assertFalse(DEPLOYMENT_FROM_DRAFT_PR_WRITER_SUPPORTED)

    def test_head_branch_is_deterministic_and_not_user_selected(self):
        self.assertEqual(server_head_branch("run_1"), server_head_branch("run_1"))
        self.assertNotEqual(server_head_branch("run_1"), server_head_branch("run_2"))
        plan = self.make_plan()
        with self.assertRaises(ContractError):
            DraftPullRequestPlan(
                plan_id=plan.plan_id,
                run_id=plan.run_id,
                repository=plan.repository,
                base_branch=plan.base_branch,
                base_revision=plan.base_revision,
                head_branch="feature/user-controlled",
                unified_diff_sha256=plan.unified_diff_sha256,
                changed_files=plan.changed_files,
                title=plan.title,
                body=plan.body,
                verification_command_id=plan.verification_command_id,
                verification_output_sha256=plan.verification_output_sha256,
            )

    def test_failed_verification_empty_diff_or_failed_terminal_reason_cannot_plan_pr(self):
        with self.assertRaises(ContractError):
            DraftPullRequestPlan.from_verified_diff(
                plan_id="plan_failed",
                evidence=evidence(exit_code=1),
                title="fix: failed",
                body="Should not plan.",
            )
        with self.assertRaises(ContractError):
            DraftPullRequestPlan.from_verified_diff(
                plan_id="plan_empty",
                evidence=evidence(changed_files=()),
                title="fix: empty",
                body="Should not plan.",
            )
        with self.assertRaises(ContractError):
            DraftPullRequestPlan.from_verified_diff(
                plan_id="plan_terminal",
                evidence=evidence(terminal_reason="failed"),
                title="fix: terminal",
                body="Should not plan.",
            )

    def test_repository_must_be_owner_repo_not_url_or_credential(self):
        for repository in ("https://github.com/owner/repo", "owner", "token=fixture/repo"):
            with self.subTest(repository=repository):
                with self.assertRaises(ContractError):
                    DraftPullRequestPlan.from_verified_diff(
                        plan_id="plan_repo",
                        evidence=evidence(repository=repository),
                        title="fix: repo",
                        body="Invalid repo.",
                    )

    def test_base_revision_must_be_exact_hex(self):
        bad = VerifiedDiffEvidence(
            run_id="run_1",
            lease_id="lease_1",
            repository_ref="skerishKang/example",
            input_revision="main",
            changed_files=("src/app.py",),
            unified_diff_sha256=SHA_A,
            verification_command_id="verify_unit",
            verification_exit_code=0,
            verification_output_sha256=SHA_B,
            terminal_reason="completed",
        )
        with self.assertRaises(ContractError):
            DraftPullRequestPlan.from_verified_diff(
                plan_id="plan_bad_base",
                evidence=bad,
                title="fix: base",
                body="Invalid base.",
            )

    def test_title_and_body_reject_secret_like_content(self):
        with self.assertRaises(ContractError):
            self.make_plan(title="fix token=fixturevalue")
        with self.assertRaises(ContractError):
            self.make_plan(body="Bearer fixture-secret-value")

    def test_plan_fingerprint_changes_with_user_visible_plan_content(self):
        a = self.make_plan(title="fix: version A")
        b = self.make_plan(title="fix: version B")
        c = self.make_plan(body="Different safe body.")
        self.assertNotEqual(a.fingerprint, b.fingerprint)
        self.assertNotEqual(a.fingerprint, c.fingerprint)


class ApprovalGatedDraftPrWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = DraftPullRequestPlan.from_verified_diff(
            plan_id="plan_1",
            evidence=evidence(),
            title="fix: bounded task",
            body="Verified by bounded unit tests.",
        )
        self.binding = DraftPrApprovalBinding.bind(
            binding_id="binding_1",
            pause_id="pause_1",
            plan=self.plan,
        )

    def test_default_writer_fails_closed(self):
        with self.assertRaises(ContractError):
            ApprovalGatedDraftPrWriter().submit(
                plan=self.plan,
                binding=self.binding,
                decision=decision(),
            )
        self.assertFalse(REAL_GITHUB_WRITE_CONFIGURED)

    def test_fake_writer_requires_canonical_approved_decision(self):
        fake = DeterministicFakeGitHubDraftPullRequestPort()
        writer = ApprovalGatedDraftPrWriter(fake)
        with self.assertRaises(ContractError):
            writer.submit(
                plan=self.plan,
                binding=self.binding,
                decision=decision(outcome=ApprovalOutcome.DENIED),
            )
        with self.assertRaises(ContractError):
            writer.submit(
                plan=self.plan,
                binding=self.binding,
                decision=decision(pause_id="pause_other"),
            )
        receipt = writer.submit(
            plan=self.plan,
            binding=self.binding,
            decision=decision(),
        )
        self.assertTrue(receipt.draft)
        self.assertEqual(receipt.repository, "skerishKang/example")
        self.assertEqual(receipt.head_branch, self.plan.head_branch)
        self.assertEqual(fake.created, [self.plan])

    def test_changed_plan_invalidates_old_approval_binding(self):
        changed = DraftPullRequestPlan.from_verified_diff(
            plan_id="plan_1",
            evidence=evidence(),
            title="fix: changed title",
            body="Verified by bounded unit tests.",
        )
        fake = DeterministicFakeGitHubDraftPullRequestPort()
        with self.assertRaisesRegex(ContractError, "changed"):
            ApprovalGatedDraftPrWriter(fake).submit(
                plan=changed,
                binding=self.binding,
                decision=decision(),
            )
        self.assertEqual(fake.created, [])


if __name__ == "__main__":
    unittest.main()
