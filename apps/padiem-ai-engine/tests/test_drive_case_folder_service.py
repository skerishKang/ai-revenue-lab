"""Drive case-folder Engine service tests (#3190, parent #3138).

Network-free. Proves the private Engine contract: server-resolved current Drive
grant, browser folder id treated as intent only (always re-fetched), real-folder
validation before persistence, bounded candidates, and fail-closed dependencies.
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
from app.drive_case_folder_service import (
    CLEAR_PATH,
    FOLDERS_PATH,
    SELECT_PATH,
    STATUS_PATH,
    DriveCaseFolderEngineService,
    drive_case_folder_service_snapshot,
)

WORKSPACE_REF = "ws_alpha_001"
PROJECT_ID = "proj_" + "a" * 32
BINDING_REF = "bind:drive_alpha"
FOLDER_ID = "folder_case_001"
FILE_ID = "file_inside_003"
SHORTCUT_ID = "shortcut_1"
SHARED_DRIVE = "shared_drive_009"
GOOGLE_SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

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


def drive_grant() -> DriveGrant:
    return DriveGrant(
        app_id=DRIVE_REFERENCE_APP_ID,
        canonical_agent_id=DRIVE_AGENT_ID,
        binding_ref=BINDING_REF,
        actor_ref="actor_1",
        granted_capabilities=(DriveCapability.READ,),
    )


class FakeGrantProvider:
    def __init__(self, grant: DriveGrant | None) -> None:
        self.grant = grant
        self.calls = 0

    async def current_drive_grant(self) -> DriveGrant | None:
        self.calls += 1
        return self.grant


class FakeDrivePort:
    """Records provider calls and returns configured canonical metadata."""

    def __init__(self, *, metadata: dict | None = None, files: list[dict] | None = None) -> None:
        self.metadata = metadata
        self.files = files if files is not None else []
        self.calls: list[dict] = []

    def get_json(self, **kwargs: object) -> dict:
        self.calls.append(kwargs)
        path = kwargs.get("path")
        if isinstance(path, str) and path.startswith("/files/"):
            if self.metadata is None:
                raise ValueError("provider_http_404")
            return self.metadata
        return {"files": list(self.files)}

    def get_text(self, **kwargs: object) -> str:
        raise AssertionError("the folder-selection service never reads content")

    @property
    def metadata_calls(self) -> list[dict]:
        return [call for call in self.calls if str(call.get("path", "")).startswith("/files/")]


class CountingBindingStore(InMemoryDriveCaseFolderBindingStore):
    def __init__(self) -> None:
        super().__init__()
        self.upsert_calls = 0

    async def upsert_active(self, row) -> None:  # type: ignore[override]
        self.upsert_calls += 1
        await super().upsert_active(row)


class Harness:
    def __init__(self, *, grant: DriveGrant | None = None, metadata: dict | None = None, files: list[dict] | None = None, port: object | None = None) -> None:
        self.store = CountingBindingStore()
        self.authority = DriveCaseFolderBindingAuthority(store=self.store)
        self.grant_provider = FakeGrantProvider(grant if grant is not None else drive_grant())
        self.port = port if port is not None else FakeDrivePort(metadata=metadata, files=files)
        self.service = DriveCaseFolderEngineService(
            grant_provider=self.grant_provider,
            drive_port=self.port,
            binding_authority=self.authority,
        )

    def post(self, path: str, payload: dict, *, content_type: str = "application/json", method: str = "POST"):
        return run(
            self.service.handle(
                method=method,
                path=path,
                content_type=content_type,
                body=json.dumps(payload).encode("utf-8"),
            )
        )


def error_code(response) -> str | None:
    body = response.body
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return error.get("code")
    return None


# --- 1. happy path: status -> candidates -> select -> clear ---------------


def test_status_without_binding_is_not_configured() -> None:
    harness = Harness()
    response = harness.post(STATUS_PATH, {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID})
    assert response.status_code == 200
    assert response.body["status"]["configured"] is False


def test_recent_folder_candidates_are_folder_only_and_bounded() -> None:
    files = [
        FOLDER_METADATA,
        {"id": FILE_ID, "name": "계약서.txt", "mimeType": "text/plain", "version": 1, "trashed": False},
        {"id": "trashed_1", "name": "휴지통", "mimeType": GOOGLE_FOLDER_MIME, "version": 1, "trashed": True},
        {
            "id": SHORTCUT_ID,
            "name": "바로가기",
            "mimeType": GOOGLE_SHORTCUT_MIME,
            "version": 1,
            "trashed": False,
            "shortcutDetails": {"targetId": FOLDER_ID, "targetMimeType": GOOGLE_FOLDER_MIME},
        },
    ]
    harness = Harness(files=files)
    response = harness.post(FOLDERS_PATH, {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID})
    assert response.status_code == 200
    folders = response.body["folders"]
    assert [item["folder_id"] for item in folders] == [FOLDER_ID]
    assert folders[0]["name"] == "사건자료"
    assert folders[0]["space_kind"] == "my_drive"
    assert set(folders[0]) == {"folder_id", "name", "space_kind", "modified_time"}
    assert response.body["exhaustive"] is False


def test_search_folder_candidates_use_the_canonical_search_handler() -> None:
    harness = Harness(files=[FOLDER_METADATA])
    response = harness.post(
        FOLDERS_PATH, {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "query": "사건"}
    )
    assert response.status_code == 200
    list_calls = [call for call in harness.port.calls if "q" in call.get("query", {})]
    assert any("name contains" in call["query"]["q"] for call in list_calls)


def test_select_folder_refetches_provider_metadata_and_persists() -> None:
    harness = Harness(metadata=FOLDER_METADATA)
    response = harness.post(
        SELECT_PATH,
        {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "folder_id": FOLDER_ID},
    )
    assert response.status_code == 200
    assert response.body["outcome"] == "created"
    # the intent id was re-fetched from the trusted Drive port under the grant
    assert harness.port.metadata_calls
    assert f"/files/{FOLDER_ID}" in str(harness.port.metadata_calls[0]["path"])
    assert harness.store.upsert_calls == 1

    status = harness.post(STATUS_PATH, {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID})
    assert status.body["status"]["configured"] is True
    assert status.body["status"]["space_kind"] == "my_drive"

    cleared = harness.post(CLEAR_PATH, {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID})
    assert cleared.status_code == 200 and cleared.body["cleared"] is True
    assert harness.post(STATUS_PATH, {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID}).body["status"][
        "configured"
    ] is False


def test_status_projection_is_product_safe() -> None:
    harness = Harness(metadata=FOLDER_METADATA)
    harness.post(SELECT_PATH, {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "folder_id": FOLDER_ID})
    status = harness.post(STATUS_PATH, {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID})
    rendered = json.dumps(status.body)
    assert FOLDER_ID not in rendered
    assert BINDING_REF not in rendered
    assert WORKSPACE_REF not in rendered


# --- 2. selection intent is never authority -------------------------------


def test_non_folder_selection_is_denied_without_durable_write() -> None:
    harness = Harness(metadata={"id": FILE_ID, "name": "계약서.txt", "mimeType": "text/plain", "version": 1, "trashed": False})
    response = harness.post(
        SELECT_PATH, {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "folder_id": FILE_ID}
    )
    assert response.status_code == 422
    assert error_code(response) == "non_folder_selection"
    assert harness.store.upsert_calls == 0


def test_shortcut_selection_is_denied() -> None:
    harness = Harness(
        metadata={
            "id": SHORTCUT_ID,
            "name": "바로가기",
            "mimeType": GOOGLE_SHORTCUT_MIME,
            "version": 1,
            "trashed": False,
            "shortcutDetails": {"targetId": FOLDER_ID, "targetMimeType": GOOGLE_FOLDER_MIME},
        }
    )
    response = harness.post(
        SELECT_PATH, {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "folder_id": SHORTCUT_ID}
    )
    assert response.status_code == 422
    assert error_code(response) == "shortcut_selection"
    assert harness.store.upsert_calls == 0


def test_trashed_selection_is_denied() -> None:
    harness = Harness(metadata={"id": FOLDER_ID, "name": "휴지통", "mimeType": GOOGLE_FOLDER_MIME, "version": 1, "trashed": True})
    response = harness.post(
        SELECT_PATH, {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "folder_id": FOLDER_ID}
    )
    assert response.status_code in (422, 502)
    assert harness.store.upsert_calls == 0


def test_arbitrary_folder_id_is_refetched_and_denied_when_unknown() -> None:
    harness = Harness(metadata=None)  # provider knows nothing about this id
    response = harness.post(
        SELECT_PATH, {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "folder_id": "guessed_folder_999"}
    )
    assert response.status_code == 422
    assert harness.store.upsert_calls == 0
    assert harness.port.metadata_calls, "the intent id must always be re-fetched"


def test_caller_authority_fields_are_rejected() -> None:
    harness = Harness(metadata=FOLDER_METADATA)
    for field, value in (
        ("binding_ref", BINDING_REF),
        ("app_id", DRIVE_REFERENCE_APP_ID),
        ("agent_id", DRIVE_AGENT_ID),
        ("scope", "case-folder:x"),
        ("drive_grant", {"binding_ref": BINDING_REF}),
    ):
        payload = {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "folder_id": FOLDER_ID}
        payload[field] = value
        response = harness.post(SELECT_PATH, payload)
        assert response.status_code == 400, field
        assert error_code(response) == "invalid_request"
    assert harness.store.upsert_calls == 0


# --- 3. dependency fail-closed -------------------------------------------


def test_missing_drive_grant_fails_closed() -> None:
    harness = Harness(grant=None)
    harness.grant_provider.grant = None
    response = harness.post(STATUS_PATH, {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID})
    assert response.status_code == 409
    assert error_code(response) == "drive_not_connected"


def test_missing_binding_authority_fails_closed() -> None:
    service = DriveCaseFolderEngineService(
        grant_provider=FakeGrantProvider(drive_grant()), drive_port=FakeDrivePort(), binding_authority=None
    )
    response = run(
        service.handle(
            method="POST",
            path=STATUS_PATH,
            content_type="application/json",
            body=json.dumps({"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID}).encode(),
        )
    )
    assert response.status_code == 503


def test_missing_drive_port_fails_closed() -> None:
    service = DriveCaseFolderEngineService(
        grant_provider=FakeGrantProvider(drive_grant()),
        drive_port=None,
        binding_authority=DriveCaseFolderBindingAuthority(store=InMemoryDriveCaseFolderBindingStore()),
    )
    response = run(
        service.handle(
            method="POST",
            path=FOLDERS_PATH,
            content_type="application/json",
            body=json.dumps({"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID}).encode(),
        )
    )
    assert response.status_code == 503


def test_request_contract_rejections() -> None:
    harness = Harness(metadata=FOLDER_METADATA)
    assert harness.post("/unknown", {}).status_code == 404
    assert harness.post(STATUS_PATH, {}, method="GET").status_code == 405
    assert harness.post(STATUS_PATH, {}, content_type="text/plain").status_code == 415
    assert harness.post(STATUS_PATH, {"workspace_ref": WORKSPACE_REF}).status_code == 400
    assert harness.post(FOLDERS_PATH, {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "query": "x" * 500}).status_code == 400


# --- 4. source posture ---------------------------------------------------


def test_service_source_reuses_canonical_drive_handlers_only() -> None:
    import app.drive_case_folder_service as module

    source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    for required in (
        "from padiem_ai_core.drive_capability import",
        "build_drive_read_handlers",
        "from app.drive_case_folder_binding import",
    ):
        assert required in source
    for forbidden in (
        "import httpx",
        "import requests",
        "urllib.request",
        "refresh_token",
        "client_secret",
        "access_token",
        "ToolRuntime(",
        "wrangler",
    ):
        assert forbidden not in source


def test_snapshot_posture() -> None:
    snapshot = drive_case_folder_service_snapshot()
    assert snapshot["folder_id_is_selection_intent"] is True
    assert snapshot["engine_refetches_metadata"] is True
    assert snapshot["requires_current_drive_grant"] is True
    assert snapshot["claims_exhaustive_listing"] is False
    assert snapshot["second_drive_client"] is False
    assert snapshot["second_tool_runtime"] is False
    assert snapshot["second_oauth_authority"] is False
