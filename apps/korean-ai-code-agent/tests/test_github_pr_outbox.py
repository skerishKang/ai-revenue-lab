from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import unittest

from padiem_ai_core import ApprovalOutcome, VerifiedApprovalDecision

from kagent.contracts import ContractError
from kagent.github_draft_pr import (
    DeterministicFakeGitHubDraftPullRequestPort,
    DraftPrApprovalBinding,
    DraftPullRequestPlan,
    DraftPullRequestReceipt,
)
from kagent.github_pr_outbox import (
    AMBIGUOUS_GITHUB_WRITE_AUTO_RETRY_SUPPORTED,
    REAL_GITHUB_OUTBOX_RECONCILIATION_CONFIGURED,
    GitHubDraftPrOutboxState,
    InMemoryGitHubDraftPrOutbox,
    github_pr_write_fingerprint,
)
from kagent.sandbox_conformance import VerifiedDiffEvidence


NOW = datetime(2026, 9, 3, 4, 0, tzinfo=timezone.utc)
REV = "abcdef1234567890abcdef1234567890abcdef12"
SHA_A = hashlib.sha256(b"diff").hexdigest()
SHA_B = hashlib.sha256(b"verify").hexdigest()


def plan(*, title="fix: bounded change"):
    evidence = VerifiedDiffEvidence(
        run_id="run_1",
        lease_id="lease_1",
        repository_ref="skerishKang/example",
        input_revision=REV,
        changed_files=("src/app.py",),
        unified_diff_sha256=SHA_A,
        verification_command_id="verify_unit",
        verification_exit_code=0,
        verification_output_sha256=SHA_B,
        terminal_reason="completed",
        final_revision_ref="workspace_final_1",
    )
    return DraftPullRequestPlan.from_verified_diff(
        plan_id="plan_1",
        evidence=evidence,
        title=title,
        body="Verified by bounded tests.",
    )


def binding(p=None):
    return DraftPrApprovalBinding.bind(binding_id="binding_1", pause_id="pause_1", plan=p or plan())


def decision(*, outcome=ApprovalOutcome.APPROVED, pause_id="pause_1"):
    return VerifiedApprovalDecision(
        decision_id="decision_1",
        pause_id=pause_id,
        outcome=outcome,
        authority_ref="trusted_control_plane",
        evidence_ref="approval_evidence_1",
        decided_at=NOW,
    )


class AmbiguousPort:
    def __init__(self):
        self.calls = 0

    def create_draft(self, plan):
        self.calls += 1
        raise RuntimeError("timeout after possible write")


class WrongReceiptPort:
    def create_draft(self, p):
        return DraftPullRequestReceipt(
            plan_id=p.plan_id,
            repository="skerishKang/other",
            pr_ref="fake_pr_wrong",
            head_branch=p.head_branch,
        )


class GitHubPrOutboxTests(unittest.TestCase):
    def test_exact_created_replay_is_idempotent_and_writer_called_once(self):
        fake = DeterministicFakeGitHubDraftPullRequestPort()
        outbox = InMemoryGitHubDraftPrOutbox(fake)
        p = plan()
        b = binding(p)
        first = outbox.submit(outbox_id="outbox_1", plan=p, binding=b, decision=decision(), now=NOW)
        second = outbox.submit(outbox_id="outbox_1", plan=p, binding=b, decision=decision(), now=NOW)
        self.assertEqual(first, second)
        self.assertEqual(first.state, GitHubDraftPrOutboxState.CREATED)
        self.assertEqual(len(fake.created), 1)

    def test_conflicting_replay_fails_closed(self):
        fake = DeterministicFakeGitHubDraftPullRequestPort()
        outbox = InMemoryGitHubDraftPrOutbox(fake)
        p = plan()
        outbox.submit(outbox_id="outbox_1", plan=p, binding=binding(p), decision=decision(), now=NOW)
        changed = plan(title="fix: changed approved title")
        with self.assertRaises(ContractError):
            outbox.submit(outbox_id="outbox_1", plan=changed, binding=binding(changed), decision=decision(), now=NOW)
        self.assertEqual(len(fake.created), 1)

    def test_denied_or_wrong_pause_does_not_create_outbox_or_call_writer(self):
        fake = DeterministicFakeGitHubDraftPullRequestPort()
        outbox = InMemoryGitHubDraftPrOutbox(fake)
        p = plan()
        with self.assertRaises(ContractError):
            outbox.submit(outbox_id="outbox_denied", plan=p, binding=binding(p), decision=decision(outcome=ApprovalOutcome.DENIED), now=NOW)
        with self.assertRaises(ContractError):
            outbox.submit(outbox_id="outbox_wrong", plan=p, binding=binding(p), decision=decision(pause_id="pause_other"), now=NOW)
        self.assertEqual(fake.created, [])
        with self.assertRaises(ContractError):
            outbox.get("outbox_denied")

    def test_ambiguous_writer_failure_requires_reconciliation_and_never_auto_retries(self):
        port = AmbiguousPort()
        outbox = InMemoryGitHubDraftPrOutbox(port)
        p = plan()
        b = binding(p)
        with self.assertRaises(RuntimeError):
            outbox.submit(outbox_id="outbox_1", plan=p, binding=b, decision=decision(), now=NOW)
        record = outbox.get("outbox_1")
        self.assertEqual(record.state, GitHubDraftPrOutboxState.RECONCILIATION_REQUIRED)
        self.assertEqual(port.calls, 1)
        with self.assertRaises(ContractError):
            outbox.submit(outbox_id="outbox_1", plan=p, binding=b, decision=decision(), now=NOW)
        self.assertEqual(port.calls, 1)
        self.assertFalse(AMBIGUOUS_GITHUB_WRITE_AUTO_RETRY_SUPPORTED)
        self.assertFalse(REAL_GITHUB_OUTBOX_RECONCILIATION_CONFIGURED)

    def test_receipt_correlation_failure_is_ambiguous_and_blocks_retry(self):
        outbox = InMemoryGitHubDraftPrOutbox(WrongReceiptPort())
        p = plan()
        with self.assertRaises(ContractError):
            outbox.submit(outbox_id="outbox_1", plan=p, binding=binding(p), decision=decision(), now=NOW)
        self.assertEqual(outbox.get("outbox_1").state, GitHubDraftPrOutboxState.RECONCILIATION_REQUIRED)

    def test_safe_projection_contains_hashes_not_diff_or_terminal_output(self):
        fake = DeterministicFakeGitHubDraftPullRequestPort()
        outbox = InMemoryGitHubDraftPrOutbox(fake)
        p = plan()
        b = binding(p)
        record = outbox.submit(outbox_id="outbox_1", plan=p, binding=b, decision=decision(), now=NOW)
        rendered = record.safe_dict()
        self.assertEqual(rendered["write_fingerprint"], github_pr_write_fingerprint(p, b))
        self.assertFalse(rendered["raw_diff"])
        self.assertFalse(rendered["raw_terminal_output"])
        self.assertFalse(rendered["auto_retry"])
        self.assertFalse(rendered["auto_merge"])


if __name__ == "__main__":
    unittest.main()
