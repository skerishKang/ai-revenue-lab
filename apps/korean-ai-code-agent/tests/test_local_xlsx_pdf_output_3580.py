"""#3580: local source bytes -> Office output -> PDF canonical Drive port.

Every default test is provider-free. The optional Windows Office canary must
be explicitly requested on a user's interactive local machine.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import io
import os
import unittest

import test_google_drive_artifact_upload as drive
from test_local_xlsx_artifact_handoff_3580 import capture
from test_xlsx_fidelity_route import workbook, SIMPLE_SHEET

from kagent.artifact_lineage import LineageArtifactRef
from kagent.contracts import ContractError
from kagent.local_xlsx_artifact_handoff import LocalXlsxArtifactHandoff
from kagent.local_xlsx_pdf_output import (
    LocalXlsxPdfOutput, PRODUCTION_OFFICE_RENDERER_COMPOSED,
    render_local_xlsx_pdf_output,
)
from kagent.windows_excel_pdf_renderer import (
    WindowsInteractiveExcelPdfRenderer, PRODUCTION_RENDERER_ACTIVATED,
)

NOW = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


class Renderer:
    def __init__(self, pdf=PDF):
        self.pdf = pdf
        self.calls = []

    def render_xlsx_pdf(self, data):
        self.calls.append(data)
        return self.pdf


def converted(source=None, renderer=None, **updates):
    r = renderer if renderer is not None else Renderer()
    s = source if source is not None else capture()
    args = dict(
        source=s, renderer=r,
        workspace_ref=drive.WORKSPACE, run_ref=drive.RUN,
        artifact_id="local_quote_pdf_3580",
        lineage_id="lineage_local_quote_3580",
        now=NOW,
    )
    args.update(updates)
    return render_local_xlsx_pdf_output(**args)


class LocalXlsxPdfOutputTests(unittest.TestCase):
    def test_office_output_has_canonical_pdf_and_unchanged_source(self):
        renderer = Renderer()
        source = capture()
        before = hashlib.sha256(source.content).hexdigest()
        result = converted(source, renderer)
        self.assertIsInstance(result, LocalXlsxPdfOutput)
        self.assertEqual(renderer.calls, [source.content])
        self.assertEqual(hashlib.sha256(source.content).hexdigest(), before)
        self.assertEqual(result.source_record.integrity_ref, before)
        self.assertEqual(result.record.media_type, "application/pdf")
        self.assertEqual(result.record.filename, "quote.pdf")
        self.assertEqual(result.record.integrity_ref, hashlib.sha256(PDF).hexdigest())
        self.assertEqual(result.lineage.source.artifact_id, source.record.artifact_id)
        self.assertEqual(result.lineage.outputs[0].artifact_id, result.record.artifact_id)
        self.assertNotIn("reports", str(result.public_projection()))
        self.assertNotIn("device_file_1", str(result.public_projection()))
        self.assertNotIn(str(PDF), str(result.public_projection()))
        self.assertFalse(PRODUCTION_OFFICE_RENDERER_COMPOSED)
        self.assertFalse(PRODUCTION_RENDERER_ACTIVATED)

    def test_pdf_bytes_connect_directly_to_existing_drive_adapter(self):
        artifact = converted()
        ref = LineageArtifactRef(artifact.record.artifact_id, artifact.record.integrity_ref)
        self.assertEqual(
            artifact.resolve_artifact_material(
                ref, workspace_ref=drive.WORKSPACE, run_ref=drive.RUN,
            ).content, PDF,
        )
        fake_provider = drive.Upload(response=drive.provider_result(
            name=artifact.record.filename,
            mimeType=artifact.record.media_type,
            size=str(len(PDF)),
            md5Checksum=hashlib.md5(PDF, usedforsecurity=False).hexdigest(),
            sha256Checksum=artifact.record.integrity_ref,
        ))
        adapter, _, _, approval, _ = drive.driver(
            artifacts=artifact, upload=fake_provider,
        )
        receipt = adapter.create_output(
            artifact_ref=ref, intent=drive.intent(artifact.record),
            workspace_ref=drive.WORKSPACE, run_ref=drive.RUN, now=drive.NOW,
        )
        self.assertEqual(receipt.artifact.integrity_ref, artifact.record.integrity_ref)
        self.assertEqual(len(fake_provider.calls), 1)
        self.assertEqual(len(approval.calls), 1)
        self.assertIn(PDF, fake_provider.calls[0]["body"])

    def test_mismatched_source_ref_is_denied_before_renderer(self):
        renderer = Renderer()
        for wrong in (
            dict(workspace_ref="foreign_workspace"),
            dict(run_ref="foreign_run"),
        ):
            with self.subTest(wrong=wrong), self.assertRaises(ContractError):
                converted(renderer=renderer, **wrong)
        self.assertEqual(renderer.calls, [])

    def test_corrupted_bytes_denied_before_renderer(self):
        r = Renderer()
        modified = replace(capture(), content=b"not original")
        with self.assertRaises(ContractError):
            converted(modified, r)
        self.assertEqual(r.calls, [])

    def test_mutated_route_denied_before_renderer(self):
        r = Renderer()
        original = capture()
        # Real route decision comes from OOXML, not a caller-selected flag.
        from kagent.xlsx_fidelity_route import classify_xlsx
        mutated_route = classify_xlsx(workbook(sheet=SIMPLE_SHEET), local_only=True)
        self.assertNotEqual(original.route, mutated_route)
        with self.assertRaises(ContractError):
            converted(replace(original, route=mutated_route), r)
        self.assertEqual(r.calls, [])

    def test_wrong_renderer_port_denied(self):
        with self.assertRaises(ContractError):
            converted(renderer=object())

    def test_invalid_and_oversized_pdf_denied(self):
        for bad in (b"", b"bogus", b"%PDF-1.4\nbroken", PDF + b"x" * (8*1024*1024)):
            with self.subTest(size=len(bad)), self.assertRaises(ContractError):
                converted(renderer=Renderer(bad))

    def test_wrong_scope_or_bytes_never_exposed_to_drive(self):
        artifact = converted()
        ref = LineageArtifactRef(artifact.record.artifact_id, artifact.record.integrity_ref)
        self.assertIsNone(artifact.resolve_artifact_material(
            ref, workspace_ref="wrong", run_ref=drive.RUN,
        ))
        self.assertIsNone(artifact.resolve_artifact_material(
            ref, workspace_ref=drive.WORKSPACE, run_ref="wrong",
        ))
        self.assertIsNone(replace(artifact, content=b"changed").resolve_artifact_material(
            ref, workspace_ref=drive.WORKSPACE, run_ref=drive.RUN,
        ))
        self.assertIsNone(artifact.resolve_artifact_material(
            LineageArtifactRef("wrong_id", artifact.record.integrity_ref),
            workspace_ref=drive.WORKSPACE, run_ref=drive.RUN,
        ))


@unittest.skipUnless(
    os.name == "nt" and os.environ.get("PADIEM_LOCAL_EXCEL_CANARY") == "1",
    "explicit opt-in on licensed Windows interactive Excel only",
)
class RealInteractiveExcelSmokeTests(unittest.TestCase):
    def test_excel_com_exports_formula_pdf_and_preserves_xlsx(self):
        try:
            from openpyxl import Workbook
            import fitz
        except ImportError:
            self.skipTest("optional Excel canary dependencies not installed")
        book = Workbook()
        sheet = book.active
        sheet.title = "Quote"
        sheet["A1"] = "Quote"
        sheet["A2"] = 3
        sheet["B2"] = 5
        sheet["C2"] = "=A2*B2"
        buffer = io.BytesIO()
        book.save(buffer)
        original = buffer.getvalue()
        pdf = WindowsInteractiveExcelPdfRenderer().render_xlsx_pdf(original)
        self.assertEqual(buffer.getvalue(), original)
        doc = fitz.open(stream=pdf, filetype="pdf")
        try:
            self.assertGreaterEqual(len(doc), 1)
            extracted = "".join(page.get_text() for page in doc)
            self.assertIn("Quote", extracted)
            self.assertIn("15", extracted)
        finally:
            doc.close()


if __name__ == "__main__":
    unittest.main()
