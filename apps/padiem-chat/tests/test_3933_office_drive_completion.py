"""#3580/#3933: real canonical Office bytes -> fake approved Drive -> SQLite D1.

One pair of new XLSX/PDF files is registered only after a completed owner run.
This is NOT a Production OAuth, Office COM, or consent demonstration.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from hashlib import md5, sha256
from io import BytesIO
import unittest

from openpyxl import Workbook

from app.history import D1HistoryStore
from app.claw_durable_drive_output_pipeline import (
    ClawDurableDriveOutputPipeline, DurableArtifactCompletionError,
)
from app.claw_office_drive_completion import ClawOfficeDriveCompletion
from kagent.artifact_registration import register_canonical_artifact
from kagent.artifact_lineage import declare_lineage
from kagent.connector_trust import ConnectorWriteIntent
from kagent.google_drive_artifact_upload import (
    GoogleDriveArtifactUploadAdapter, upload_payload_fingerprint,
)
from kagent.local_xlsx_artifact_handoff import LocalXlsxArtifactHandoff
from kagent.local_xlsx_revision_pdf import LocalRevisedXlsxPdf
from kagent.xlsx_fidelity_route import classify_xlsx

from test_3929_claw_conversation_artifact_d1 import (
    D1Sqlite, setup_database, OWNER, FOREIGN, CHAT, WORKSPACE, RUN, RUN2,
)
from test_3929_claw_drive_output_registration import (
    ports, PDF, NOW, BINDING, ACTOR, FOLDER,
)

MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def actual_office_outputs():
    book = Workbook()
    book.active.title = "Quote"
    book.active["A1"] = "Existing School"
    book.active["B2"] = 88_000_000
    book.active["B3"] = "=B2*0.1"
    before = BytesIO()
    book.save(before)
    source_data = before.getvalue()
    source = register_canonical_artifact(
        artifact_id="office_source_3580", artifact_kind="source.xlsx",
        filename="quote.xlsx", media_type=MIME,
        size_bytes=len(source_data), integrity_ref=sha256(source_data).hexdigest(),
        workspace_ref=WORKSPACE, run_ref=RUN,
    )
    handoff = LocalXlsxArtifactHandoff(
        record=source, content=source_data,
        route=classify_xlsx(source_data, local_only=True),
    )
    book.active["A1"] = "New School"
    book.active["B2"] = 99_200_000
    after = BytesIO()
    book.save(after)
    updated = after.getvalue()
    working = register_canonical_artifact(
        artifact_id="office_working_3580", artifact_kind="working.xlsx",
        filename="quote_revised.xlsx", media_type=MIME,
        size_bytes=len(updated), integrity_ref=sha256(updated).hexdigest(),
        workspace_ref=WORKSPACE, run_ref=RUN,
        source_ref="artifact/" + source.artifact_id,
    )
    pdf = register_canonical_artifact(
        artifact_id="office_pdf_3580", artifact_kind="output.pdf",
        filename="quote_revised.pdf", media_type="application/pdf",
        size_bytes=len(PDF), integrity_ref=sha256(PDF).hexdigest(),
        workspace_ref=WORKSPACE, run_ref=RUN,
        source_ref="artifact/" + working.artifact_id,
    )
    lineage = declare_lineage(
        lineage_id="lineage_office_3580",
        source=source, working=working, outputs=(pdf,),
        transformation_kind="xlsx.revise.office_pdf",
        workspace_ref=WORKSPACE, run_ref=RUN, created_at=NOW,
    )
    return LocalRevisedXlsxPdf(
        source=handoff, revised=working, pdf=pdf,
        lineage=lineage, revised_bytes=updated, pdf_bytes=PDF,
    )


class TwoFileProvider:
    def __init__(self, outputs, fail_pdf=False):
        self.outputs = outputs
        self.fail_pdf = fail_pdf
        self.calls = 0

    def create_file_multipart(self, **kwargs):
        self.calls += 1
        record, data = (
            (self.outputs.revised, self.outputs.revised_bytes)
            if self.calls == 1 else (self.outputs.pdf, self.outputs.pdf_bytes)
        )
        if self.fail_pdf and self.calls == 2:
            raise RuntimeError("simulated Google failure (must not be exposed)")
        return {
            "id": "provider_file_" + str(self.calls),
            "name": record.filename, "mimeType": record.media_type,
            "parents": [FOLDER], "version": "1", "size": str(len(data)),
            "md5Checksum": md5(data, usedforsecurity=False).hexdigest(),
            "sha256Checksum": sha256(data).hexdigest(),
            "trashed": False,
        }


class OfficeDriveCompletionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = setup_database()
        self.history = D1HistoryStore(D1Sqlite(self.db))
        self.outputs = actual_office_outputs()
        adapter, _, _, _, approval = ports()
        self.approval = approval
        self.provider = TwoFileProvider(self.outputs)
        trusted = GoogleDriveArtifactUploadAdapter(
            binding=adapter._binding, scope=adapter._scope,
            artifacts=self.outputs, folders=adapter._folders,
            approval=self.approval, upload=self.provider,
        )
        self.completion = ClawOfficeDriveCompletion(
            pipeline=ClawDurableDriveOutputPipeline(
                history=self.history, uploader=trusted,
            )
        )
        self.xlsx_intent = self.intent(self.outputs.revised, "xlsx")
        self.pdf_intent = self.intent(self.outputs.pdf, "pdf")

    def tearDown(self):
        self.db.close()

    def intent(self, record, suffix):
        return ConnectorWriteIntent(
            connector_id="google-drive",
            binding_ref=BINDING, actor_ref=ACTOR,
            tool_name="upload_file", target_ref=FOLDER,
            payload_fingerprint=upload_payload_fingerprint(
                artifact=record, folder_ref=FOLDER,
            ),
            idempotency_key="idem_office_" + suffix,
            approval_ref="approval_office_" + suffix,
            evidence_ref="evidence_office_" + suffix,
            requested_at=NOW,
        )

    def kwargs(self, **overrides):
        data = dict(
            owner_id=OWNER, conversation_id=CHAT,
            workspace_ref=WORKSPACE, run_ref=RUN,
            outputs=self.outputs,
            xlsx_intent=self.xlsx_intent, pdf_intent=self.pdf_intent, now=NOW,
        )
        data.update(overrides)
        return data

    async def test_actual_canonical_xlsx_pdf_both_registered_after_approved_upload(self):
        result = await self.completion.upload_completed_revision(**self.kwargs())
        self.assertEqual(self.provider.calls, 2)
        self.assertEqual(self.approval.calls, 2)
        self.assertTrue(result.public_projection()["both_indexed"])
        self.assertFalse(result.public_projection()["pdf_fidelity_attested"])
        rows = await self.history.list_owner_conversation_artifacts(
            user_id=OWNER, conversation_id=CHAT,
            workspace_ref=WORKSPACE, limit=31,
        )
        self.assertEqual(
            {row["artifact_id"] for row in rows},
            {self.outputs.revised.artifact_id, self.outputs.pdf.artifact_id},
        )
        self.assertEqual(
            {row["integrity_ref"] for row in rows},
            {self.outputs.revised.integrity_ref, self.outputs.pdf.integrity_ref},
        )
        self.assertNotIn("provider_file_", str(result.public_projection()))

    async def test_preflight_all_material_and_intents_before_first_write(self):
        wrong_intent = replace(self.pdf_intent, payload_fingerprint="0"*64)
        for override in (
            {"outputs": replace(self.outputs, pdf_bytes=PDF + b"tampered")},
            {"outputs": replace(self.outputs, lineage=replace(
                self.outputs.lineage, run_ref="other_run"
            )},
            {"pdf_intent": wrong_intent},
            {"pdf_intent": replace(self.pdf_intent, idempotency_key="idem_office_xlsx")},
            {"pdf_intent": replace(self.pdf_intent, approval_ref="approval_office_xlsx")},
            {"workspace_ref": "other_workspace"},
            {"run_ref": RUN2},
        ):
            with self.subTest(override=tuple(override)):
                with self.assertRaises(DurableArtifactCompletionError):
                    await self.completion.upload_completed_revision(**self.kwargs(**override))
        self.assertEqual(self.provider.calls, 0)
        self.assertEqual(self.approval.calls, 0)

    async def test_foreign_owner_or_noncompleted_run_no_upload(self):
        with self.assertRaises(DurableArtifactCompletionError):
            await self.completion.upload_completed_revision(
                **self.kwargs(owner_id=FOREIGN)
            )
        self.assertEqual(self.provider.calls, 0)

    async def test_second_upload_failure_does_not_claim_pair_or_replay_first(self):
        self.provider.fail_pdf = True
        with self.assertRaises(Exception):
            await self.completion.upload_completed_revision(**self.kwargs())
        self.assertEqual(self.provider.calls, 2)
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM claw_conversation_artifact_index"
        ).fetchone()[0], 1)
        with self.assertRaises(Exception):
            await self.completion.upload_completed_revision(**self.kwargs())
        self.assertEqual(self.provider.calls, 2)


if __name__ == "__main__":
    unittest.main()
