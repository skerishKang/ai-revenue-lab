"""#3580: trusted Worker private Broker RPC rebuilds real Office PDF bytes.

Uses owner-scoped actual SQLite D1 origin/command correlation and a fake
Service Binding. No Google Drive, model calls or public byte endpoint.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import unittest

from app.claw_local_office_binary_reader import (
    BrokerOfficeBinaryReader, OfficeBinaryReadRefused, OFFICE_CHUNK_BYTES,
)
from app.claw_local_task_result_composition import LocalRunnerResultSource
from test_3580_local_office_origin_bridge import (
    LocalOfficeOriginTests, FakeCanonicalBroker, CORR,
)
from test_3929_claw_conversation_artifact_d1 import OWNER, FOREIGN, RUN, WORKSPACE

PDF = b"%PDF-1.4\n" + b"X" * (OFFICE_CHUNK_BYTES + 50) + b"\n%%EOF\n"


class PrivateBroker:
    def __init__(self, data=PDF):
        self.data = data
        self.calls = 0
        self.changed = False
        self.missing = False

    async def read_office_artifact_part(self, payload):
        self.calls += 1
        if self.missing:
            return {"ok": False, "error": {"code": "office_artifact_unavailable"}}
        if payload != {
            "owner": OWNER, "workspace": WORKSPACE, "run_id": RUN,
            "command_id": CORR["command_id"], "kind": "pdf",
            "part_index": payload["part_index"],
        }:
            return {"ok": False, "error": {"code": "office_artifact_unavailable"}}
        index = payload["part_index"]
        piece = self.data[index*OFFICE_CHUNK_BYTES:(index+1)*OFFICE_CHUNK_BYTES]
        if not piece:
            return {"ok": False, "error": {"code": "office_artifact_unavailable"}}
        digest = sha256(self.data).hexdigest()
        if self.changed and index == 1:
            digest = "a" * 64
        return {"ok": True, "artifact_part": {
            "contract_version": "claw-office-artifact-read.v1",
            "artifact_id": "artifact_private_pdf_3580",
            "filename": "verified.pdf",
            "media_type": "application/pdf",
            "size_bytes": len(self.data),
            "integrity_ref": digest,
            "part_index": index,
            "part_count": (len(self.data)+OFFICE_CHUNK_BYTES-1)//OFFICE_CHUNK_BYTES,
            "data_b64": base64.b64encode(piece).decode("ascii"),
        }}


class BoundBroker(FakeCanonicalBroker):
    def __init__(self, binding):
        super().__init__()
        self._binding = binding


class OwnerScopedPrivateOfficeReadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await LocalOfficeOriginTests.asyncSetUp(self)
        self.private = PrivateBroker()
        self.broker = BoundBroker(self.private)
        self.source = LocalRunnerResultSource(
            history=self.fixture.history, result_port=self.broker,
        )

    async def asyncTearDown(self):
        await LocalOfficeOriginTests.asyncTearDown(self)

    async def test_real_private_binary_roundtrip(self):
        file = await self.source.read_staged_office_output(
            owner_id=OWNER, run_ref=RUN, kind="pdf",
        )
        self.assertEqual(file.content, PDF)
        self.assertEqual(file.integrity_ref, sha256(PDF).hexdigest())
        self.assertEqual(file.size_bytes, len(PDF))
        self.assertEqual(self.private.calls, 2)
        self.assertNotIn("data_b64", file.public_projection())
        self.assertFalse(file.public_projection()["drive_write_approval"])

    async def test_other_owner_denied_before_private_read(self):
        with self.assertRaises(OfficeBinaryReadRefused):
            await self.source.read_staged_office_output(
                owner_id=FOREIGN, run_ref=RUN, kind="pdf",
            )
        self.assertEqual(self.private.calls, 0)

    async def test_absent_part_refused_without_partial_bytes(self):
        self.private.missing = True
        with self.assertRaises(OfficeBinaryReadRefused):
            await self.source.read_staged_office_output(
                owner_id=OWNER, run_ref=RUN, kind="pdf",
            )

    async def test_midstream_metadata_mutation_refused(self):
        self.private.changed = True
        with self.assertRaises(OfficeBinaryReadRefused):
            await self.source.read_staged_office_output(
                owner_id=OWNER, run_ref=RUN, kind="pdf",
            )

    async def test_untrusted_broker_failure_or_correlation_mismatch_refused(self):
        self.broker.fact = None
        with self.assertRaises(OfficeBinaryReadRefused):
            await self.source.read_staged_office_output(
                owner_id=OWNER, run_ref=RUN, kind="pdf",
            )
        self.assertEqual(self.private.calls, 0)

    async def test_missing_private_binding_capability_refuses(self):
        source = LocalRunnerResultSource(
            history=self.fixture.history, result_port=FakeCanonicalBroker(),
        )
        with self.assertRaises(OfficeBinaryReadRefused):
            await source.read_staged_office_output(
                owner_id=OWNER, run_ref=RUN, kind="pdf",
            )


if __name__ == "__main__":
    unittest.main()
