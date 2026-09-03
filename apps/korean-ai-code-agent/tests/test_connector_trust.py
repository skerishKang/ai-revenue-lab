from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.connector_trust import (
    ConnectorBindingProjection,
    ConnectorBindingState,
    ConnectorHealthProjection,
    ConnectorHealthState,
    ConnectorInboundEvent,
    ConnectorProviderError,
    ConnectorProviderErrorKind,
    ConnectorRateLimitProjection,
    ConnectorWriteIntent,
    ConnectorWriteReceipt,
    IdempotencyDisposition,
    InMemoryEventReplayGuard,
    InMemoryWriteIdempotencyRegistry,
    ReplayDisposition,
    SignatureStatus,
)
from kagent.contracts import ContractError


NOW = datetime(2026, 9, 3, 4, 0, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


class ConnectorTrustTests(unittest.TestCase):
    def binding(self, **overrides):
        values = dict(
            binding_ref="binding_1",
            connector_id="gmail",
            actor_ref="actor_1",
            account_ref="account_1",
            workspace_ref="workspace_1",
            granted_scopes=("gmail.read",),
            granted_capabilities=("gmail/search_threads",),
            issued_at=NOW - timedelta(hours=1),
            updated_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(hours=1),
        )
        values.update(overrides)
        return ConnectorBindingProjection(**values)

    def write_intent(self, **overrides):
        values = dict(
            connector_id="gmail",
            binding_ref="binding_1",
            actor_ref="actor_1",
            tool_name="create_draft",
            target_ref="mailbox_primary",
            payload_fingerprint=DIGEST_A,
            idempotency_key="idem_1",
            approval_ref="p01_approval_1",
            evidence_ref="p01_evidence_1",
            requested_at=NOW,
            expected_version_ref="version_1",
        )
        values.update(overrides)
        return ConnectorWriteIntent(**values)

    def test_binding_projection_is_opaque_and_secret_free(self):
        binding = self.binding()
        self.assertTrue(binding.usable_at(NOW))
        rendered = binding.safe_dict()
        self.assertFalse(rendered["raw_access_token"])
        self.assertFalse(rendered["raw_refresh_token"])
        self.assertFalse(rendered["raw_client_secret"])
        self.assertFalse(rendered["raw_api_key"])
        self.assertFalse(rendered["raw_cookie"])

    def test_expired_or_revoked_binding_fails_closed(self):
        expired = self.binding(expires_at=NOW - timedelta(seconds=1))
        self.assertFalse(expired.usable_at(NOW))
        revoked = self.binding(
            state=ConnectorBindingState.REVOKED,
            revoked_at=NOW - timedelta(minutes=1),
        )
        self.assertFalse(revoked.usable_at(NOW))

    def test_active_binding_cannot_smuggle_revocation_timestamp(self):
        with self.assertRaises(ContractError):
            self.binding(revoked_at=NOW)

    def test_health_must_be_fresh_and_binding_usable(self):
        binding = self.binding()
        fresh = ConnectorHealthProjection(
            binding_ref="binding_1",
            state=ConnectorHealthState.HEALTHY,
            observed_at=NOW - timedelta(seconds=20),
            freshness_seconds=60,
            health_ref="health_1",
        )
        self.assertTrue(fresh.healthy_at(NOW, binding))
        stale = ConnectorHealthProjection(
            binding_ref="binding_1",
            state=ConnectorHealthState.HEALTHY,
            observed_at=NOW - timedelta(seconds=61),
            freshness_seconds=60,
            health_ref="health_2",
        )
        self.assertFalse(stale.healthy_at(NOW, binding))

    def test_replay_guard_is_exact_per_connector_binding_event(self):
        guard = InMemoryEventReplayGuard()
        self.assertEqual(
            guard.observe(connector_id="slack", binding_ref="binding_1", event_ref="event_1"),
            ReplayDisposition.NEW,
        )
        self.assertEqual(
            guard.observe(connector_id="slack", binding_ref="binding_1", event_ref="event_1"),
            ReplayDisposition.DUPLICATE,
        )
        self.assertEqual(
            guard.observe(connector_id="slack", binding_ref="binding_2", event_ref="event_1"),
            ReplayDisposition.NEW,
        )

    def test_signature_required_event_needs_verified_fresh_signature(self):
        event = ConnectorInboundEvent(
            event_ref="event_1",
            connector_id="slack",
            binding_ref="binding_1",
            workspace_ref="workspace_1",
            received_at=NOW,
            body_text="hello",
            signature_required=True,
            signature_status=SignatureStatus.VERIFIED,
            signature_timestamp=NOW - timedelta(seconds=30),
            replay=ReplayDisposition.NEW,
        )
        self.assertTrue(event.accepted())
        stale = ConnectorInboundEvent(
            event_ref="event_2",
            connector_id="slack",
            binding_ref="binding_1",
            workspace_ref="workspace_1",
            received_at=NOW,
            body_text="hello",
            signature_required=True,
            signature_status=SignatureStatus.VERIFIED,
            signature_timestamp=NOW - timedelta(minutes=6),
            replay=ReplayDisposition.NEW,
        )
        self.assertFalse(stale.accepted())

    def test_duplicate_or_failed_signature_event_is_not_accepted(self):
        failed = ConnectorInboundEvent(
            event_ref="event_1",
            connector_id="slack",
            binding_ref="binding_1",
            workspace_ref="workspace_1",
            received_at=NOW,
            body_text="hello",
            signature_required=True,
            signature_status=SignatureStatus.FAILED,
            signature_timestamp=NOW,
            replay=ReplayDisposition.NEW,
        )
        self.assertFalse(failed.accepted())
        duplicate = ConnectorInboundEvent(
            event_ref="event_2",
            connector_id="slack",
            binding_ref="binding_1",
            workspace_ref="workspace_1",
            received_at=NOW,
            body_text="hello",
            signature_required=True,
            signature_status=SignatureStatus.VERIFIED,
            signature_timestamp=NOW,
            replay=ReplayDisposition.DUPLICATE,
        )
        self.assertFalse(duplicate.accepted())

    def test_inbound_body_is_untrusted_bounded_and_redacted(self):
        event = ConnectorInboundEvent(
            event_ref="event_3",
            connector_id="slack",
            binding_ref="binding_1",
            workspace_ref="workspace_1",
            received_at=NOW,
            body_text="token=supersecretvalue",
            signature_required=False,
            signature_status=SignatureStatus.NOT_SUPPORTED,
            signature_timestamp=None,
            replay=ReplayDisposition.NEW,
        )
        rendered = event.safe_dict()
        self.assertFalse(rendered["body_trusted"])
        self.assertNotIn("supersecretvalue", rendered["body_text"])
        self.assertTrue(rendered["accepted"])

    def test_write_intent_requires_trusted_approval_and_evidence_refs(self):
        intent = self.write_intent()
        rendered = intent.safe_dict()
        self.assertEqual(rendered["approval_ref"], "p01_approval_1")
        self.assertEqual(rendered["evidence_ref"], "p01_evidence_1")
        self.assertFalse(rendered["payload_text_present"])
        self.assertFalse(rendered["model_text_counts_as_success"])
        with self.assertRaises(ContractError):
            self.write_intent(approval_ref="")

    def test_write_idempotency_distinguishes_same_replay_from_conflict(self):
        registry = InMemoryWriteIdempotencyRegistry()
        first = self.write_intent()
        self.assertEqual(registry.observe(first), IdempotencyDisposition.NEW)
        self.assertEqual(registry.observe(first), IdempotencyDisposition.REPLAY_SAME)
        conflict = self.write_intent(payload_fingerprint=DIGEST_B)
        self.assertEqual(registry.observe(conflict), IdempotencyDisposition.CONFLICT)

    def test_rate_limit_and_provider_error_are_safe_projections(self):
        rate = ConnectorRateLimitProjection(
            observed_at=NOW,
            remaining=0,
            limit=100,
            retry_after_seconds=30,
            reset_at=NOW + timedelta(seconds=30),
        )
        error = ConnectorProviderError(
            kind=ConnectorProviderErrorKind.RATE_LIMITED,
            error_ref="provider_rate_limit",
            retryable=True,
            rate_limit=rate,
        )
        rendered = error.safe_dict()
        self.assertEqual(rendered["kind"], "rate_limited")
        self.assertFalse(rendered["raw_provider_error"])
        self.assertEqual(rendered["rate_limit"]["retry_after_seconds"], 30)

    def test_write_receipt_is_only_trusted_success_projection(self):
        receipt = ConnectorWriteReceipt(
            receipt_ref="receipt_1",
            connector_id="gmail",
            binding_ref="binding_1",
            idempotency_key="idem_1",
            provider_operation_ref="provider_op_1",
            target_ref="draft_1",
            committed_at=NOW,
            evidence_ref="p01_evidence_2",
            version_ref="version_2",
        )
        rendered = receipt.safe_dict()
        self.assertTrue(rendered["trusted_receipt"])
        self.assertFalse(rendered["model_text_counts_as_success"])


if __name__ == "__main__":
    unittest.main()
