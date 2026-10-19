"""Workspace-bound general Drive READ RPC regression, with real Core handlers."""
from __future__ import annotations
import asyncio

from padiem_ai_core.drive_capability import DriveCapability
from app.connector_bindings import DRIVE_AGENT_ID, DRIVE_REFERENCE_APP_ID, DriveGrant
from app.drive_case_folder_service import DriveCaseFolderEngineService, GENERAL_SEARCH_PATH, GENERAL_READ_PATH
from app.drive_case_folder_rpc import drive_case_folder_rpc

class Grants:
    def __init__(self, connected=True):
        self.connected=connected
        self.workspaces=[]
    async def current_drive_grant(self, *, workspace_ref):
        self.workspaces.append(workspace_ref)
        if not self.connected:
            return None
        return DriveGrant(app_id=DRIVE_REFERENCE_APP_ID, canonical_agent_id=DRIVE_AGENT_ID,
                          binding_ref="bind:workspace_A", actor_ref="actor:workspace_A",
                          granted_capabilities=(DriveCapability.READ,))

class Port:
    def __init__(self):
        self.calls=[]
    def get_json(self, **kw):
        self.calls.append(("json",kw["path"],kw["binding_ref"],kw["actor_ref"]))
        if kw["path"] == "/files":
            return {"files": [{"id":"drive_file_A", "name":"견적서.txt", "mimeType":"text/plain",
                               "trashed":False, "version":1,
                               "webViewLink":"https://drive.google.com/file/d/drive_file_A/view"}]}
        return {"id":"drive_file_A","name":"견적서.txt","mimeType":"text/plain","trashed":False}
    def get_text(self, **kw):
        self.calls.append(("text",kw["path"],kw["binding_ref"],kw["actor_ref"]))
        return "예상 합계 500원"

def test_search_and_read_reuse_workspace_grant_and_core():
    grants=Grants()
    port=Port()
    svc=DriveCaseFolderEngineService(grant_provider=grants,drive_port=port)
    async def run():
        search=await drive_case_folder_rpc(svc, operation="drive_general_search",payload={"workspace_ref":"workspace_A","query":"견적서"})
        read=await drive_case_folder_rpc(svc,operation="drive_general_read",payload={"workspace_ref":"workspace_A","file_id":"drive_file_A"})
        return search,read
    search,read=asyncio.run(run())
    assert search["ok"] and search["files"][0]["name"]=="견적서.txt"
    assert read["ok"] and "500원" in read["content"]
    assert grants.workspaces==["workspace_A","workspace_A"]
    assert all(c[2:] == ("bind:workspace_A","actor:workspace_A") for c in port.calls)

def test_missing_workspace_grant_denies_provider_calls():
    grants=Grants(connected=False)
    port=Port()
    svc=DriveCaseFolderEngineService(grant_provider=grants,drive_port=port)
    result=asyncio.run(drive_case_folder_rpc(svc,operation="drive_general_search",payload={"workspace_ref":"workspace_A","query":"견적서"}))
    assert result["ok"] is False
    assert result["error"]["code"]=="drive_not_connected"
    assert port.calls==[]

def test_client_supplied_authority_rejected_before_provider_calls():
    grants=Grants()
    port=Port()
    svc=DriveCaseFolderEngineService(grant_provider=grants,drive_port=port)
    result=asyncio.run(drive_case_folder_rpc(svc,operation="drive_general_search",payload={"workspace_ref":"workspace_A","query":"견적서","binding_ref":"forged"}))
    assert result["ok"] is False
    assert result["error"]["code"]=="invalid_request"
    assert grants.workspaces == []
    assert port.calls == []
