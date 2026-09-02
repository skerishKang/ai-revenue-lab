from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from kagent.application_commands import (
    COMMAND_ENVELOPE_APPROVAL_MINTING_SUPPORTED,
    COMMAND_ENVELOPE_AUTHORIZATION_SUPPORTED,
    RAW_COMMAND_PAYLOAD_SUPPORTED,
    REAL_API_SERVER_CONFIGURED,
    InMemoryProductCommandJournal,
    ProductCommandEnvelope,
    ProductCommandKind,
    ProductCommandStatus,
)
from kagent.contracts import ContractError

NOW = datetime(2026, 9, 3, 13, 0, tzinfo=timezone.utc)


def command(**changes):
    values = dict(
        command_id="command_1",
        idempotency_key="idem_1",
        trusted_session_ref="session_1",
        workspace_id="ws_1",
        kind=ProductCommandKind.START_CLOUD_RUN,
        subject_ref="run_1",
        subject_version=1,
        payload_sha256="a" * 64,
        requested_at=NOW,
    )
    values.update(changes)
    return ProductCommandEnvelope(**values)


class ApplicationCommandTests(unittest.TestCase):
    def test_exact_replay_is_idempotent(self):
        journal = InMemoryProductCommandJournal()
        first = journal.receive(command())
        replay = journal.receive(command())
        self.assertEqual(first, replay)
        self.assertEqual(first.status, ProductCommandStatus.RECEIVED)

    def test_conflicting_command_or_idempotency_replay_is_rejected(self):
        journal = InMemoryProductCommandJournal()
        original = command()
        journal.receive(original)
        with self.assertRaises(ContractError):
            journal.receive(replace(original, payload_sha256="b" * 64))
        with self.assertRaises(ContractError):
            journal.receive(command(command_id="command_2", payload_sha256="c" * 64))

    def test_lifecycle_is_bounded_and_terminal_cannot_resurrect(self):
        journal = InMemoryProductCommandJournal()
        journal.receive(command())
        dispatched = journal.transition("command_1", status=ProductCommandStatus.DISPATCHED, updated_at=NOW + timedelta(seconds=1))
        self.assertEqual(dispatched.status, ProductCommandStatus.DISPATCHED)
        completed = journal.transition("command_1", status=ProductCommandStatus.COMPLETED, updated_at=NOW + timedelta(seconds=2), result_ref="result_1")
        self.assertEqual(completed.status, ProductCommandStatus.COMPLETED)
        with self.assertRaises(ContractError):
            journal.transition("command_1", status=ProductCommandStatus.DISPATCHED, updated_at=NOW + timedelta(seconds=3))

    def test_failure_requires_bounded_code_and_is_terminal(self):
        journal = InMemoryProductCommandJournal()
        journal.receive(command())
        failed = journal.transition("command_1", status=ProductCommandStatus.FAILED, updated_at=NOW + timedelta(seconds=1), failure_code="policy_denied")
        self.assertEqual(failed.status, ProductCommandStatus.FAILED)
        with self.assertRaises(ContractError):
            journal.transition("command_1", status=ProductCommandStatus.DISPATCHED, updated_at=NOW + timedelta(seconds=2))

    def test_envelope_contains_hash_not_raw_payload_and_grants_no_authority(self):
        safe = command().safe_dict()
        self.assertFalse(safe["raw_payload"])
        self.assertFalse(safe["authorization_granted"])
        self.assertFalse(safe["approval_minted"])
        self.assertFalse(RAW_COMMAND_PAYLOAD_SUPPORTED)
        self.assertFalse(COMMAND_ENVELOPE_AUTHORIZATION_SUPPORTED)
        self.assertFalse(COMMAND_ENVELOPE_APPROVAL_MINTING_SUPPORTED)
        self.assertFalse(REAL_API_SERVER_CONFIGURED)


if __name__ == "__main__":
    unittest.main()
