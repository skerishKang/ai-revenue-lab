"""B67 Chat -> Engine selected-folder PDF seam tests (#3355)."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

from app.drive_case_folder_engine import (
    PDF_CANDIDATES_OPERATION,
    PDF_READ_OPERATION,
    CloudflareDriveCaseFolderEngineClient,
    DriveCaseFolderEngineError,
    drive_case_folder_engine_seam_snapshot,
)

WORKSPACE_REF = "ws_alpha_001"
PROJECT_ID = "proj_" + "a" * 32
FILE_ID = "file_pdf_001"
PDF_BYTES = b"%PDF-1.7\nsynthetic\n%%EOF\n"


def run(coro):
    return asyncio.run(coro)


class FakeEngineBinding:
    def __init__(self, responses: dict | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, dict]] = []

    async def drive_case_folder_status(self, payload):
        return {"ok": True, "status": {"configured": False, "space_kind": None, "scope_token": None, "updated_at": None}, "contract_version": "v1"}

    async def drive_case_folder_folders(self, payload):
        return {"ok": True, "folders": [], "more": False, "exhaustive": False, "contract_version": "v1"}

    async def drive_case_folder_select(self, payload):
        return {"ok": True, "outcome": "created", "status": {"configured": True, "space_kind": "my_drive", "updated_at": None}, "contract_version": "v1"}

    async def drive_case_folder_clear(self, payload):
        return {"ok": True, "cleared": True}

    async def b67_case_pdf_candidates(self, payload):
        self.calls.append((PDF_CANDIDATES_OPERATION, dict(payload)))
        return self.responses.get(PDF_CANDIDATES_OPERATION, candidates_response())

    async def b67_case_pdf_read(self, payload):
        self.calls.append((PDF_READ_OPERATION, dict(payload)))
        return self.responses.get(PDF_READ_OPERATION, read_response())


class FolderOnlyBinding:
    async def drive_case_folder_status(self, payload):
        return {"ok": True, "status": {"configured": False, "space_kind": None, "scope_token": None, "updated_at": None}, "contract_version": "v1"}

    async def drive_case_folder_folders(self, payload):
        return {"ok": True, "folders": [], "more": False, "exhaustive": False, "contract_version": "v1"}

    async def drive_case_folder_select(self, payload):
        return {"ok": True, "outcome": "created", "status": {"configured": True, "space_kind": "my_drive", "updated_at": None}, "contract_version": "v1"}

    async def drive_case_folder_clear(self, payload):
        return {"ok": True, "cleared": True}


def file_projection():
    return {
        "file_id": FILE_ID,
        "name": "소장.pdf",
        "mime_type": "application/pdf",
        "size_bytes": len(PDF_BYTES),
        "modified_time": "2026-10-01T00:00:00Z",
        "space_kind": "my_drive",
        "intake_state": "browser_pdf_ready",
    }


def candidates_response():
    return {
        "ok": True,
        "files": [file_projection()],
        "more": False,
        "direct_child_only": True,
        "contract_version": "engine-b67-case-pdf.v1",
    }


def read_response():
    return {
        "ok": True,
        "file": file_projection(),
        "content_base64": base64.b64encode(PDF_BYTES).decode("ascii"),
        "byte_size": len(PDF_BYTES),
        "version_evidence": {
            "version": "v-1",
            "modified_time": "2026-10-01T00:00:00Z",
            "md5_checksum": None,
            "sha256_checksum": "a" * 64,
            "head_revision_id": None,
        },
        "authorization": {"direct_parent_proof": True, "source_type": "drive"},
        "contract_version": "engine-b67-case-pdf.v1",
    }


def test_pdf_candidates_uses_fixed_private_rpc_and_bounded_query():
    binding = FakeEngineBinding()
    client = CloudflareDriveCaseFolderEngineClient(binding)
    body = run(client.pdf_candidates(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID, query=" 소장 "))
    assert body["files"][0]["file_id"] == FILE_ID
    assert body["direct_child_only"] is True
    assert binding.calls == [
        (
            PDF_CANDIDATES_OPERATION,
            {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "query": "소장"},
        )
    ]


def test_pdf_read_validates_payload_and_preserves_version_evidence():
    binding = FakeEngineBinding()
    client = CloudflareDriveCaseFolderEngineClient(binding)
    body = run(client.read_pdf(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID, file_id=FILE_ID))
    assert base64.b64decode(body["content_base64"], validate=True) == PDF_BYTES
    assert body["byte_size"] == len(PDF_BYTES)
    assert body["version_evidence"]["sha256_checksum"] == "a" * 64
    assert body["authorization"] == {"direct_parent_proof": True, "source_type": "drive"}
    assert binding.calls[-1] == (
        PDF_READ_OPERATION,
        {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "file_id": FILE_ID},
    )


def test_folder_only_binding_remains_constructible_but_pdf_fails_closed():
    client = CloudflareDriveCaseFolderEngineClient(FolderOnlyBinding())
    with pytest.raises(DriveCaseFolderEngineError) as excinfo:
        run(client.pdf_candidates(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID))
    assert excinfo.value.code == "drive_case_pdf_unavailable"
    assert excinfo.value.status_code == 503


def test_pdf_candidate_extra_field_is_denied():
    bad = candidates_response()
    bad["files"][0]["resource_key"] = "must-not-cross"
    client = CloudflareDriveCaseFolderEngineClient(FakeEngineBinding({PDF_CANDIDATES_OPERATION: bad}))
    with pytest.raises(DriveCaseFolderEngineError) as excinfo:
        run(client.pdf_candidates(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID))
    assert excinfo.value.code == "drive_case_pdf_response_invalid"


def test_pdf_read_rejects_invalid_base64_and_signature():
    bad = read_response()
    bad["content_base64"] = base64.b64encode(b"not-a-pdf").decode("ascii")
    bad["byte_size"] = len(b"not-a-pdf")
    client = CloudflareDriveCaseFolderEngineClient(FakeEngineBinding({PDF_READ_OPERATION: bad}))
    with pytest.raises(DriveCaseFolderEngineError):
        run(client.read_pdf(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID, file_id=FILE_ID))


def test_pdf_engine_error_is_bounded_without_raw_text():
    bad = {
        "ok": False,
        "error": {
            "code": "execution_fallback_required",
            "message": "raw provider internal detail",
            "retryable": False,
            "metadata": None,
        },
    }
    client = CloudflareDriveCaseFolderEngineClient(FakeEngineBinding({PDF_READ_OPERATION: bad}))
    with pytest.raises(DriveCaseFolderEngineError) as excinfo:
        run(client.read_pdf(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID, file_id=FILE_ID))
    assert excinfo.value.status_code == 413
    assert "raw provider internal detail" not in str(excinfo.value)


def test_pdf_client_never_returns_workspace_or_project_refs():
    client = CloudflareDriveCaseFolderEngineClient(FakeEngineBinding())
    rendered = json.dumps(run(client.read_pdf(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID, file_id=FILE_ID)))
    assert WORKSPACE_REF not in rendered
    assert PROJECT_ID not in rendered
    assert "resource_key" not in rendered


def test_seam_snapshot_declares_pdf_ops_without_second_binding():
    snapshot = drive_case_folder_engine_seam_snapshot()
    assert snapshot["pdf_operations"] == [PDF_CANDIDATES_OPERATION, PDF_READ_OPERATION]
    assert snapshot["binding_name"]
    assert snapshot["browser_selects_endpoint"] is False
