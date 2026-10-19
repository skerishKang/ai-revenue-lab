"""#3580 finish-first multi-adapter acceptance — SIMULATED provider E2E.

Run actual Padiem adapter code through trusted in-memory fakes:
native Docs/Sheets -> working copy -> PDF canonical artifact -> Telegram
sendDocument (stdlib real transport, fake HTTPS) OR Drive multipart create (fake
CP-authorized provider); XLSX -> Drive durable source -> Office fallback marker
-> PDF from fake Office renderer -> same Telegram connector path.

NEVER claim a real Office conversion, OAuth WRITE, Desktop filesystem access,
Production SEND or user-visible E2E based on these hermetic tests.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from unittest import TestCase
from unittest.mock import patch

import test_telegram_artifact_delivery as tg
import test_telegram_document_transport as tg_transport
import test_google_workspace_working_copy as work
import test_google_drive_artifact_upload as drive
from test_xlsx_fidelity_route import workbook, FORMULA_SHEET

from kagent.artifact_lineage import (
    LineageArtifactRef, declare_lineage,
)
from kagent.artifact_registration import (
    ArtifactLifecycle, register_canonical_artifact,
)
from kagent.google_drive_artifact_upload import DriveArtifactMaterial
from kagent.telegram_artifact_delivery import (
    TelegramArtifactMaterial, TelegramArtifactDeliveryError,
)
from kagent.telegram_document_transport import StdlibTelegramDocumentSendPort
from kagent.xlsx_fidelity_route import classify_xlsx, XlsxRoute


def native_pdf(*, kind="docs"):
    with patch.object(work, "SPACE", tg.WORKSPACE_REF), patch.object(
        work, "RUN", tg.RUN_REF
    ):
        app, provider = work.setup(kind)
        result = work.invoke(app, kind)
    assert result.output.workspace_ref == tg.WORKSPACE_REF
    assert result.output.run_ref == tg.RUN_REF
    assert result.lineage.output_artifact_ids == (result.output.artifact_id,)
    assert all(
        v.get("file_id") != work.SRC
        for name, v in provider.calls if name in ("docs_edit", "sheets_edit", "export")
    )
    return result, provider


def fake_telegram_send(pdf_record, pdf_bytes, *, tamper=False):
    """Real connector adapter + real stdlib multipart encoder, fake socket."""
    payload = pdf_bytes + b"tampered" if tamper else pdf_bytes
    material = tg._material(record=pdf_record, data=payload)
    adapter, _, binding, _ = tg._adapter(
        material=material, send=StdlibTelegramDocumentSendPort()
    )
    request = tg._request(record=pdf_record)
    socket = tg_transport.FakeConnection()
    with patch("kagent.telegram_document_transport.http.client.HTTPSConnection",
               return_value=socket), patch(
        "kagent.telegram_document_transport.ssl.create_default_context",
        return_value=object(),
    ):
        receipt = adapter.deliver(request)
    return receipt, socket, binding, request


def fake_drive_upload(pdf_record, pdf_bytes):
    """Real canonical artifact+scope+write-intent adapter, fake Drive provider."""
    md5 = hashlib.md5(pdf_bytes, usedforsecurity=False).hexdigest()
    response = drive.provider_result(
        name=pdf_record.filename, mimeType=pdf_record.media_type,
        size=str(len(pdf_bytes)), sha256Checksum=pdf_record.integrity_ref,
        md5Checksum=md5,
    )
    provider = drive.Upload(response=response)
    with patch.object(drive, "WORKSPACE", tg.WORKSPACE_REF), patch.object(
        drive, "RUN", tg.RUN_REF
    ):
        adapter, _, _, approval, _ = drive.driver(
            artifacts=drive.Material(
                item=DriveArtifactMaterial(pdf_record, pdf_bytes)),
            upload=provider,
        )
        output = adapter.create_output(
            artifact_ref=LineageArtifactRef(
                artifact_id=pdf_record.artifact_id,
                integrity_ref=pdf_record.integrity_ref,
            ),
            intent=drive.intent(pdf_record),
            workspace_ref=tg.WORKSPACE_REF, run_ref=tg.RUN_REF,
            now=drive.NOW,
        )
    return output, provider, approval


class Artifact3580FullChainTests(TestCase):
    def test_docs_source_copy_edit_pdf_to_actual_telegram_adapter_and_multipart(self):
        result, workspace_provider = native_pdf()
        receipt, socket, binding, request = fake_telegram_send(
            result.output, result.pdf_bytes
        )
        self.assertEqual(receipt.terminal_status.value, "succeeded")
        self.assertTrue(receipt.correlates_with(request))
        self.assertEqual(receipt.external_side_effect_count, 1)
        self.assertEqual(binding.token_calls, 1)
        self.assertEqual(binding.chat_id_calls, 1)
        self.assertEqual(len(socket.requests), 1)
        self.assertTrue(socket.closed)
        self.assertIn(result.pdf_bytes, socket.requests[0][2])
        self.assertEqual(socket.requests[0][0], "POST")
        self.assertEqual(
            [name for name, _ in workspace_provider.calls],
            ["copy", "revision", "docs_edit", "export"],
        )
        self.assertNotIn(
            tg.PROVIDER_TOKEN.decode(), str(receipt.public_projection())
        )

    def test_sheets_source_copy_raw_edit_pdf_to_real_drive_upload_adapter(self):
        result, provider = native_pdf(kind="sheets")
        upload_result, drive_provider, approval = fake_drive_upload(
            result.output, result.pdf_bytes
        )
        self.assertEqual(upload_result.artifact.lifecycle, ArtifactLifecycle.DURABLE)
        self.assertEqual(upload_result.artifact.integrity_ref,
                         result.output.integrity_ref)
        self.assertEqual(upload_result.artifact.durable_location.location_kind,
                         "google_drive")
        self.assertEqual([name for name,_ in provider.calls],
                         ["copy","sheets_edit","export"])
        self.assertEqual(len(drive_provider.calls), 1)
        self.assertEqual(len(approval.calls), 1)
        self.assertEqual(
            drive_provider.calls[0]["path"], "/upload/drive/v3/files"
        )
        self.assertIn(result.pdf_bytes, drive_provider.calls[0]["body"])
        self.assertNotIn(
            drive_provider.response["id"], str(upload_result.public_projection())
        )
        self.assertNotIn(
            result.pdf_bytes.decode(), str(upload_result.public_projection())
        )

    def test_native_pdf_integrity_tamper_blocks_telegram_network(self):
        result, _ = native_pdf()
        with self.assertRaises(TelegramArtifactDeliveryError):
            fake_telegram_send(result.output, result.pdf_bytes, tamper=True)

    def test_xlsx_drive_source_office_fallback_fixture_to_telegram(self):
        """E2E wiring proof with a *fake Office renderer*, not real conversion."""
        xlsx = workbook(sheet=FORMULA_SHEET)
        route = classify_xlsx(xlsx)
        self.assertIs(route.route, XlsxRoute.OFFICE_FALLBACK)
        self.assertEqual(route.execution_target, "ephemeral_office_renderer")
        self.assertFalse(route.may_automatically_convert)
        source = register_canonical_artifact(
            artifact_id="xlsx_original_drive_fixture",
            artifact_kind="source.xlsx",
            filename="원본 견적서.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=len(xlsx), integrity_ref=hashlib.sha256(xlsx).hexdigest(),
            workspace_ref=tg.WORKSPACE_REF, run_ref=tg.RUN_REF,
        )
        drive_output, port, _ = fake_drive_upload(source, xlsx)
        self.assertEqual(drive_output.artifact.lifecycle, ArtifactLifecycle.DURABLE)
        self.assertEqual(drive_output.artifact.integrity_ref, source.integrity_ref)
        self.assertIsNone(source.durable_location)
        self.assertEqual(len(port.calls), 1)
        self.assertNotIn("fileId", port.calls[0]["query"])

        # The Office engine is deliberately a fake, so this proves orchestration,
        # not XLSX fidelity or a real production backend.
        fake_office_pdf = b"%PDF-1.7\nfake office fallback only\n%%EOF\n"
        pdf = register_canonical_artifact(
            artifact_id="fallback_pdf_3580", artifact_kind="office.pdf",
            filename="견적서 결과.pdf", media_type="application/pdf",
            size_bytes=len(fake_office_pdf),
            integrity_ref=hashlib.sha256(fake_office_pdf).hexdigest(),
            workspace_ref=tg.WORKSPACE_REF, run_ref=tg.RUN_REF,
        )
        lineage = declare_lineage(
            lineage_id="xlsx-fallback-lineage",
            source=drive_output.artifact, transformation_kind="xlsx_office_fallback",
            workspace_ref=tg.WORKSPACE_REF, run_ref=tg.RUN_REF,
            created_at=datetime(2026,10,9,tzinfo=timezone.utc),
            working_representation_ref="ephemeral-office-verified-fixture",
            outputs=(pdf,),
        )
        self.assertEqual(lineage.source_integrity_ref, source.integrity_ref)
        self.assertEqual(lineage.output_integrity_refs, (pdf.integrity_ref,))
        receipt, socket, _, _ = fake_telegram_send(pdf, fake_office_pdf)
        self.assertEqual(receipt.terminal_status.value, "succeeded")
        self.assertIn(fake_office_pdf, socket.requests[0][2])
        self.assertEqual(len(socket.requests), 1)

    def test_unsafe_xlsx_archive_refuses_before_any_provider_port(self):
        invalid = b"PK\x03\x04forged"
        result = classify_xlsx(invalid)
        self.assertIs(result.route, XlsxRoute.REJECT)
        self.assertEqual(result.execution_target, "none")
        self.assertFalse(result.may_automatically_convert)
        self.assertNotIn("fileId", str(result.public_projection()))

    def test_local_file_route_rejects_cloud_implicit_path_reads(self):
        route = classify_xlsx(workbook(sheet=FORMULA_SHEET),
                              local_only=True)
        self.assertEqual(route.execution_target, "padiem_desktop_local_runner")
        self.assertFalse(route.google_conversion_verified)
        self.assertTrue(route.preserves_original)


if __name__ == "__main__":
    import unittest
    unittest.main()
