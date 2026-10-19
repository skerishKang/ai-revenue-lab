"""#3580 local-read->artifact->Drive source acceptance (no live provider calls)."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import tempfile
import unittest

import test_google_drive_artifact_upload as drive
from test_windows_local_filesystem import device

from kagent.artifact_lineage import LineageArtifactRef
from kagent.artifact_registration import ArtifactLifecycle
from kagent.contracts import ContractError
from kagent.google_drive_artifact_upload import DriveArtifactMaterial
from kagent.local_xlsx_artifact_handoff import (
    capture_local_xlsx_for_handoff, LocalXlsxArtifactHandoff,
    PRODUCTION_DESKTOP_MATERIAL_HANDOFF_WIRED,
)
from kagent.windows_local_filesystem import (
    DeterministicFakeWindowsFileAuthorizationPort,
    LocalFileOperation, LocalFileRequest, LocalFileResult,
    WindowsSelectedRootFileRuntime,
)
from kagent.xlsx_fidelity_route import XlsxRoute
from test_xlsx_fidelity_route import workbook, FORMULA_SHEET

DATA = workbook(sheet=FORMULA_SHEET)
NOW = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)


def request(*, operation=LocalFileOperation.READ, path=r"reports\quote.xlsx"):
    return LocalFileRequest(
        action_id="local_action_3580", run_id=drive.RUN,
        device_id="device_file_1", root_ref="repo",
        operation=operation, path_relative=path, requested_at=NOW,
    )


class FakeRuntime(WindowsSelectedRootFileRuntime):
    def __init__(self, *, payload=DATA, alter=None):
        self.payload, self.alter = payload, alter
        self.calls = []

    def perform(self, r, *, now):
        self.calls.append((r, now))
        digest = hashlib.sha256(self.payload).hexdigest()
        result = LocalFileResult(
            action_id=r.action_id, run_id=r.run_id,
            device_id=r.device_id, root_ref=r.root_ref,
            operation=LocalFileOperation.READ, path_relative=r.path_relative,
            completed_at=NOW, bytes_count=len(self.payload),
            content_sha256=digest, content=self.payload,
        )
        if self.alter == "wrong_run":
            result = LocalFileResult(
                action_id=r.action_id, run_id="wrong_run",
                device_id=r.device_id, root_ref=r.root_ref,
                operation=LocalFileOperation.READ, path_relative=r.path_relative,
                completed_at=NOW, bytes_count=len(self.payload),
                content_sha256=digest, content=self.payload,
            )
        return result


def capture(runtime=None, req=None):
    return capture_local_xlsx_for_handoff(
        runtime=runtime if runtime is not None else FakeRuntime(),
        request=req if req is not None else request(),
        now=NOW, workspace_ref=drive.WORKSPACE,
        artifact_id="local_xlsx_source_3580",
    )


class LocalXlsxArtifactHandoffTests(unittest.TestCase):
    def test_local_bytes_become_canonical_original_then_drive_durable_fake(self):
        original = bytes(DATA)
        handoff = capture()
        self.assertIsInstance(handoff, LocalXlsxArtifactHandoff)
        self.assertEqual(handoff.record.integrity_ref, hashlib.sha256(DATA).hexdigest())
        self.assertIs(handoff.route.route, XlsxRoute.OFFICE_FALLBACK)
        self.assertEqual(handoff.route.execution_target, "padiem_desktop_local_runner")
        self.assertFalse(handoff.route.may_automatically_convert)
        self.assertEqual(handoff.record.filename, "quote.xlsx")
        self.assertEqual(DATA, original)
        self.assertNotIn("reports", str(handoff.public_projection()))
        self.assertNotIn("device_file_1", str(handoff.public_projection()))
        self.assertFalse(handoff.public_projection()["raw_file_content"])
        self.assertFalse(PRODUCTION_DESKTOP_MATERIAL_HANDOFF_WIRED)

        record = handoff.record
        ref = LineageArtifactRef(record.artifact_id, record.integrity_ref)
        material = handoff.resolve_artifact_material(ref, workspace_ref=drive.WORKSPACE, run_ref=drive.RUN)
        self.assertIsInstance(material, DriveArtifactMaterial)
        self.assertEqual(material.content, DATA)
        md5 = hashlib.md5(DATA, usedforsecurity=False).hexdigest()
        provider = drive.Upload(response=drive.provider_result(
            name=record.filename, mimeType=record.media_type,
            size=str(len(DATA)), sha256Checksum=record.integrity_ref,
            md5Checksum=md5,
        ))
        adapter, _, _, approval, _ = drive.driver(artifacts=handoff, upload=provider)
        result = adapter.create_output(
            artifact_ref=ref, intent=drive.intent(record),
            workspace_ref=drive.WORKSPACE, run_ref=drive.RUN, now=drive.NOW,
        )
        self.assertEqual(result.artifact.lifecycle, ArtifactLifecycle.DURABLE)
        self.assertEqual(result.artifact.integrity_ref, record.integrity_ref)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(len(approval.calls), 1)
        self.assertIn(DATA, provider.calls[0]["body"])
        self.assertNotIn("reports", str(result.public_projection()))
        self.assertNotIn("win_device", str(result.public_projection()))

    def test_exact_artifact_workspace_run_ref_required(self):
        handoff = capture()
        ref = LineageArtifactRef(handoff.record.artifact_id, handoff.record.integrity_ref)
        self.assertIsNone(handoff.resolve_artifact_material(ref, workspace_ref="wrong", run_ref=drive.RUN))
        self.assertIsNone(handoff.resolve_artifact_material(ref, workspace_ref=drive.WORKSPACE, run_ref="wrong"))
        self.assertIsNone(handoff.resolve_artifact_material(
            LineageArtifactRef("wrong", handoff.record.integrity_ref),
            workspace_ref=drive.WORKSPACE, run_ref=drive.RUN,
        ))

    def test_corrupt_or_wrong_result_denied_without_material(self):
        with self.assertRaises(ContractError):
            capture(FakeRuntime(payload=b"PK\\x03\\x04untrusted"))
        with self.assertRaises(ContractError):
            capture(FakeRuntime(alter="wrong_run"))

    def test_non_xlsx_and_non_read_refused_before_disk_access(self):
        runtime = FakeRuntime()
        with self.assertRaises(ContractError):
            capture(runtime, request(path="reports\\notes.docx"))
        with self.assertRaises(ContractError):
            capture(runtime, request(operation=LocalFileOperation.DELETE))
        self.assertEqual(runtime.calls, [])


@unittest.skipUnless(os.name == "nt", "real physical local read is Windows first")
class WindowsPhysicalLocalXlsxHandoffTests(unittest.TestCase):
    def test_actual_windows_selected_root_read_preserves_original_and_exports_material(self):
        with tempfile.TemporaryDirectory() as root_dir:
            folder = Path(root_dir) / "reports"
            folder.mkdir()
            path = folder / "quote.xlsx"
            path.write_bytes(DATA)
            prior = hashlib.sha256(path.read_bytes()).hexdigest()
            runtime = WindowsSelectedRootFileRuntime(
                device=device(root_dir),
                authorization_port=DeterministicFakeWindowsFileAuthorizationPort(),
            )
            handoff = capture(runtime)
            self.assertEqual(handoff.record.integrity_ref, prior)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), prior)
            self.assertEqual(handoff.content, DATA)
            self.assertNotIn(str(path), str(handoff.public_projection()))


if __name__ == "__main__":
    unittest.main()
