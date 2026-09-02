from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.product_evidence_timeline import (
    CONTROL_PLANE_AUDIT_REPLACED,
    REAL_AUDIT_BACKEND_CONFIGURED,
    InMemoryProductEvidenceTimeline,
    ProductEvidenceEvent,
    ProductEvidenceEventKind,
)


NOW = datetime(2026, 9, 3, 5, 0, tzinfo=timezone.utc)


class ProductEvidenceTimelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.timeline = InMemoryProductEvidenceTimeline(
            timeline_id="timeline_ws_1",
            workspace_id="ws_1",
        )

    def event(self, *, event_id: str, kind: ProductEvidenceEventKind, offset: int = 0, **kwargs):
        return self.timeline.make_event(
            event_id=event_id,
            kind=kind,
            workflow_id=kwargs.pop("workflow_id", "workflow_1"),
            subject_kind=kwargs.pop("subject_kind", "purchase_order"),
            subject_id=kwargs.pop("subject_id", "po_1"),
            subject_version=kwargs.pop("subject_version", 1),
            occurred_at=NOW + timedelta(seconds=offset),
            **kwargs,
        )

    def test_append_builds_deterministic_hash_chain(self):
        first = self.timeline.append(
            self.event(
                event_id="evt_1",
                kind=ProductEvidenceEventKind.OBJECT_VERSION_CREATED,
                evidence_refs=("evidence:po:1",),
            )
        )
        second = self.timeline.append(
            self.event(
                event_id="evt_2",
                kind=ProductEvidenceEventKind.APPROVAL_REQUESTED,
                offset=1,
                actor_ref="actor_owner",
            )
        )
        third = self.timeline.append(
            self.event(
                event_id="evt_3",
                kind=ProductEvidenceEventKind.APPROVAL_DECIDED,
                offset=2,
                actor_ref="actor_owner",
                reason_code="approved",
            )
        )
        self.assertIsNone(first.previous_event_sha256)
        self.assertEqual(second.previous_event_sha256, first.event_sha256)
        self.assertEqual(third.previous_event_sha256, second.event_sha256)
        self.assertTrue(self.timeline.verify_chain())
        self.assertEqual(self.timeline.next_sequence, 4)

    def test_exact_replay_is_idempotent_conflicting_event_id_rejected(self):
        first = self.event(
            event_id="evt_same",
            kind=ProductEvidenceEventKind.COMMUNICATION_SENT,
        )
        self.assertEqual(self.timeline.append(first), first)
        self.assertEqual(self.timeline.append(first), first)
        conflict = replace(
            first,
            kind=ProductEvidenceEventKind.COMMUNICATION_RECEIVED,
            event_sha256="",
        )
        with self.assertRaisesRegex(ContractError, "conflicts"):
            self.timeline.append(conflict)

    def test_gap_wrong_previous_hash_and_time_regression_fail_closed(self):
        first = self.timeline.append(
            self.event(event_id="evt_1", kind=ProductEvidenceEventKind.CLOUD_DISPATCH_ENQUEUED)
        )
        with self.assertRaisesRegex(ContractError, "sequence"):
            self.timeline.append(
                ProductEvidenceEvent(
                    event_id="evt_gap",
                    timeline_id="timeline_ws_1",
                    sequence=3,
                    kind=ProductEvidenceEventKind.CLOUD_DISPATCH_ACKNOWLEDGED,
                    workspace_id="ws_1",
                    workflow_id="workflow_1",
                    subject_kind="run",
                    subject_id="run_1",
                    subject_version=None,
                    occurred_at=NOW + timedelta(seconds=1),
                    previous_event_sha256=first.event_sha256,
                )
            )
        wrong_hash = "0" * 64
        with self.assertRaisesRegex(ContractError, "previous_event_sha256"):
            self.timeline.append(
                ProductEvidenceEvent(
                    event_id="evt_wrong_hash",
                    timeline_id="timeline_ws_1",
                    sequence=2,
                    kind=ProductEvidenceEventKind.CLOUD_DISPATCH_ACKNOWLEDGED,
                    workspace_id="ws_1",
                    workflow_id="workflow_1",
                    subject_kind="run",
                    subject_id="run_1",
                    subject_version=None,
                    occurred_at=NOW + timedelta(seconds=1),
                    previous_event_sha256=wrong_hash,
                )
            )
        with self.assertRaisesRegex(ContractError, "monotonic"):
            self.timeline.append(
                ProductEvidenceEvent(
                    event_id="evt_old",
                    timeline_id="timeline_ws_1",
                    sequence=2,
                    kind=ProductEvidenceEventKind.CLOUD_DISPATCH_ACKNOWLEDGED,
                    workspace_id="ws_1",
                    workflow_id="workflow_1",
                    subject_kind="run",
                    subject_id="run_1",
                    subject_version=None,
                    occurred_at=NOW - timedelta(seconds=1),
                    previous_event_sha256=first.event_sha256,
                )
            )

    def test_cross_workspace_or_timeline_event_is_rejected(self):
        other = ProductEvidenceEvent(
            event_id="evt_other",
            timeline_id="timeline_other",
            sequence=1,
            kind=ProductEvidenceEventKind.PILOT_METRIC_OBSERVED,
            workspace_id="ws_other",
            workflow_id="workflow_1",
            subject_kind="pilot_metric",
            subject_id="metric_1",
            subject_version=1,
            occurred_at=NOW,
        )
        with self.assertRaisesRegex(ContractError, "another timeline"):
            self.timeline.append(other)

    def test_safe_export_has_references_not_raw_payload_authority(self):
        event = self.event(
            event_id="evt_safe",
            kind=ProductEvidenceEventKind.DRAFT_PR_PLANNED,
            subject_kind="draft_pr_plan",
            subject_id="plan_1",
            evidence_refs=("sha256:abc123", "verification:unit"),
        )
        self.timeline.append(event)
        exported = self.timeline.export_safe()
        self.assertEqual(exported["authority"], "b54_product_evidence_projection")
        self.assertFalse(exported["control_plane_authoritative_audit"])
        rendered = exported["events"][0]
        self.assertFalse(rendered["raw_payload_stored"])
        self.assertFalse(rendered["communication_body_stored"])
        self.assertFalse(rendered["raw_diff_stored"])
        self.assertFalse(rendered["task_prompt_stored"])
        self.assertFalse(rendered["tool_arguments_stored"])
        self.assertFalse(rendered["hidden_reasoning_stored"])
        self.assertFalse(rendered["control_plane_authoritative_audit"])
        self.assertFalse(REAL_AUDIT_BACKEND_CONFIGURED)
        self.assertFalse(CONTROL_PLANE_AUDIT_REPLACED)

    def test_reference_fields_reject_credential_like_material(self):
        with self.assertRaises(ContractError):
            self.timeline.make_event(
                event_id="evt_secret",
                kind=ProductEvidenceEventKind.COMMUNICATION_SENT,
                workflow_id="workflow_1",
                subject_kind="communication",
                subject_id="token=fixturevalue",
                occurred_at=NOW,
            )

    def test_supplied_event_hash_must_match_content(self):
        with self.assertRaisesRegex(ContractError, "event_sha256"):
            ProductEvidenceEvent(
                event_id="evt_hash",
                timeline_id="timeline_ws_1",
                sequence=1,
                kind=ProductEvidenceEventKind.VERIFIED_DIFF_RECORDED,
                workspace_id="ws_1",
                workflow_id="workflow_1",
                subject_kind="verified_diff",
                subject_id="diff_1",
                subject_version=1,
                occurred_at=NOW,
                event_sha256="0" * 64,
            )


if __name__ == "__main__":
    unittest.main()
