"""S6 approval/action-confirmation presentation contract tests (network-free)."""

from __future__ import annotations

import unittest

from padiem_embedded_runtime.approval_presentation import (
    MAX_PROPOSALS,
    STATUS_DEGRADED,
    STATUS_EMPTY,
    STATUS_PRESENTED,
    STATUS_READY,
    STATUS_REJECTED,
    STATUS_STAGED,
    normalize_approval_proposal,
    present_approval_proposals,
    present_approval_state,
    present_confirmation_intent,
    present_public_reference,
)

VALID_PROPOSAL = {
    "proposal_id": "prop_1001",
    "tool_id": "tool.email.send",
    "requirement": "first_party",
    "summary": "Send a weekly digest",
}


class NormalizeProposalTests(unittest.TestCase):
    def test_valid_proposal_round_trips(self) -> None:
        proposal = normalize_approval_proposal(VALID_PROPOSAL)
        self.assertEqual(proposal.proposal_id, "prop_1001")
        self.assertEqual(proposal.to_public_dict()["tool_id"], "tool.email.send")

    def test_unknown_field_fails_closed(self) -> None:
        with self.assertRaises(Exception):
            normalize_approval_proposal({**VALID_PROPOSAL, "args": {"raw": "x"}})

    def test_tool_args_shaped_summary_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            normalize_approval_proposal({**VALID_PROPOSAL, "summary": "tool_args dump here"})

    def test_url_or_diff_shaped_summary_is_rejected(self) -> None:
        for summary in ("see https://x.test/a", "diff --git a/x b/x", "<b>bold</b>"):
            with self.subTest(summary=summary):
                with self.assertRaises(Exception):
                    normalize_approval_proposal({**VALID_PROPOSAL, "summary": summary})

    def test_path_shaped_identifier_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            normalize_approval_proposal({**VALID_PROPOSAL, "proposal_id": "C:\\x\\prop"})

    def test_oversize_summary_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            normalize_approval_proposal({**VALID_PROPOSAL, "summary": "s" * 121})


class PresentProposalsTests(unittest.TestCase):
    def test_order_dedup_and_labels(self) -> None:
        presentation = present_approval_proposals(
            [
                VALID_PROPOSAL,
                {
                    "proposal_id": "prop_1002",
                    "tool_id": "tool.calendar.read",
                    "requirement": "always",
                },
                VALID_PROPOSAL,
            ]
        )
        self.assertEqual(presentation.status, STATUS_READY)
        self.assertEqual([p.label for p in presentation.proposals], ["[1]", "[2]"])
        self.assertEqual(presentation.proposals[0].proposal.proposal_id, "prop_1001")

    def test_bound_is_enforced(self) -> None:
        items = [
            {**VALID_PROPOSAL, "proposal_id": f"prop_{i}"} for i in range(MAX_PROPOSALS + 2)
        ]
        presentation = present_approval_proposals(items)
        self.assertEqual(len(presentation.proposals), MAX_PROPOSALS)
        self.assertEqual(presentation.dropped_count, 2)
        self.assertEqual(presentation.status, STATUS_DEGRADED)

    def test_empty_input_is_empty_status(self) -> None:
        self.assertEqual(present_approval_proposals([]).status, STATUS_EMPTY)

    def test_malformed_items_drop_without_raising_or_retention(self) -> None:
        presentation = present_approval_proposals(
            [VALID_PROPOSAL, "not-a-mapping", {**VALID_PROPOSAL, "proposal_id": "https://x/y"}]
        )
        self.assertEqual(presentation.status, STATUS_DEGRADED)
        self.assertEqual(presentation.dropped_count, 2)
        self.assertNotIn("https", str(presentation.to_public_dict()))

    def test_non_sequence_input_degrades(self) -> None:
        presentation = present_approval_proposals("not-a-list")
        self.assertEqual(presentation.status, STATUS_DEGRADED)
        self.assertEqual(presentation.dropped_count, 1)


class ConfirmationIntentTests(unittest.TestCase):
    def test_all_allowlisted_intents_stage(self) -> None:
        for intent in ("approve", "reject", "confirm", "cancel"):
            with self.subTest(intent=intent):
                view = present_confirmation_intent(
                    {"intent": intent, "proposal_id": "prop_1001"}
                )
                self.assertEqual(view.status, STATUS_STAGED)
                self.assertEqual(view.intent, intent)
                self.assertFalse(view.to_public_dict()["reason_code"] == "INVALID_INTENT")

    def test_non_allowlisted_intent_rejected_without_echo(self) -> None:
        view = present_confirmation_intent(
            {"intent": "force_execute", "proposal_id": "prop_1001"}
        )
        self.assertEqual(view.status, STATUS_REJECTED)
        self.assertEqual(view.reason_code, "INVALID_INTENT")
        self.assertEqual(view.intent, "")
        self.assertEqual(view.proposal_id, "")

    def test_invalid_proposal_id_rejected(self) -> None:
        view = present_confirmation_intent({"intent": "approve", "proposal_id": "/tmp/x"})
        self.assertEqual(view.status, STATUS_REJECTED)
        self.assertEqual(view.reason_code, "INVALID_PROPOSAL_ID")

    def test_malformed_and_unknown_fields_rejected(self) -> None:
        for raw in (
            "not-a-mapping",
            {},
            {"intent": "approve", "proposal_id": "prop_1", "callback_url": "https://x"},
        ):
            with self.subTest(raw=str(raw)):
                view = present_confirmation_intent(raw)
                self.assertEqual(view.status, STATUS_REJECTED)


class ApprovalStateTests(unittest.TestCase):
    def test_allowlisted_states_pass(self) -> None:
        for state in ("pending", "approved", "rejected", "expired", "unavailable"):
            with self.subTest(state=state):
                view = present_approval_state({"state": state})
                self.assertEqual(view.state, state)
                self.assertFalse(view.degraded)

    def test_reason_codes_only_on_terminal_states(self) -> None:
        view = present_approval_state({"state": "rejected", "reason_code": "USER_REJECTED"})
        self.assertEqual(view.reason_code, "USER_REJECTED")
        bad = present_approval_state({"state": "approved", "reason_code": "USER_REJECTED"})
        self.assertTrue(bad.degraded)

    def test_malformed_degrades_to_unavailable(self) -> None:
        for raw in (
            {"state": "auto_approved_by_sidecar"},
            {"state": "pending", "reason_code": "raw failure text"},
            "not-a-mapping",
            {"state": "pending", "verdict": "yes"},
        ):
            with self.subTest(raw=str(raw)):
                view = present_approval_state(raw)
                self.assertTrue(view.degraded)
                self.assertEqual(view.state, "unavailable")
                self.assertEqual(view.reason_code, "INVALID_HOST_INPUT")


class PublicReferenceTests(unittest.TestCase):
    def test_bounded_identifier_presents(self) -> None:
        view = present_public_reference("evidence_9f2c1a7b")
        self.assertEqual(view.status, STATUS_PRESENTED)
        self.assertEqual(view.label, "evidence_9f2c1a7b")

    def test_url_shaped_reference_rejected_without_retention(self) -> None:
        view = present_public_reference("https://authority.example/decision/42")
        self.assertEqual(view.status, STATUS_REJECTED)
        self.assertEqual(view.reason_code, "URL_SHAPED_REFERENCE")
        self.assertNotIn("authority.example", str(view.to_public_dict()))

    def test_invalid_grammar_and_non_string_rejected(self) -> None:
        for value in ("has space", "x" * 129, None, 7):
            with self.subTest(value=str(value)):
                view = present_public_reference(value)
                self.assertEqual(view.status, STATUS_REJECTED)


if __name__ == "__main__":
    unittest.main()
