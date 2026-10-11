"""Private Engine Drive case-folder RPC tests (#3190).

Network-free. Proves the Service Binding RPC seam: closed payloads per
operation, bounded errors, no public fetch route, and no raw refs in responses.
"""

from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from padiem_ai_core.drive_capability import DriveCapability
from padiem_ai_core.drive_case_folder_scope import GOOGLE_FOLDER_MIME

from app.connector_bindings import DRIVE_AGENT_ID, DRIVE_REFERENCE_APP_ID, DriveGrant
from app.drive_case_folder_binding import (
    DriveCaseFolderBindingAuthority,
    InMemoryDriveCaseFolderBindingStore,
)
from app.drive_case_folder_rpc import (
    DRIVE_CASE_FOLDER_RPC_OPERATIONS,
    OPERATION_PATHS,
    drive_case_folder_rpc,
    drive_case_folder_rpc_snapshot,
)
from app.drive_case_folder_service import DriveCaseFolderEngineService

WORKSPACE_REF = "ws_alpha_001"
PROJECT_ID = "proj_" + "a" * 32
BINDING_REF = "bind:drive_alpha"
FOLDER_ID = "folder_case_001"

FOLDER_METADATA = {
    "id": FOLDER_ID,
    "name": "사건자료",
    "mimeType": GOOGLE_FOLDER_MIME,
    "version": 3,
    "parents": ["root_folder"],
    "modifiedTime": "2026-09-01T00:00:00Z",
    "trashed": False,
}


def run(coro):
    return asyncio.run(coro)


class FakeGrantProvider:
    async def current_drive_grant(self, *, workspace_ref: str) -> DriveGrant | None:
        del workspace_ref
        return DriveGrant(
            app_id=DRIVE_REFERENCE_APP_ID,
            canonical_agent_id=DRIVE_AGENT_ID,
            binding_ref=BINDING_REF,
            actor_ref="actor_1",
            granted_capabilities=(DriveCapability.READ,),
        )


class FakeDrivePort:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def get_json(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        path = kwargs.get("path")
        if isinstance(path, str) and path.startswith("/files/"):
            return FOLDER_METADATA
        return {"files": [FOLDER_METADATA]}

    def get_text(self, **kwargs: object) -> str:
        raise AssertionError("selection never reads content")


def service() -> DriveCaseFolderEngineService:
    return DriveCaseFolderEngineService(
        grant_provider=FakeGrantProvider(),
        drive_port=FakeDrivePort(),
        binding_authority=DriveCaseFolderBindingAuthority(
            store=InMemoryDriveCaseFolderBindingStore()
        ),
    )


def call(operation: str, payload: object, *, svc: object = ...):
    service_obj = service() if svc is ... else svc
    return run(drive_case_folder_rpc(service_obj, operation=operation, payload=payload))


# --- 1. operations --------------------------------------------------------


def test_all_four_operations_are_registered() -> None:
    assert set(OPERATION_PATHS) == set(DRIVE_CASE_FOLDER_RPC_OPERATIONS)
    payloads = {
        "drive_case_folder_status": {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID},
        "drive_case_folder_folders": {
            "workspace_ref": WORKSPACE_REF,
            "project_id": PROJECT_ID,
            "query": "사건",
        },
        "drive_case_folder_select": {
            "workspace_ref": WORKSPACE_REF,
            "project_id": PROJECT_ID,
            "folder_id": FOLDER_ID,
        },
        "drive_case_folder_clear": {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID},
    }
    for operation, payload in payloads.items():
        response = call(operation, payload)
        assert response["ok"] is True, operation


def test_status_clear_select_round_trip() -> None:
    svc = service()
    status = call("drive_case_folder_status", {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID}, svc=svc)
    assert status["ok"] is True and status["status"]["configured"] is False

    selected = call(
        "drive_case_folder_select",
        {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "folder_id": FOLDER_ID},
        svc=svc,
    )
    assert selected["ok"] is True and selected["outcome"] == "created"

    configured = call("drive_case_folder_status", {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID}, svc=svc)
    assert configured["status"]["configured"] is True

    cleared = call("drive_case_folder_clear", {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID}, svc=svc)
    assert cleared["ok"] is True and cleared["cleared"] is True


def test_folders_returns_bounded_candidates() -> None:
    response = call("drive_case_folder_folders", {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID})
    assert response["ok"] is True
    assert [item["folder_id"] for item in response["folders"]] == [FOLDER_ID]
    assert response["exhaustive"] is False


# --- 2. closed payload + bounded errors -----------------------------------


def test_unknown_operation_is_not_found() -> None:
    response = call("drive_case_folder_delete_everything", {})
    assert response["ok"] is False
    assert response["error"]["code"] == "not_found"


def test_error_envelope_is_uniform() -> None:
    for operation, payload in (
        ("drive_case_folder_nope", {}),
        ("drive_case_folder_status", {}),
        ("drive_case_folder_status", {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "extra": 1}),
    ):
        response = call(operation, payload)
        assert set(response) == {"ok", "error"}, operation
        assert response["ok"] is False
        error = response["error"]
        assert set(error) == {"code", "message", "retryable", "metadata"}, operation
        assert isinstance(error["retryable"], bool)
        assert error["metadata"] is None
        assert isinstance(error["message"], str) and error["message"]


def test_missing_service_error_is_uniform() -> None:
    response = call("drive_case_folder_status", {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID}, svc=None)
    assert set(response) == {"ok", "error"}
    assert set(response["error"]) == {"code", "message", "retryable", "metadata"}


def test_caller_authority_fields_are_rejected() -> None:
    for field in ("binding_ref", "workspace_ref_claim", "app_id", "actor_ref", "scope"):
        payload = {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, field: "x"}
        response = call("drive_case_folder_status", payload)
        assert response["ok"] is False, field
        assert response["error"]["code"] == "invalid_request", field


def test_missing_service_fails_closed() -> None:
    response = call("drive_case_folder_status", {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID}, svc=None)
    assert response["ok"] is False
    assert response["error"]["code"] == "drive_case_folder_unavailable"


def test_non_object_payload_is_rejected() -> None:
    response = run(drive_case_folder_rpc(service(), operation="drive_case_folder_status", payload="nope"))
    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_request"


# --- 3. response safety ---------------------------------------------------


def test_responses_never_echo_raw_refs() -> None:
    selected = call(
        "drive_case_folder_select",
        {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "folder_id": FOLDER_ID},
    )
    rendered = json.dumps(selected)
    for secret in (BINDING_REF, WORKSPACE_REF, PROJECT_ID, FOLDER_ID):
        assert secret not in rendered
    folders = call("drive_case_folder_folders", {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID})
    assert BINDING_REF not in json.dumps(folders)
    assert WORKSPACE_REF not in json.dumps(folders)


def test_rpc_snapshot_is_service_binding_only() -> None:
    snapshot = drive_case_folder_rpc_snapshot()
    assert snapshot["public_fetch_route"] is False
    assert snapshot["service_binding_only"] is True
    assert snapshot["returns_raw_refs"] is False
    assert len(snapshot["operations"]) == 4


def test_worker_exposes_rpc_methods_not_fetch_routes() -> None:
    pytest.importorskip("workers")
    import worker

    entrypoint = worker.Default
    for operation in DRIVE_CASE_FOLDER_RPC_OPERATIONS:
        assert callable(getattr(entrypoint, operation, None)), operation
    # the internal paths must not be public fetch routes
    source = pathlib.Path(worker.__file__).read_text(encoding="utf-8")
    for path in OPERATION_PATHS.values():
        assert path not in source, "internal Drive path must not be a public fetch route"
