"""B54 compatibility: the product envelope projects onto the shared Core primitive.

These tests do not replace the B54 in-memory journal (product lifecycle stays
product-owned). They pin the promoted-lane contract: every
``ProductCommandEnvelope`` material field maps onto
``padiem_ai_core.product_command_identity`` and the shared primitive reproduces
the exact-duplicate / conflicting-replay semantics the B54 journal guarantees,
without minting authority.
"""

from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import replace
from datetime import datetime, timezone
import unittest

from kagent.application_commands import (
    ProductCommandEnvelope,
    ProductCommandKind,
)
from kagent.contracts import ContractError

from padiem_ai_core.execution_context import IdempotencyConflictError
from padiem_ai_core.product_command_identity import (
    ProductCommandIdempotency,
    ProductCommandIdentity,
    ProductCommandReservationOutcome,
    product_command_material_fingerprint,
)

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


def project(envelope: ProductCommandEnvelope) -> ProductCommandIdentity:
    return ProductCommandIdentity(
        workspace_id=envelope.workspace_id,
        command_id=envelope.command_id,
        idempotency_key=envelope.idempotency_key,
        kind=envelope.kind.value,
        subject_ref=envelope.subject_ref,
        subject_version=envelope.subject_version,
        payload_sha256=envelope.payload_sha256,
        session_ref=envelope.trusted_session_ref,
        requested_at=envelope.requested_at,
    )


class SharedDurableIdempotencyAdapter:
    """Test double speaking the exact Core IdempotencyAdapter protocol."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict] = {}
        self.inserts = 0

    async def begin(self, *, app_id, idempotency_key, request_fingerprint):
        record = self.records.get((app_id, idempotency_key))
        if record is not None:
            if record["request_fingerprint"] != request_fingerprint:
                raise IdempotencyConflictError("conflicting product command replay")
            if record["state"] == "completed":
                return dict(record["result"])
            raise IdempotencyConflictError("product command already in flight")
        self.inserts += 1
        self.records[(app_id, idempotency_key)] = {
            "state": "reserved",
            "request_fingerprint": request_fingerprint,
            "result": None,
        }
        return None

    async def complete(self, *, app_id, idempotency_key, request_fingerprint, result):
        record = self.records[(app_id, idempotency_key)]
        record["state"] = "completed"
        record["result"] = dict(result)


class ProductCommandProjectionCompatibilityTests(unittest.TestCase):
    def test_envelope_material_maps_losslessly_to_shared_identity(self):
        envelope = command()
        identity = project(envelope)
        self.assertEqual(identity.kind, ProductCommandKind.START_CLOUD_RUN.value)
        self.assertEqual(identity.session_ref, envelope.trusted_session_ref)
        self.assertEqual(identity.payload_sha256, envelope.payload_sha256)
        self.assertEqual(identity.requested_at, envelope.requested_at)
        field_names = {field.name for field in dataclasses.fields(identity)}
        self.assertNotIn("raw_payload", field_names)
        self.assertNotIn("payload", field_names)

    def test_material_divergence_between_envelopes_diverges_in_shared_fingerprint(self):
        base = command()
        self.assertEqual(
            product_command_material_fingerprint(project(base)),
            product_command_material_fingerprint(project(command())),
        )
        self.assertNotEqual(
            product_command_material_fingerprint(project(base)),
            product_command_material_fingerprint(project(replace(base, payload_sha256="b" * 64))),
        )
        self.assertNotEqual(
            product_command_material_fingerprint(project(base)),
            product_command_material_fingerprint(project(replace(base, workspace_id="ws_2"))),
        )

    def test_journal_conflict_rules_reproduced_on_shared_primitive(self):
        adapter = SharedDurableIdempotencyAdapter()
        service = ProductCommandIdempotency(adapter=adapter, app_id="b54")
        envelope = command()

        first = asyncio.run(service.reserve(project(envelope)))
        self.assertIs(first.outcome, ProductCommandReservationOutcome.ACCEPTED)

        with self.assertRaises(IdempotencyConflictError):
            asyncio.run(service.reserve(project(replace(envelope, payload_sha256="b" * 64))))
        with self.assertRaises(IdempotencyConflictError):
            asyncio.run(service.reserve(project(command(command_id="command_2", payload_sha256="c" * 64))))

        asyncio.run(service.complete(first.identity, result={"result_ref": "result_1"}))
        replay = asyncio.run(service.reserve(project(envelope)))
        self.assertIs(replay.outcome, ProductCommandReservationOutcome.REPLAY)
        self.assertEqual(replay.replay_result, {"result_ref": "result_1"})
        self.assertEqual(adapter.inserts, 1)
        public = replay.to_public_dict()
        self.assertFalse(public["authorization_granted"])
        self.assertFalse(public["approval_minted"])

    def test_b54_journal_semantics_unchanged_after_projection_exists(self):
        from kagent.application_commands import InMemoryProductCommandJournal, ProductCommandStatus

        journal = InMemoryProductCommandJournal()
        envelope = command()
        record = journal.receive(envelope)
        self.assertEqual(journal.receive(envelope), record)
        journal.transition(
            "command_1",
            status=ProductCommandStatus.DISPATCHED,
            updated_at=NOW.replace(minute=14),
        )
        with self.assertRaises(ContractError):
            journal.receive(replace(envelope, payload_sha256="d" * 64))


if __name__ == "__main__":
    unittest.main()
