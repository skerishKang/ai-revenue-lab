"""Project-scoped B67 Drive PDF route tests (#3355)."""

from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

import app.drive_case_folder_routes as folder_routes
from app.drive_case_folder_engine import DriveCaseFolderEngineError
from app.drive_case_pdf_routes import drive_case_pdf_detail, drive_case_pdfs_collection

UID = "user-1"
PROJECT_ID = "proj_" + "a" * 32
FOREIGN_PROJECT_ID = "proj_" + "b" * 32
WORKSPACE_REF = "ws_resolved_001"
SESSION_ID = "sess_1"
FILE_ID = "file_pdf_001"
PDF_BYTES = b"%PDF-1.7\nsynthetic\n%%EOF\n"


def run(coro):
    return asyncio.run(coro)


class FakeQuery:
    def __init__(self, mapping=None):
        self._mapping = dict(mapping or {})

    def keys(self):
        return self._mapping.keys()

    def get(self, key):
        return self._mapping.get(key)


class FakeRequest:
    def __init__(self, *, project_id=PROJECT_ID, file_id=None, query=None, state=None):
        self.path_params = {"project_id": project_id}
        if file_id is not None:
            self.path_params["file_id"] = file_id
        self.query_params = FakeQuery(query)
        self.app = SimpleNamespace(state=state if state is not None else SimpleNamespace())


class FakeHistory:
    def __init__(self, *, owned=True):
        self.owned = owned

    async def get_project(self, uid, project_id):
        return SimpleNamespace(project_id=project_id) if self.owned else None


class FakeShadowStore:
    async def load_projection(self, uid):
        return SimpleNamespace(auth_session_id=SESSION_ID)


class FakeIdentityAuthority:
    def __init__(self):
        self.calls = []

    async def resolve_connector_workspace(self, *, session_id):
        self.calls.append(session_id)
        return WORKSPACE_REF


class FakeEngineClient:
    def __init__(self):
        self.calls = []

    async def pdf_candidates(self, *, workspace_ref, project_id, query=None):
        self.calls.append(("candidates", {"workspace_ref": workspace_ref, "project_id": project_id, "query": query}))
        return {
            "files": [
                {
                    "file_id": FILE_ID,
                    "name": "소장.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": len(PDF_BYTES),
                    "modified_time": "2026-10-01T00:00:00Z",
                    "space_kind": "my_drive",
                    "intake_state": "browser_pdf_ready",
                }
            ],
            "more": False,
            "direct_child_only": True,
        }

    async def read_pdf(self, *, workspace_ref, project_id, file_id):
        self.calls.append(("read", {"workspace_ref": workspace_ref, "project_id": project_id, "file_id": file_id}))
        return {
            "file": {
                "file_id": file_id,
                "name": "소장.pdf",
                "mime_type": "application/pdf",
                "size_bytes": len(PDF_BYTES),
                "modified_time": "2026-10-01T00:00:00Z",
                "space_kind": "my_drive",
                "intake_state": "browser_pdf_ready",
            },
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
        }


def state(*, history=None, client=None):
    return SimpleNamespace(
        history_store=history if history is not None else FakeHistory(),
        identity_shadow_store=FakeShadowStore(),
        control_plane_identity_authority=FakeIdentityAuthority(),
        drive_case_folder_engine_client=client if client is not None else FakeEngineClient(),
    )


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch):
    monkeypatch.setattr(folder_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(folder_routes, "current_user_id", lambda request: UID)


def test_candidates_use_server_resolved_workspace_and_owned_project():
    engine = FakeEngineClient()
    response = run(drive_case_pdfs_collection(FakeRequest(query={"query": " 소장 "}, state=state(client=engine))))
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["files"][0]["file_id"] == FILE_ID
    assert body["direct_child_only"] is True
    assert engine.calls == [
        (
            "candidates",
            {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "query": "소장"},
        )
    ]
    rendered = response.body.decode()
    assert WORKSPACE_REF not in rendered
    assert PROJECT_ID not in rendered


def test_foreign_project_fails_before_pdf_engine_call():
    engine = FakeEngineClient()
    response = run(
        drive_case_pdfs_collection(
            FakeRequest(project_id=FOREIGN_PROJECT_ID, state=state(history=FakeHistory(owned=False), client=engine))
        )
    )
    assert response.status_code == 404
    assert engine.calls == []


def test_collection_rejects_browser_authority_query_fields():
    for key in ("workspace_ref", "binding_ref", "actor_ref", "access_token", "provider_url"):
        engine = FakeEngineClient()
        response = run(drive_case_pdfs_collection(FakeRequest(query={key: "x"}, state=state(client=engine))))
        assert response.status_code == 400, key
        assert engine.calls == [], key


def test_detail_passes_file_id_as_selection_intent_only():
    engine = FakeEngineClient()
    response = run(drive_case_pdf_detail(FakeRequest(file_id=FILE_ID, state=state(client=engine))))
    assert response.status_code == 200
    body = json.loads(response.body)
    assert base64.b64decode(body["content_base64"], validate=True) == PDF_BYTES
    assert body["authorization"] == {"direct_parent_proof": True, "source_type": "drive"}
    assert engine.calls[-1] == (
        "read",
        {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "file_id": FILE_ID},
    )
    rendered = response.body.decode()
    assert WORKSPACE_REF not in rendered
    assert PROJECT_ID not in rendered
    assert "resource_key" not in rendered


def test_detail_rejects_all_query_authority_fields_before_engine_call():
    engine = FakeEngineClient()
    response = run(
        drive_case_pdf_detail(
            FakeRequest(file_id=FILE_ID, query={"workspace_ref": WORKSPACE_REF}, state=state(client=engine))
        )
    )
    assert response.status_code == 400
    assert engine.calls == []


def test_engine_error_maps_without_raw_detail():
    class Failing(FakeEngineClient):
        async def read_pdf(self, *, workspace_ref, project_id, file_id):
            raise DriveCaseFolderEngineError(
                "execution_fallback_required",
                "Selected PDF requires bounded execution fallback.",
                status_code=413,
            )

    response = run(drive_case_pdf_detail(FakeRequest(file_id=FILE_ID, state=state(client=Failing()))))
    assert response.status_code == 413
    body = json.loads(response.body)
    assert body["error"]["code"] == "execution_fallback_required"


def test_unexpected_exception_is_generic_and_does_not_propagate_attributes():
    class Sneaky(FakeEngineClient):
        async def pdf_candidates(self, *, workspace_ref, project_id, query=None):
            raise type("E", (Exception,), {"code": "injected", "safe_message": "raw secret", "status_code": 200})()

    response = run(drive_case_pdfs_collection(FakeRequest(state=state(client=Sneaky()))))
    assert response.status_code == 502
    rendered = response.body.decode()
    assert json.loads(response.body)["error"]["code"] == "drive_case_pdf_failed"
    assert "raw secret" not in rendered
    assert "injected" not in rendered


def test_route_module_reuses_existing_project_workspace_resolver():
    import pathlib
    import app.drive_case_pdf_routes as module

    source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    assert "from .drive_case_folder_routes import _resolve_context" in source
    assert "resolve_connector_workspace" not in source
    assert "P01_ENGINE_SERVICE_BINDING_NAME" not in source
    assert module.BROWSER_WORKSPACE_REF_AUTHORITY is False
    assert module.BROWSER_BINDING_REF_AUTHORITY is False
    assert module.BROWSER_DRIVE_GRANT_AUTHORITY is False
    assert module.BROWSER_PROVIDER_ENDPOINT_AUTHORITY is False
    assert module.FILE_ID_IS_SELECTION_INTENT is True
    assert module.SECOND_ENGINE_BINDING is False
    assert module.PRODUCTION_MUTATION is False
