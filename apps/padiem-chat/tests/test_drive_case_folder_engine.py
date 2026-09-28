"""Chat -> Engine private seam tests (#3190).

Network-free. Proves the Chat client calls only the fixed private RPCs, closes
every response schema, and never surfaces raw Engine error text.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.drive_case_folder_engine import (
    CLEAR_OPERATION,
    FOLDERS_OPERATION,
    SELECT_OPERATION,
    STATUS_OPERATION,
    CloudflareDriveCaseFolderEngineClient,
    DriveCaseFolderEngineError,
    drive_case_folder_engine_seam_snapshot,
)

WORKSPACE_REF = "ws_alpha_001"
PROJECT_ID = "proj_" + "a" * 32
FOLDER_ID = "folder_case_001"


def run(coro):
    return asyncio.run(coro)


class FakeEngineBinding:
    """Mirrors the Engine Worker RPC shape: binding.method({payload})."""

    def __init__(self, responses: dict | None = None, *, error: Exception | None = None) -> None:
        self.responses = responses or {}
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def drive_case_folder_status(self, payload: dict) -> dict:
        return self._respond(STATUS_OPERATION, payload)

    async def drive_case_folder_folders(self, payload: dict) -> dict:
        return self._respond(FOLDERS_OPERATION, payload)

    async def drive_case_folder_select(self, payload: dict) -> dict:
        return self._respond(SELECT_OPERATION, payload)

    async def drive_case_folder_clear(self, payload: dict) -> dict:
        return self._respond("drive_case_folder_clear", payload)

    def _respond(self, operation: str, payload: dict) -> dict:
        self.calls.append((operation, dict(payload)))
        if self.error is not None:
            raise self.error
        return self.responses.get(operation, _ok_default(operation))


def _ok_default(operation: str) -> dict:
    if operation == STATUS_OPERATION:
        return {
            "ok": True,
            "status": {"configured": False, "space_kind": None, "scope_token": None, "updated_at": None},
            "contract_version": "engine-drive-case-folder-service.v1",
        }
    if operation == FOLDERS_OPERATION:
        return {"ok": True, "folders": [], "more": False, "exhaustive": False, "contract_version": "v1"}
    if operation == SELECT_OPERATION:
        return {
            "ok": True,
            "outcome": "created",
            "status": {"configured": True, "space_kind": "my_drive", "updated_at": "2026-09-28T00:00:00+00:00"},
            "contract_version": "v1",
        }
    return {"ok": True, "cleared": True}


def folders_response() -> dict:
    return {
        "ok": True,
        "folders": [
            {
                "folder_id": FOLDER_ID,
                "name": "사건자료",
                "space_kind": "my_drive",
                "modified_time": "2026-09-01T00:00:00+00:00",
            }
        ],
        "more": False,
        "exhaustive": False,
        "contract_version": "v1",
    }


# --- 1. operations --------------------------------------------------------


def test_status_rpc_round_trip() -> None:
    binding = FakeEngineBinding()
    client = CloudflareDriveCaseFolderEngineClient(binding)
    body = run(client.status(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID))
    assert body == {"configured": False, "space_kind": None, "updated_at": None, "scope_token": None}
    assert binding.calls == [(STATUS_OPERATION, {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID})]


def test_folders_rpc_round_trip_and_query_bound() -> None:
    binding = FakeEngineBinding({FOLDERS_OPERATION: folders_response()})
    client = CloudflareDriveCaseFolderEngineClient(binding)
    body = run(client.folders(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID, query=" 사건 "))
    assert body["folders"][0]["folder_id"] == FOLDER_ID
    assert binding.calls[-1][1]["query"] == "사건"
    assert body["exhaustive"] is False


def test_select_rpc_round_trip() -> None:
    binding = FakeEngineBinding()
    client = CloudflareDriveCaseFolderEngineClient(binding)
    body = run(client.select(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID, folder_id=FOLDER_ID))
    assert body["configured"] is True
    assert binding.calls[-1][1]["folder_id"] == FOLDER_ID


def test_clear_rpc_round_trip() -> None:
    binding = FakeEngineBinding()
    client = CloudflareDriveCaseFolderEngineClient(binding)
    assert run(client.clear(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID)) == {"cleared": True}


# --- 2. closed response validation ----------------------------------------


def test_extra_outer_field_is_denied() -> None:
    bad = _ok_default(STATUS_OPERATION)
    bad["extra"] = 1
    client = CloudflareDriveCaseFolderEngineClient(FakeEngineBinding({STATUS_OPERATION: bad}))
    with pytest.raises(DriveCaseFolderEngineError) as excinfo:
        run(client.status(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID))
    assert excinfo.value.code == "drive_case_folder_response_invalid"
    assert excinfo.value.status_code == 502


def test_missing_field_is_denied() -> None:
    bad = _ok_default(FOLDERS_OPERATION)
    del bad["more"]
    client = CloudflareDriveCaseFolderEngineClient(FakeEngineBinding({FOLDERS_OPERATION: bad}))
    with pytest.raises(DriveCaseFolderEngineError):
        run(client.folders(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID))


def test_wrong_type_is_denied() -> None:
    bad = _ok_default(STATUS_OPERATION)
    bad["status"] = {"configured": "yes", "space_kind": None, "scope_token": None, "updated_at": None}
    client = CloudflareDriveCaseFolderEngineClient(FakeEngineBinding({STATUS_OPERATION: bad}))
    with pytest.raises(DriveCaseFolderEngineError):
        run(client.status(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID))


def test_unknown_space_kind_is_denied() -> None:
    bad = folders_response()
    bad["folders"][0]["space_kind"] = "team_drive"
    client = CloudflareDriveCaseFolderEngineClient(FakeEngineBinding({FOLDERS_OPERATION: bad}))
    with pytest.raises(DriveCaseFolderEngineError):
        run(client.folders(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID))


def test_unknown_outcome_is_denied() -> None:
    bad = _ok_default(SELECT_OPERATION)
    bad["outcome"] = "maybe"
    client = CloudflareDriveCaseFolderEngineClient(FakeEngineBinding({SELECT_OPERATION: bad}))
    with pytest.raises(DriveCaseFolderEngineError):
        run(client.select(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID, folder_id=FOLDER_ID))


# --- 3. bounded errors, no raw text ---------------------------------------


def test_engine_error_envelope_is_mapped_without_raw_text() -> None:
    bad = {
        "ok": False,
        "error": {
            "code": "drive_not_connected",
            "message": "internal detail: /x/y",
            "retryable": False,
            "metadata": None,
        },
    }
    client = CloudflareDriveCaseFolderEngineClient(FakeEngineBinding({STATUS_OPERATION: bad}))
    with pytest.raises(DriveCaseFolderEngineError) as excinfo:
        run(client.status(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID))
    assert excinfo.value.status_code == 409
    assert "internal detail" not in str(excinfo.value)
    assert "internal detail" not in excinfo.value.safe_message


def test_error_envelope_is_closed() -> None:
    inner = {"code": "drive_not_connected", "message": "m", "retryable": False, "metadata": None}
    variants = (
        {"ok": False, "error": inner, "extra": 1},
        {"ok": False, "error": {**inner, "extra": 1}},
        {"ok": False, "error": {key: value for key, value in inner.items() if key != "retryable"}},
        {"ok": False, "error": {**inner, "retryable": "no"}},
        {"ok": False, "error": {**inner, "metadata": {"x": 1}}},
        {"ok": False, "error": {**inner, "access_token": "***"}},
        {"ok": False, "error": {**inner, "code": 123}},
        {"ok": False, "error": {**inner, "message": ""}},
    )
    for bad in variants:
        client = CloudflareDriveCaseFolderEngineClient(FakeEngineBinding({STATUS_OPERATION: bad}))
        with pytest.raises(DriveCaseFolderEngineError) as excinfo:
            run(client.status(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID))
        assert excinfo.value.status_code == 502, bad
        assert excinfo.value.code == "drive_case_folder_response_invalid", bad


def test_unknown_engine_error_code_is_normalized() -> None:
    bad = {
        "ok": False,
        "error": {"code": "totally_new_code", "message": "m", "retryable": True, "metadata": None},
    }
    client = CloudflareDriveCaseFolderEngineClient(FakeEngineBinding({STATUS_OPERATION: bad}))
    with pytest.raises(DriveCaseFolderEngineError) as excinfo:
        run(client.status(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID))
    assert excinfo.value.code == "drive_case_folder_failed"
    assert excinfo.value.status_code == 502
    assert "totally_new_code" not in str(excinfo.value)


def test_constructor_requires_every_rpc() -> None:
    class Partial:
        async def drive_case_folder_status(self, payload: dict) -> dict:
            return {}

    with pytest.raises(ValueError):
        CloudflareDriveCaseFolderEngineClient(Partial())


def test_transport_failure_is_bounded() -> None:
    client = CloudflareDriveCaseFolderEngineClient(
        FakeEngineBinding(error=RuntimeError("raw engine trace"))
    )
    with pytest.raises(DriveCaseFolderEngineError) as excinfo:
        run(client.status(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID))
    assert excinfo.value.status_code == 502
    assert "raw engine trace" not in str(excinfo.value)


def test_binding_without_rpcs_is_rejected() -> None:
    for bad in (None, object()):
        with pytest.raises(ValueError):
            CloudflareDriveCaseFolderEngineClient(bad)


def test_client_never_returns_raw_refs() -> None:
    binding = FakeEngineBinding({FOLDERS_OPERATION: folders_response()})
    client = CloudflareDriveCaseFolderEngineClient(binding)
    rendered = json.dumps(run(client.folders(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID)))
    assert WORKSPACE_REF not in rendered and PROJECT_ID not in rendered


def test_seam_snapshot_posture() -> None:
    snapshot = drive_case_folder_engine_seam_snapshot()
    assert snapshot["browser_selects_endpoint"] is False
    assert snapshot["response_schema_closed"] is True
    assert snapshot["raw_engine_error_text"] is False
    assert snapshot["production_binding_activated"] is False
    assert len(snapshot["operations"]) == 4
