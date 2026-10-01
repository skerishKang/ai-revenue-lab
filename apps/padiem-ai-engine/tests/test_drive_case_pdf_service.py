from __future__ import annotations

import asyncio
import base64
import json
import pathlib

import pytest

from padiem_ai_core.drive_capability import DriveCapability
from padiem_ai_core.drive_case_folder_scope import DriveCaseResource, GOOGLE_FOLDER_MIME

from app.connector_bindings import DRIVE_AGENT_ID, DRIVE_REFERENCE_APP_ID, DriveGrant
from app.drive_case_folder_binding import (
    DriveCaseFolderBindingAuthority,
    InMemoryDriveCaseFolderBindingStore,
)
from app.drive_case_pdf_rpc import (
    B67_CASE_PDF_RPC_OPERATIONS,
    CANDIDATES_OPERATION,
    READ_OPERATION,
    drive_case_pdf_rpc,
    drive_case_pdf_rpc_snapshot,
)
from app.drive_case_pdf_service import (
    MAX_B67_CASE_PDF_BYTES,
    DriveCasePdfService,
    drive_case_pdf_service_snapshot,
)

WORKSPACE_REF = "ws_legal_001"
PROJECT_ID = "proj_" + "b" * 32
BINDING_REF = "bind:legal_drive"
FOLDER_ID = "folder_case_001"
FILE_ID = "pdf_case_001"
PDF_BYTES = b"%PDF-1.7\ncase evidence\n%%EOF"

FOLDER_METADATA = {
    "id": FOLDER_ID,
    "name": "Case Folder",
    "mimeType": GOOGLE_FOLDER_MIME,
    "parents": ["root"],
    "trashed": False,
    "version": 1,
}

PDF_METADATA = {
    "id": FILE_ID,
    "name": "brief.pdf",
    "mimeType": "application/pdf",
    "parents": [FOLDER_ID],
    "trashed": False,
    "version": 7,
    "modifiedTime": "2026-10-01T00:00:00Z",
    "size": len(PDF_BYTES),
}


def run(coro):
    return asyncio.run(coro)


def grant(binding_ref: str = BINDING_REF) -> DriveGrant:
    return DriveGrant(
        app_id=DRIVE_REFERENCE_APP_ID,
        canonical_agent_id=DRIVE_AGENT_ID,
        binding_ref=binding_ref,
        actor_ref="actor_legal",
        granted_capabilities=(DriveCapability.READ,),
    )


class FakeGrantProvider:
    def __init__(self, value: DriveGrant | None = None) -> None:
        self.value = grant() if value is None else value
        self.calls: list[str] = []

    async def current_drive_grant(self, *, workspace_ref: str):
        self.calls.append(workspace_ref)
        return self.value


class FakeDrivePort:
    def __init__(
        self,
        *,
        files: list[dict] | None = None,
        metadata: dict | None = None,
        content: bytes = PDF_BYTES,
    ) -> None:
        self.files = list(files if files is not None else [PDF_METADATA])
        self.metadata = dict(metadata if metadata is not None else PDF_METADATA)
        self.content = content
        self.calls: list[tuple[str, dict]] = []

    def get_json(self, **kwargs):
        self.calls.append(("json", dict(kwargs)))
        if kwargs["path"] == "/files":
            return {"files": list(self.files)}
        return dict(self.metadata)

    def get_bytes(self, **kwargs):
        self.calls.append(("bytes", dict(kwargs)))
        return self.content


async def make_service(
    *,
    port: FakeDrivePort | None = None,
    current_grant: DriveGrant | None = None,
    selected_shared_drive: str | None = None,
) -> tuple[DriveCasePdfService, FakeDrivePort, FakeGrantProvider, DriveCaseFolderBindingAuthority]:
    active_grant = current_grant or grant()
    provider = FakeGrantProvider(active_grant)
    selected_metadata = dict(FOLDER_METADATA)
    if selected_shared_drive is not None:
        selected_metadata["driveId"] = selected_shared_drive
    selected = DriveCaseResource.from_provider(
        binding_ref=active_grant.binding_ref,
        metadata=selected_metadata,
    )
    authority = DriveCaseFolderBindingAuthority(
        store=InMemoryDriveCaseFolderBindingStore()
    )
    await authority.bind_selected_folder(
        workspace_ref=WORKSPACE_REF,
        project_id=PROJECT_ID,
        drive_grant=active_grant,
        selected_resource=selected,
    )
    drive_port = port or FakeDrivePort()
    service = DriveCasePdfService(
        grant_provider=provider,
        drive_port=drive_port,
        binding_authority=authority,
    )
    return service, drive_port, provider, authority


def test_candidates_are_parent_constrained_pdf_only_and_bounded() -> None:
    service, port, provider, _ = run(make_service())
    body = run(
        service.candidates(
            workspace_ref=WORKSPACE_REF,
            project_id=PROJECT_ID,
            query="termination",
        )
    )
    assert body["ok"] is True
    assert body["direct_child_only"] is True
    assert len(body["files"]) == 1
    item = body["files"][0]
    assert item["file_id"] == FILE_ID
    assert item["mime_type"] == "application/pdf"
    assert item["intake_state"] == "browser_pdf_ready"
    assert provider.calls == [WORKSPACE_REF]
    kind, call = port.calls[0]
    assert kind == "json"
    assert call["path"] == "/files"
    assert f"'{FOLDER_ID}' in parents" in call["query"]["q"]
    assert "mimeType = 'application/pdf'" in call["query"]["q"]
    assert "termination" in call["query"]["q"]
    assert call["required_scopes"] == ("https://www.googleapis.com/auth/drive.readonly",)


def test_read_refetches_metadata_then_returns_exact_bounded_pdf_bytes() -> None:
    service, port, _, _ = run(make_service())
    body = run(
        service.read(
            workspace_ref=WORKSPACE_REF,
            project_id=PROJECT_ID,
            file_id=FILE_ID,
        )
    )
    assert body["ok"] is True
    assert base64.b64decode(body["content_base64"]) == PDF_BYTES
    assert body["byte_size"] == len(PDF_BYTES)
    assert body["authorization"]["direct_parent_proof"] is True
    assert [kind for kind, _ in port.calls] == ["json", "bytes"]
    assert port.calls[0][1]["path"].endswith("/files/" + FILE_ID)
    assert port.calls[1][1]["query"] == {"alt": "media", "supportsAllDrives": "true"}
    assert port.calls[1][1]["max_response_bytes"] == MAX_B67_CASE_PDF_BYTES


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({**PDF_METADATA, "parents": ["other_folder"]}, "drive_parent_contract_failed"),
        ({**PDF_METADATA, "mimeType": "text/plain"}, "not_pdf"),
        ({**PDF_METADATA, "trashed": True}, "drive_case_folder_scope_denied"),
        (
            {
                **PDF_METADATA,
                "mimeType": "application/vnd.google-apps.shortcut",
                "shortcutDetails": {
                    "targetId": FILE_ID,
                    "targetMimeType": "application/pdf",
                },
            },
            "drive_case_folder_scope_denied",
        ),
    ],
)
def test_denials_happen_before_any_pdf_bytes(metadata: dict, expected: str) -> None:
    port = FakeDrivePort(metadata=metadata)
    service, port, _, _ = run(make_service(port=port))
    with pytest.raises(Exception) as caught:
        run(
            service.read(
                workspace_ref=WORKSPACE_REF,
                project_id=PROJECT_ID,
                file_id=FILE_ID,
            )
        )
    assert getattr(caught.value, "code", None) == expected
    assert [kind for kind, _ in port.calls] == ["json"]


def test_oversize_pdf_requires_execution_fallback_before_bytes() -> None:
    metadata = {**PDF_METADATA, "size": MAX_B67_CASE_PDF_BYTES + 1}
    port = FakeDrivePort(metadata=metadata)
    service, port, _, _ = run(make_service(port=port))
    with pytest.raises(Exception) as caught:
        run(
            service.read(
                workspace_ref=WORKSPACE_REF,
                project_id=PROJECT_ID,
                file_id=FILE_ID,
            )
        )
    assert getattr(caught.value, "code", None) == "execution_fallback_required"
    assert [kind for kind, _ in port.calls] == ["json"]


def test_missing_or_zero_size_is_not_downloaded() -> None:
    metadata = {**PDF_METADATA}
    metadata.pop("size")
    port = FakeDrivePort(metadata=metadata)
    service, port, _, _ = run(make_service(port=port))
    with pytest.raises(Exception) as caught:
        run(
            service.read(
                workspace_ref=WORKSPACE_REF,
                project_id=PROJECT_ID,
                file_id=FILE_ID,
            )
        )
    assert getattr(caught.value, "code", None) == "pdf_size_unverifiable"
    assert [kind for kind, _ in port.calls] == ["json"]


def test_shared_drive_mismatch_denies_before_bytes() -> None:
    metadata = {**PDF_METADATA, "driveId": "shared_other"}
    port = FakeDrivePort(metadata=metadata)
    service, port, _, _ = run(
        make_service(port=port, selected_shared_drive="shared_selected")
    )
    with pytest.raises(Exception) as caught:
        run(
            service.read(
                workspace_ref=WORKSPACE_REF,
                project_id=PROJECT_ID,
                file_id=FILE_ID,
            )
        )
    assert getattr(caught.value, "code", None) == "drive_case_folder_scope_denied"
    assert [kind for kind, _ in port.calls] == ["json"]


def test_binding_drift_denies_before_provider_read() -> None:
    service, port, provider, authority = run(make_service())
    provider.value = grant("bind:new_drive")
    with pytest.raises(Exception) as caught:
        run(
            service.read(
                workspace_ref=WORKSPACE_REF,
                project_id=PROJECT_ID,
                file_id=FILE_ID,
            )
        )
    assert getattr(caught.value, "code", None) == "drive_binding_drift"
    assert port.calls == []


def test_content_size_and_signature_integrity_fail_closed() -> None:
    for payload, expected in (
        (PDF_BYTES + b"x", "pdf_integrity_mismatch"),
        (b"NOTPDF" + PDF_BYTES[6:], "pdf_signature_mismatch"),
    ):
        metadata = {**PDF_METADATA, "size": len(payload)}
        port = FakeDrivePort(metadata=metadata, content=payload)
        service, _, _, _ = run(make_service(port=port))
        with pytest.raises(Exception) as caught:
            run(
                service.read(
                    workspace_ref=WORKSPACE_REF,
                    project_id=PROJECT_ID,
                    file_id=FILE_ID,
                )
            )
        assert getattr(caught.value, "code", None) == expected


def test_rpc_is_closed_private_and_does_not_accept_authority_fields() -> None:
    service, _, _, _ = run(make_service())
    candidates = run(
        drive_case_pdf_rpc(
            service,
            operation=CANDIDATES_OPERATION,
            payload={"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID},
        )
    )
    assert candidates["ok"] is True

    pdf = run(
        drive_case_pdf_rpc(
            service,
            operation=READ_OPERATION,
            payload={
                "workspace_ref": WORKSPACE_REF,
                "project_id": PROJECT_ID,
                "file_id": FILE_ID,
            },
        )
    )
    assert pdf["ok"] is True

    for forbidden in ("binding_ref", "actor_ref", "drive_grant", "selected_folder_id"):
        denied = run(
            drive_case_pdf_rpc(
                service,
                operation=READ_OPERATION,
                payload={
                    "workspace_ref": WORKSPACE_REF,
                    "project_id": PROJECT_ID,
                    "file_id": FILE_ID,
                    forbidden: "forged",
                },
            )
        )
        assert denied["ok"] is False
        assert denied["error"]["code"] == "invalid_request"


def test_rpc_missing_service_and_unknown_operation_fail_closed() -> None:
    missing = run(
        drive_case_pdf_rpc(
            None,
            operation=READ_OPERATION,
            payload={"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "file_id": FILE_ID},
        )
    )
    assert missing["error"]["code"] == "drive_case_pdf_unavailable"
    unknown = run(drive_case_pdf_rpc(None, operation="b67_pdf_delete", payload={}))
    assert unknown["error"]["code"] == "not_found"


def test_worker_exposes_private_rpc_methods_not_public_fetch_paths() -> None:
    pytest.importorskip("workers")
    import worker

    for operation in B67_CASE_PDF_RPC_OPERATIONS:
        assert callable(getattr(worker.Default, operation, None)), operation
    source = pathlib.Path(worker.__file__).read_text(encoding="utf-8")
    assert "/api/b67" not in source
    assert "/internal/v1/b67" not in source


def test_service_and_rpc_snapshots_lock_authority_posture() -> None:
    service = drive_case_pdf_service_snapshot()
    assert service["direct_child_only"] is True
    assert service["generic_drive_binary_tool"] is False
    assert service["canonical_selected_folder_authority_reused"] is True
    assert service["canonical_workspace_grant_reused"] is True
    assert service["cp_access_lease_reused"] is True
    assert service["file_id_is_selection_intent"] is True
    assert service["metadata_refetch_before_bytes"] is True
    assert service["raw_refresh_token"] is False
    assert service["drive_write"] is False
    assert service["public_fetch_route"] is False
    assert service["production_mutation"] is False

    rpc = drive_case_pdf_rpc_snapshot()
    assert rpc["service_binding_only"] is True
    assert rpc["public_fetch_route"] is False
    assert rpc["browser_drive_authority"] is False
    assert rpc["raw_credentials_present"] is False
