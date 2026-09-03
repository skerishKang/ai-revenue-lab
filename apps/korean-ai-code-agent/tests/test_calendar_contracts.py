from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from kagent.calendar_contracts import (
    CALENDAR_EVENT_CONTENT_TRUSTED,
    CALENDAR_HIDDEN_NOTIFICATION_DEFAULT_ALLOWED,
    CALENDAR_MCP_ETAG_IF_MATCH_ATOMICITY_VERIFIED,
    CALENDAR_REST_IF_MATCH_SUPPORTED,
    CalendarCapability,
    CalendarConferencePolicy,
    CalendarEventProjection,
    CalendarEventTime,
    CalendarMutationApproval,
    CalendarMutationMaterial,
    CalendarMutationPreflightDecision,
    CalendarMutationReceipt,
    CalendarNotificationLevel,
    CalendarRecurrenceScope,
    CalendarRecurrenceTarget,
    CalendarReminder,
    CalendarResponseStatus,
    CalendarScopeProjection,
    calendar_mutation_preflight,
)
from kagent.connector_trust import ConnectorWriteIntent, ConnectorWriteReceipt
from kagent.contracts import ContractError


NOW = datetime(2026, 9, 3, 4, 30, tzinfo=timezone.utc)
DESCRIPTION_SHA = "a" * 64
ETAG_HASH = "b" * 64


class CalendarContractsTests(unittest.TestCase):
    def timed(self, **overrides):
        values = dict(
            all_day=False,
            time_zone="Asia/Seoul",
            start_at=datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 9, 10, 2, 0, tzinfo=timezone.utc),
        )
        values.update(overrides)
        return CalendarEventTime(**values)

    def scope(self):
        return CalendarScopeProjection(
            binding_ref="binding_calendar_1",
            workspace_ref="workspace_calendar_1",
            allowed_calendar_ids=("primary", "team_calendar"),
        )

    def current_event(self, **overrides):
        values = dict(
            calendar_id="primary",
            event_id="event_1",
            etag='"provider-etag-1"',
            summary="Review",
            description="Untrusted description",
            location="Room 1",
            organizer_email="owner@example.com",
            attendee_emails=("a@example.com",),
            event_time=self.timed(),
            recurrence_rules=(),
            recurrence_target=CalendarRecurrenceTarget(CalendarRecurrenceScope.NON_RECURRING),
            status="confirmed",
            updated_at=NOW,
        )
        values.update(overrides)
        return CalendarEventProjection(**values)

    def material(self, **overrides):
        current = self.current_event()
        values = dict(
            binding_ref="binding_calendar_1",
            workspace_ref="workspace_calendar_1",
            operation=CalendarCapability.UPDATE_EVENT,
            calendar_id="primary",
            event_id="event_1",
            expected_etag_sha256=current.etag_sha256,
            summary="Review",
            description_sha256=DESCRIPTION_SHA,
            location="Room 1",
            attendee_emails=("a@example.com",),
            event_time=self.timed(),
            recurrence_target=CalendarRecurrenceTarget(CalendarRecurrenceScope.NON_RECURRING),
            recurrence_rules=(),
            reminders=(CalendarReminder("popup", 10),),
            conference_policy=CalendarConferencePolicy.NONE,
            notification_level=CalendarNotificationLevel.ALL,
        )
        values.update(overrides)
        return CalendarMutationMaterial(**values)

    def approval(self, material=None, **overrides):
        material = material or self.material()
        values = dict(
            approval_ref="p01_approval_calendar_1",
            evidence_ref="p01_evidence_calendar_1",
            material_fingerprint=material.material_fingerprint,
            approved_at=NOW,
        )
        values.update(overrides)
        return CalendarMutationApproval(**values)

    def intent(self, material=None, **overrides):
        material = material or self.material()
        values = dict(
            connector_id="google-calendar",
            binding_ref=material.binding_ref,
            actor_ref="actor_1",
            tool_name=material.operation.value,
            target_ref=material.target_ref,
            payload_fingerprint=material.material_fingerprint,
            idempotency_key="idem_calendar_1",
            approval_ref="p01_approval_calendar_1",
            evidence_ref="p01_evidence_calendar_1",
            requested_at=NOW,
            expected_version_ref=material.version_ref,
        )
        values.update(overrides)
        return ConnectorWriteIntent(**values)

    def test_scope_is_explicit_and_bounded(self):
        scope = self.scope()
        self.assertTrue(scope.authorizes(binding_ref="binding_calendar_1", calendar_id="primary"))
        self.assertFalse(scope.authorizes(binding_ref="binding_calendar_1", calendar_id="private_other"))
        self.assertFalse(scope.safe_dict()["whole_account_calendar_access"])

    def test_all_day_and_timed_boundaries_are_explicit(self):
        all_day = CalendarEventTime(
            all_day=True,
            time_zone="Asia/Seoul",
            start_date=date(2026, 9, 10),
            end_date=date(2026, 9, 11),
        )
        self.assertTrue(all_day.canonical_dict()["all_day"])
        self.assertEqual(all_day.canonical_dict()["end_date"], "2026-09-11")
        self.assertEqual(self.timed(time_zone="UTC").time_zone, "UTC")
        with self.assertRaises(ContractError):
            CalendarEventTime(
                all_day=True,
                time_zone="Asia/Seoul",
                start_date=date(2026, 9, 10),
                end_date=date(2026, 9, 10),
            )
        with self.assertRaises(ContractError):
            self.timed(time_zone="Not A Zone")
        with self.assertRaises(ContractError):
            self.timed(time_zone="Asia//Seoul")

    def test_recurrence_instance_requires_parent_and_original_start_identity(self):
        with self.assertRaises(ContractError):
            CalendarRecurrenceTarget(CalendarRecurrenceScope.INSTANCE)
        instance = CalendarRecurrenceTarget(
            CalendarRecurrenceScope.INSTANCE,
            recurring_event_id="series_1",
            original_start_key="2026-09-10T10:00:00+09:00",
        )
        self.assertEqual(instance.canonical_dict()["recurring_event_id"], "series_1")

    def test_event_projection_hides_raw_etag_and_marks_content_untrusted(self):
        event = self.current_event()
        rendered = event.safe_dict()
        self.assertFalse(rendered["event_content_trusted"])
        self.assertFalse(rendered["raw_etag_exposed_to_model"])
        self.assertNotIn("etag", rendered)
        self.assertEqual(len(rendered["etag_sha256"]), 64)
        self.assertFalse(CALENDAR_EVENT_CONTENT_TRUSTED)

    def test_notification_side_effect_is_material(self):
        all_notifications = self.material(notification_level=CalendarNotificationLevel.ALL)
        none = self.material(notification_level=CalendarNotificationLevel.NONE)
        self.assertTrue(all_notifications.attendee_notification_side_effect)
        self.assertFalse(none.attendee_notification_side_effect)
        self.assertNotEqual(all_notifications.material_fingerprint, none.material_fingerprint)
        self.assertFalse(CALENDAR_HIDDEN_NOTIFICATION_DEFAULT_ALLOWED)

    def test_attendee_and_time_changes_invalidate_material_fingerprint(self):
        baseline = self.material()
        self.assertNotEqual(
            baseline.material_fingerprint,
            self.material(attendee_emails=("other@example.com",)).material_fingerprint,
        )
        changed_time = self.timed(
            start_at=datetime(2026, 9, 10, 2, 0, tzinfo=timezone.utc),
            end_at=datetime(2026, 9, 10, 3, 0, tzinfo=timezone.utc),
        )
        self.assertNotEqual(
            baseline.material_fingerprint,
            self.material(event_time=changed_time).material_fingerprint,
        )

    def test_create_update_delete_respond_are_separate_capabilities(self):
        create = CalendarMutationMaterial(
            binding_ref="binding_calendar_1",
            workspace_ref="workspace_calendar_1",
            operation=CalendarCapability.CREATE_EVENT,
            calendar_id="primary",
            summary="Create",
            description_sha256=DESCRIPTION_SHA,
            location="Room",
            attendee_emails=(),
            event_time=self.timed(),
            recurrence_target=CalendarRecurrenceTarget(CalendarRecurrenceScope.NON_RECURRING),
            notification_level=CalendarNotificationLevel.NONE,
        )
        self.assertEqual(create.operation.value, "create_event")
        self.assertTrue(create.version_ref.startswith("calendar-create:"))
        for capability in (
            CalendarCapability.UPDATE_EVENT,
            CalendarCapability.DELETE_EVENT,
            CalendarCapability.RESPOND_TO_EVENT,
        ):
            kwargs = {}
            if capability is CalendarCapability.RESPOND_TO_EVENT:
                kwargs["response_status"] = CalendarResponseStatus.ACCEPTED
            material = self.material(operation=capability, **kwargs)
            self.assertEqual(material.operation, capability)

    def test_existing_event_mutation_requires_expected_etag_hash(self):
        with self.assertRaises(ContractError):
            self.material(expected_etag_sha256=None)
        with self.assertRaises(ContractError):
            self.material(event_id=None)

    def test_respond_requires_response_status_only_for_respond_operation(self):
        with self.assertRaises(ContractError):
            self.material(operation=CalendarCapability.RESPOND_TO_EVENT, response_status=None)
        response = self.material(
            operation=CalendarCapability.RESPOND_TO_EVENT,
            response_status=CalendarResponseStatus.TENTATIVE,
        )
        self.assertEqual(response.response_status, CalendarResponseStatus.TENTATIVE)
        with self.assertRaises(ContractError):
            self.material(response_status=CalendarResponseStatus.ACCEPTED)

    def test_preflight_allows_exact_approved_current_event(self):
        current = self.current_event()
        material = self.material(expected_etag_sha256=current.etag_sha256)
        decision = calendar_mutation_preflight(
            scope=self.scope(),
            material=material,
            approval=self.approval(material),
            intent=self.intent(material),
            current_event=current,
        )
        self.assertEqual(decision, CalendarMutationPreflightDecision.ALLOW)

    def test_stale_etag_fails_closed(self):
        material = self.material(expected_etag_sha256=self.current_event().etag_sha256)
        changed = self.current_event(etag='"provider-etag-2"')
        decision = calendar_mutation_preflight(
            scope=self.scope(),
            material=material,
            approval=self.approval(material),
            intent=self.intent(material),
            current_event=changed,
        )
        self.assertEqual(decision, CalendarMutationPreflightDecision.STALE_ETAG)
        self.assertTrue(CALENDAR_REST_IF_MATCH_SUPPORTED)
        self.assertFalse(CALENDAR_MCP_ETAG_IF_MATCH_ATOMICITY_VERIFIED)

    def test_material_change_after_approval_fails(self):
        approved_material = self.material()
        current_material = self.material(summary="Changed")
        decision = calendar_mutation_preflight(
            scope=self.scope(),
            material=current_material,
            approval=self.approval(approved_material),
            intent=self.intent(current_material),
            current_event=self.current_event(),
        )
        self.assertEqual(decision, CalendarMutationPreflightDecision.MATERIAL_CHANGED)

    def test_out_of_scope_calendar_fails(self):
        material = self.material(calendar_id="other_calendar")
        decision = calendar_mutation_preflight(
            scope=self.scope(),
            material=material,
            approval=self.approval(material),
            intent=self.intent(material),
            current_event=self.current_event(calendar_id="other_calendar"),
        )
        self.assertEqual(decision, CalendarMutationPreflightDecision.OUT_OF_SCOPE)

    def test_wrong_tool_or_version_binding_fails(self):
        material = self.material()
        wrong_tool = calendar_mutation_preflight(
            scope=self.scope(),
            material=material,
            approval=self.approval(material),
            intent=self.intent(material, tool_name="delete_event"),
            current_event=self.current_event(),
        )
        self.assertEqual(wrong_tool, CalendarMutationPreflightDecision.WRONG_CONNECTOR_OR_TOOL)
        wrong_version = calendar_mutation_preflight(
            scope=self.scope(),
            material=material,
            approval=self.approval(material),
            intent=self.intent(material, expected_version_ref="calendar-etag:wrong"),
            current_event=self.current_event(),
        )
        self.assertEqual(wrong_version, CalendarMutationPreflightDecision.VERSION_BINDING_MISMATCH)

    def test_create_preflight_does_not_require_current_event(self):
        material = CalendarMutationMaterial(
            binding_ref="binding_calendar_1",
            workspace_ref="workspace_calendar_1",
            operation=CalendarCapability.CREATE_EVENT,
            calendar_id="primary",
            summary="Create",
            description_sha256=DESCRIPTION_SHA,
            location="Room",
            attendee_emails=("a@example.com",),
            event_time=self.timed(),
            recurrence_target=CalendarRecurrenceTarget(CalendarRecurrenceScope.NON_RECURRING),
            notification_level=CalendarNotificationLevel.ALL,
        )
        decision = calendar_mutation_preflight(
            scope=self.scope(),
            material=material,
            approval=self.approval(material),
            intent=self.intent(material),
            current_event=None,
        )
        self.assertEqual(decision, CalendarMutationPreflightDecision.ALLOW)

    def test_receipt_requires_provider_etag_for_non_delete(self):
        connector_receipt = ConnectorWriteReceipt(
            receipt_ref="receipt_calendar_1",
            connector_id="google-calendar",
            binding_ref="binding_calendar_1",
            idempotency_key="idem_calendar_1",
            provider_operation_ref="calendar_update_1",
            target_ref="calendar:primary:event:event_1",
            committed_at=NOW,
            evidence_ref="p01_evidence_calendar_2",
        )
        receipt = CalendarMutationReceipt(
            connector_receipt=connector_receipt,
            operation=CalendarCapability.UPDATE_EVENT,
            calendar_id="primary",
            event_id="event_1",
            result_etag_sha256=ETAG_HASH,
        )
        rendered = receipt.safe_dict()
        self.assertTrue(rendered["trusted_provider_receipt"])
        self.assertFalse(rendered["model_text_counts_as_mutation_success"])
        with self.assertRaises(ContractError):
            CalendarMutationReceipt(
                connector_receipt=connector_receipt,
                operation=CalendarCapability.UPDATE_EVENT,
                calendar_id="primary",
                event_id="event_1",
            )

    def test_receipt_requires_exact_mutation_target(self):
        wrong_target = ConnectorWriteReceipt(
            receipt_ref="receipt_calendar_wrong_target",
            connector_id="google-calendar",
            binding_ref="binding_calendar_1",
            idempotency_key="idem_calendar_wrong_target",
            provider_operation_ref="calendar_update_wrong_target",
            target_ref="calendar:primary:event:event_other",
            committed_at=NOW,
            evidence_ref="p01_evidence_calendar_wrong_target",
        )
        with self.assertRaises(ContractError):
            CalendarMutationReceipt(
                connector_receipt=wrong_target,
                operation=CalendarCapability.UPDATE_EVENT,
                calendar_id="primary",
                event_id="event_1",
                result_etag_sha256=ETAG_HASH,
            )

    def test_delete_receipt_does_not_invent_returned_etag(self):
        connector_receipt = ConnectorWriteReceipt(
            receipt_ref="receipt_calendar_delete_1",
            connector_id="google-calendar",
            binding_ref="binding_calendar_1",
            idempotency_key="idem_calendar_delete_1",
            provider_operation_ref="calendar_delete_1",
            target_ref="calendar:primary:event:event_1",
            committed_at=NOW,
            evidence_ref="p01_evidence_calendar_3",
        )
        receipt = CalendarMutationReceipt(
            connector_receipt=connector_receipt,
            operation=CalendarCapability.DELETE_EVENT,
            calendar_id="primary",
            event_id="event_1",
        )
        self.assertIsNone(receipt.result_etag_sha256)
        with self.assertRaises(ContractError):
            CalendarMutationReceipt(
                connector_receipt=connector_receipt,
                operation=CalendarCapability.DELETE_EVENT,
                calendar_id="primary",
                event_id="event_1",
                result_etag_sha256=ETAG_HASH,
            )


if __name__ == "__main__":
    unittest.main()
