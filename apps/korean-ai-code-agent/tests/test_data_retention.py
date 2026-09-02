from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.data_retention import (
    DEFAULT_RETENTION_POLICY,
    HIDDEN_REASONING_RETENTION_CLASS_SUPPORTED,
    MODEL_DEFINED_RETENTION_SUPPORTED,
    RAW_CREDENTIAL_RETENTION_CLASS_SUPPORTED,
    REAL_STORAGE_DELETE_CONFIGURED,
    DeletionReceipt,
    RetainedDataClass,
    RetainedRecordMetadata,
    RetentionDisposition,
    RetentionPolicy,
    RetentionRule,
    evaluate_retention,
)

NOW = datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)


def record(*, data_class=RetainedDataClass.INBOUND_MESSAGE_BODY, created_at=None, legal_hold_ref=None, policy=DEFAULT_RETENTION_POLICY):
    return RetainedRecordMetadata(
        record_ref="record_1",
        workspace_id="ws_1",
        data_class=data_class,
        content_sha256="a" * 64,
        created_at=created_at or NOW,
        policy_ref=policy.policy_ref,
        policy_version=policy.version,
        legal_hold_ref=legal_hold_ref,
    )


class RetentionTests(unittest.TestCase):
    def test_default_policy_defines_every_retained_data_class(self):
        self.assertEqual({rule.data_class for rule in DEFAULT_RETENTION_POLICY.rules}, set(RetainedDataClass))
        self.assertEqual(DEFAULT_RETENTION_POLICY.ttl_for(RetainedDataClass.INBOUND_MESSAGE_BODY), 30)
        self.assertEqual(DEFAULT_RETENTION_POLICY.ttl_for(RetainedDataClass.SOURCE_DOCUMENT), 90)
        self.assertGreater(DEFAULT_RETENTION_POLICY.ttl_for(RetainedDataClass.PILOT_AGGREGATE), 90)

    def test_keep_and_delete_due_are_deterministic_from_server_policy(self):
        item = record(created_at=NOW - timedelta(days=29))
        self.assertEqual(evaluate_retention(record=item, policy=DEFAULT_RETENTION_POLICY, now=NOW).disposition, RetentionDisposition.KEEP)
        due = record(created_at=NOW - timedelta(days=31))
        decision = evaluate_retention(record=due, policy=DEFAULT_RETENTION_POLICY, now=NOW)
        self.assertEqual(decision.disposition, RetentionDisposition.DELETE_DUE)

    def test_legal_hold_prevents_delete_due(self):
        item = record(created_at=NOW - timedelta(days=365), legal_hold_ref="legal_hold_1")
        decision = evaluate_retention(record=item, policy=DEFAULT_RETENTION_POLICY, now=NOW)
        self.assertEqual(decision.disposition, RetentionDisposition.LEGAL_HOLD)
        with self.assertRaises(ContractError):
            DeletionReceipt.attest(
                record=item,
                decision=decision,
                deleted_at=NOW,
                deletion_authority_ref="trusted:storage-service",
                evidence_ref="evidence:delete-1",
            )

    def test_deletion_receipt_requires_exact_due_decision_and_contains_hash_not_content(self):
        item = record(created_at=NOW - timedelta(days=31))
        decision = evaluate_retention(record=item, policy=DEFAULT_RETENTION_POLICY, now=NOW)
        receipt = DeletionReceipt.attest(
            record=item,
            decision=decision,
            deleted_at=NOW,
            deletion_authority_ref="trusted:storage-service",
            evidence_ref="evidence:delete-1",
        )
        safe = receipt.safe_dict()
        self.assertEqual(safe["deleted_content_sha256"], "a" * 64)
        self.assertFalse(safe["deleted_content_present"])
        self.assertNotIn("content", safe)
        keep_item = record(created_at=NOW)
        keep_decision = evaluate_retention(record=keep_item, policy=DEFAULT_RETENTION_POLICY, now=NOW)
        with self.assertRaises(ContractError):
            DeletionReceipt.attest(
                record=keep_item,
                decision=keep_decision,
                deleted_at=NOW,
                deletion_authority_ref="trusted:storage-service",
                evidence_ref="evidence:delete-2",
            )

    def test_policy_must_be_complete_unique_and_record_version_must_match(self):
        with self.assertRaises(ContractError):
            RetentionPolicy("bad_policy", 1, (RetentionRule(RetainedDataClass.SOURCE_DOCUMENT, 30),))
        duplicate = tuple(DEFAULT_RETENTION_POLICY.rules) + (DEFAULT_RETENTION_POLICY.rules[0],)
        with self.assertRaises(ContractError):
            RetentionPolicy("bad_policy", 1, duplicate)
        item = RetainedRecordMetadata(
            record_ref="record_1",
            workspace_id="ws_1",
            data_class=RetainedDataClass.SOURCE_DOCUMENT,
            content_sha256="a" * 64,
            created_at=NOW,
            policy_ref=DEFAULT_RETENTION_POLICY.policy_ref,
            policy_version=2,
        )
        with self.assertRaises(ContractError):
            evaluate_retention(record=item, policy=DEFAULT_RETENTION_POLICY, now=NOW)

    def test_model_credentials_hidden_reasoning_and_real_delete_are_not_supported(self):
        self.assertFalse(MODEL_DEFINED_RETENTION_SUPPORTED)
        self.assertFalse(REAL_STORAGE_DELETE_CONFIGURED)
        self.assertFalse(RAW_CREDENTIAL_RETENTION_CLASS_SUPPORTED)
        self.assertFalse(HIDDEN_REASONING_RETENTION_CLASS_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
