"""#3330/#3580: verified ticket→existing Drive WRITE→real D1 owner index.

Only the Drive provider is a fake; approval, exact artifact bytes, owner-run
pre/post proof, D1 registration and output contracts are the existing source.
No Production call or model dispatch.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import unittest

from padiem_ai_core.drive_capability import DriveFileProjection
from padiem_ai_core.drive_index_freshness import DriveIndexSourceSnapshot
from padiem_ai_core.ephemeral_work_ticket import EphemeralExecutionWorkTicket

from app.claw_durable_drive_output_pipeline import ClawDurableDriveOutputPipeline
from app.claw_drive_ticket_output_composition import (
    TicketOutputCompositionError,
    upload_completed_output_with_verified_ticket,
)
from app.history import D1HistoryStore

from kagent.artifact_lineage import LineageArtifactRef

from test_3929_claw_conversation_artifact_d1 import (
    D1Sqlite, setup_database, OWNER, FOREIGN, CHAT, WORKSPACE, OTHER_WORKSPACE,
    RUN,
)
from test_3929_claw_drive_output_registration import (
    ARTIFACT_ID, SHA, NOW, FOLDER, ports,
)


def _current(*, file_id="original_source_3330", version=7):
    return DriveFileProjection(
        file_id=file_id,
        name="original.pdf",
        mime_type="application/pdf",
        version=version,
    )


class CanonicalTicketToDriveOutputTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = setup_database()
        self.history = D1HistoryStore(D1Sqlite(self.db))
        self.adapter, self.intent, self.record, self.provider, self.approval = ports()
        self.pipeline = ClawDurableDriveOutputPipeline(
            history=self.history, uploader=self.adapter
        )
        self.source = _current()
        self.ticket = EphemeralExecutionWorkTicket(
            run_ref=RUN,
            owner_ref=OWNER,
            workspace_ref=WORKSPACE,
            capability="document.export_pdf",
            mode="produce_artifact",
            inputs=(DriveIndexSourceSnapshot.from_projection(self.source),),
            output_folder_ref=FOLDER,
            issued_at=NOW - timedelta(minutes=2),
            expires_at=NOW + timedelta(minutes=2),
        )

    def tearDown(self):
        self.db.close()

    def params(self, **overrides):
        data = dict(
            pipeline=self.pipeline, ticket=self.ticket,
            current_sources=(self.source,),
            owner_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE,
            run_ref=RUN,
            artifact_ref=LineageArtifactRef(ARTIFACT_ID, SHA),
            source_record=self.record,
            intent=self.intent, now=NOW,
        )
        data.update(overrides)
        return data

    async def _refused(self, **overrides):
        with self.assertRaises(TicketOutputCompositionError):
            await upload_completed_output_with_verified_ticket(
                **self.params(**overrides)
            )
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.approval.calls, 0)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM claw_conversation_artifact_index"
        ).fetchone()[0], 0)

    async def test_owner_ticket_and_fresh_drive_version_compose_real_d1_artifact_write(self):
        result = await upload_completed_output_with_verified_ticket(**self.params())
        self.assertTrue(result.stored_in_conversation_index)
        self.assertEqual(result.artifact_id, ARTIFACT_ID)
        self.assertEqual(self.provider.calls, 1)
        self.assertEqual(self.approval.calls, 1)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM claw_conversation_artifact_index"
        ).fetchone()[0], 1)

    async def test_foreign_owner_and_workspace_refused_before_provider_write(self):
        await self._refused(owner_id=FOREIGN)
        await self._refused(workspace_ref=OTHER_WORKSPACE)
        await self._refused(run_ref="run_foreign")

    async def test_write_target_must_match_exact_approved_intent(self):
        ticket = replace(self.ticket, output_folder_ref="different_folder_3330")
        await self._refused(ticket=ticket)

    async def test_expired_ticket_refuses_before_write(self):
        await self._refused(now=NOW + timedelta(minutes=2))

    async def test_stale_drive_version_refuses_even_when_file_id_matches(self):
        await self._refused(current_sources=(_current(version=8),))
        await self._refused(current_sources=(_current(file_id="other_input"),))

    async def test_absent_or_untrusted_drive_metadata_fails_closed(self):
        await self._refused(current_sources=())
        await self._refused(current_sources=({"file_id": "original_source_3330"},))
        await self._refused(current_sources=None)

    async def test_ticket_does_not_replace_p01_owner_or_write_approval(self):
        self.approval.allowed = False
        with self.assertRaises(Exception):
            await upload_completed_output_with_verified_ticket(**self.params())
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.approval.calls, 1)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM claw_conversation_artifact_index"
        ).fetchone()[0], 0)
