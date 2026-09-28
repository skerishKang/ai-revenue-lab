"""Owner-gated Drive case-folder route tests (#3190).

Network-free. Proves the fixed authority order, the non-disclosing foreign
project behaviour, browser authority field rejection, and that the Engine call
uses the server-resolved canonical workspace with the owner-validated project.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

import app.drive_case_folder_routes as routes_module
from app.drive_case_folder_engine import DriveCaseFolderEngineError
from app.drive_case_folder_routes import (
    drive_case_folder_delete,
    drive_case_folder_put,
    drive_case_folder_status,
    drive_folders_collection,
)

UID = "user-1"
PROJECT_ID = "proj_" + "a" * 32
FOREIGN_PROJECT_ID = "proj_" + "b" * 32
WORKSPACE_REF = "ws_resolved_001"
SESSION_ID = "sess_1"
FOLDER_ID = "folder_case_001"


def run(coro):
    return asyncio.run(coro)


class FakeQuery:
    def __init__(self, mapping: dict | None = None) -> None:
        self._mapping = dict(mapping or {})

    def keys(self):
        return self._mapping.keys()

    def get(self, key):
        return self._mapping.get(key)


class FakeRequest:
    def __init__(self, *, project_id=PROJECT_ID, query=None, body=b"", state=None) -> None:
        self.path_params = {"project_id": project_id}
        self.query_params = FakeQuery(query)
        self._body = body
        self.app = SimpleNamespace(state=state if state is not None else SimpleNamespace())

    async def body(self):
        return self._body


class FakeHistory:
    def __init__(self, *, owned=True) -> None:
        self.owned = owned
        self.calls: list[tuple] = []

    async def get_project(self, uid, project_id):
        self.calls.append((uid, project_id))
        return SimpleNamespace(project_id=project_id) if self.owned else None


class FakeShadowStore:
    def __init__(self, *, session_id: str | None = SESSION_ID) -> None:
        self.session_id = session_id

    async def load_projection(self, uid):
        if self.session_id is None:
            return None
        return SimpleNamespace(auth_session_id=self.session_id)


class FakeIdentityAuthority:
    def __init__(self, *, workspace_ref: str | None = WORKSPACE_REF) -> None:
        self.workspace_ref = workspace_ref
        self.calls: list[str] = []

    async def resolve_connector_workspace(self, *, session_id):
        self.calls.append(session_id)
        return self.workspace_ref


class FakeEngineClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def status(self, *, workspace_ref, project_id):
        self.calls.append(("status", {"workspace_ref": workspace_ref, "project_id": project_id}))
        return {
            "configured": True,
            "space_kind": "my_drive",
            "updated_at": "2026-09-28T00:00:00+00:00",
            "scope_token": "drive_scope_abc",
        }

    async def folders(self, *, workspace_ref, project_id, query=None):
        self.calls.append(
            ("folders", {"workspace_ref": workspace_ref, "project_id": project_id, "query": query})
        )
        return {
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
        }

    async def select(self, *, workspace_ref, project_id, folder_id):
        self.calls.append(
            (
                "select",
                {"workspace_ref": workspace_ref, "project_id": project_id, "folder_id": folder_id},
            )
        )
        return {"configured": True, "space_kind": "my_drive", "updated_at": "2026-09-28T00:00:00+00:00"}

    async def clear(self, *, workspace_ref, project_id):
        self.calls.append(("clear", {"workspace_ref": workspace_ref, "project_id": project_id}))
        return {"cleared": True}


def state(
    *,
    history=None,
    shadow="default",
    authority="default",
    client="default",
) -> SimpleNamespace:
    return SimpleNamespace(
        history_store=history if history is not None else FakeHistory(),
        identity_shadow_store=FakeShadowStore() if shadow == "default" else shadow,
        control_plane_identity_authority=FakeIdentityAuthority() if authority == "default" else authority,
        drive_case_folder_engine_client=FakeEngineClient() if client == "default" else client,
    )


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch):
    monkeypatch.setattr(routes_module, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes_module, "current_user_id", lambda request: UID)


# --- 1. authority order + taxonomy ----------------------------------------


def test_signed_out_is_401(monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "current_user_id", lambda request: None)
    response = run(drive_case_folder_status(FakeRequest(state=state())))
    assert response.status_code == 401


def test_not_ready_is_503(monkeypatch) -> None:
    monkeypatch.setattr(routes_module, "auth_ready", lambda request: False)
    response = run(drive_case_folder_status(FakeRequest(state=state())))
    assert response.status_code == 503


def test_foreign_project_is_404_non_disclosing() -> None:
    response = run(drive_case_folder_status(FakeRequest(project_id=FOREIGN_PROJECT_ID, state=state(history=FakeHistory(owned=False)))))
    assert response.status_code == 404
    assert json.loads(response.body)["error"]["code"] == "project_not_found"
    # identical to an unknown project's response
    unknown = run(drive_case_folder_status(FakeRequest(project_id="proj_" + "c" * 32, state=state(history=FakeHistory(owned=False)))))
    assert json.loads(unknown.body) == json.loads(response.body)


def test_invalid_project_id_is_404() -> None:
    response = run(drive_case_folder_status(FakeRequest(project_id="not-a-project", state=state())))
    assert response.status_code == 404


def test_missing_identity_shadow_fails_closed() -> None:
    response = run(drive_case_folder_status(FakeRequest(state=state(shadow=None))))
    assert response.status_code == 503


def test_missing_canonical_workspace_fails_closed() -> None:
    response = run(drive_case_folder_status(FakeRequest(state=state(authority=FakeIdentityAuthority(workspace_ref=None)))))
    assert response.status_code == 503


def test_missing_engine_client_is_503() -> None:
    response = run(drive_case_folder_status(FakeRequest(state=state(client=None))))
    assert response.status_code == 503


# --- 2. engine call uses server authority ---------------------------------


def test_status_uses_server_resolved_workspace_and_owner_project() -> None:
    engine = FakeEngineClient()
    response = run(drive_case_folder_status(FakeRequest(state=state(client=engine))))
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body == {"configured": True, "space_kind": "my_drive", "updated_at": "2026-09-28T00:00:00+00:00"}
    operation, payload = engine.calls[-1]
    assert operation == "status"
    assert payload["workspace_ref"] == WORKSPACE_REF
    assert payload["project_id"] == PROJECT_ID
    # no raw identifier leaks into the product response
    rendered = response.body.decode()
    for secret in (WORKSPACE_REF, FOLDER_ID, "drive_scope_abc"):
        assert secret not in rendered


def test_folders_passes_bounded_query_only() -> None:
    engine = FakeEngineClient()
    response = run(drive_folders_collection(FakeRequest(query={"query": " 사건 "}, state=state(client=engine))))
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["folders"][0]["folder_id"] == FOLDER_ID
    assert body["exhaustive"] is False
    assert engine.calls[-1][1]["query"] == "사건"


def test_unknown_query_key_is_denied_without_engine_call() -> None:
    engine = FakeEngineClient()
    response = run(drive_folders_collection(FakeRequest(query={"workspace_ref": WORKSPACE_REF}, state=state(client=engine))))
    assert response.status_code == 400
    assert engine.calls == []


def test_put_select_round_trip() -> None:
    engine = FakeEngineClient()
    request = FakeRequest(body=json.dumps({"folder_id": FOLDER_ID}).encode(), state=state(client=engine))
    response = run(drive_case_folder_put(request))
    assert response.status_code == 200
    assert json.loads(response.body)["configured"] is True
    assert engine.calls[-1][1]["folder_id"] == FOLDER_ID


def test_put_extra_authority_field_is_denied_without_engine_call() -> None:
    for field, value in (
        ("workspace_ref", WORKSPACE_REF),
        ("binding_ref", "bind:x"),
        ("actor_ref", "actor:x"),
        ("app_id", "app:x"),
        ("scope", "case-folder:x"),
        ("tenant_id", "t"),
    ):
        engine = FakeEngineClient()
        body = json.dumps({"folder_id": FOLDER_ID, field: value}).encode()
        response = run(drive_case_folder_put(FakeRequest(body=body, state=state(client=engine))))
        assert response.status_code == 400, field
        assert engine.calls == [], field


def test_delete_clear_round_trip_and_body_rejection() -> None:
    engine = FakeEngineClient()
    response = run(drive_case_folder_delete(FakeRequest(state=state(client=engine))))
    assert response.status_code == 200
    assert json.loads(response.body) == {"configured": False, "cleared": True}
    assert engine.calls[-1][0] == "clear"

    engine2 = FakeEngineClient()
    rejected = run(
        drive_case_folder_delete(
            FakeRequest(body=json.dumps({"workspace_ref": WORKSPACE_REF}).encode(), state=state(client=engine2))
        )
    )
    assert rejected.status_code == 400
    assert engine2.calls == []


def test_engine_error_is_mapped_without_raw_text() -> None:
    class FailingClient(FakeEngineClient):
        async def status(self, *, workspace_ref, project_id):
            raise DriveCaseFolderEngineError(
                "drive_not_connected",
                "Google Drive is not connected for this workspace.",
                status_code=409,
            )

    response = run(drive_case_folder_status(FakeRequest(state=state(client=FailingClient()))))
    assert response.status_code == 409
    assert json.loads(response.body)["error"]["code"] == "drive_not_connected"


def test_unexpected_exception_is_generic_502_without_attribute_propagation() -> None:
    class Sneaky(FakeEngineClient):
        async def status(self, *, workspace_ref, project_id):
            raise type(
                "E",
                (Exception,),
                {"status_code": 200, "code": "totally_injected", "safe_message": "injected text"},
            )()

    response = run(drive_case_folder_status(FakeRequest(state=state(client=Sneaky()))))
    assert response.status_code == 502
    rendered = response.body.decode()
    assert json.loads(response.body)["error"]["code"] == "drive_case_folder_failed"
    assert "totally_injected" not in rendered
    assert "injected text" not in rendered


def test_worker_composition_reuses_the_existing_p01_binding() -> None:
    import pathlib

    import app.drive_case_folder_engine as engine_module

    engine_source = pathlib.Path(engine_module.__file__).read_text(encoding="utf-8")
    assert "P01_ENGINE_SERVICE_BINDING_NAME" in engine_source
    assert '"PADIEM_AI_ENGINE"' not in engine_source

    worker_source = (pathlib.Path(__file__).resolve().parents[1] / "worker.py").read_text(encoding="utf-8")
    assert "P01_ENGINE_SERVICE_BINDING_NAME" in worker_source
    assert "CloudflareDriveCaseFolderEngineClient" in worker_source
    assert "drive_case_folder_engine_client" in worker_source
    assert '"PADIEM_AI_ENGINE"' not in worker_source


def test_route_pins() -> None:
    assert routes_module.BROWSER_WORKSPACE_REF_AUTHORITY is False
    assert routes_module.BROWSER_BINDING_REF_AUTHORITY is False
    assert routes_module.BROWSER_DRIVE_GRANT_AUTHORITY is False
    assert routes_module.FOREIGN_PROJECT_EXISTENCE_DISCLOSURE is False
    assert routes_module.ENGINE_FALLBACK_WITHOUT_CLIENT is False
