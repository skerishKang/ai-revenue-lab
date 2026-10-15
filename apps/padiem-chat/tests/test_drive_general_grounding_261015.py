"""Targeted regressions for owner-scoped Drive search/read in Chat and Engine."""
from __future__ import annotations
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.drive_general_grounding import DriveGroundingError, drive_search_intent, drive_general_grounding


def test_drive_intent_requires_explicit_drive_and_action():
    assert drive_search_intent("구글드라이브에서 견적서 찾아줘") == "견적서"
    assert drive_search_intent("안녕하세요") is None
    assert drive_search_intent("공개 웹에서 견적서 찾아줘") is None
    with pytest.raises(DriveGroundingError) as exc:
        drive_search_intent("드라이브에서 검색해줘")
    assert exc.value.status_code == 422


class Store:
    async def load_projection(self, user_id):
        return SimpleNamespace(auth_session_id="signed_auth_session")


class Authority:
    async def resolve_connector_workspace(self, *, session_id):
        assert session_id == "signed_auth_session"
        return "workspace_server_verified"


class Engine:
    def __init__(self):
        self.calls = []
    async def general_search(self, *, workspace_ref, query):
        self.calls.append(("search", workspace_ref, query))
        return {"files": [{"file_id": "file_123", "name": "견적서.txt", "mime_type": "text/plain",
                           "url": "https://drive.google.com/file/d/file_123/view"}], "more": False}
    async def general_read(self, *, workspace_ref, file_id):
        self.calls.append(("read", workspace_ref, file_id))
        return {"name": "견적서.txt", "content": "합계 100원", "truncated": False}


def test_read_after_one_verified_search(monkeypatch):
    from app import drive_general_grounding as mod
    monkeypatch.setattr(mod, "auth_ready", lambda request: True)
    monkeypatch.setattr(mod, "current_user_id", lambda request: "signed_user")
    engine = Engine()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        identity_shadow_store=Store(),
        control_plane_identity_authority=Authority(),
        drive_case_folder_engine_client=engine,
    )))
    ctx, sources = asyncio.run(drive_general_grounding(request, "구글드라이브에서 견적서 찾아서 요약해줘"))
    assert "합계 100원" in ctx
    assert "신뢰하지 않는" in ctx
    assert len(sources) == 1
    assert engine.calls == [("search", "workspace_server_verified", "견적서"), ("read", "workspace_server_verified", "file_123")]


def test_multiple_matches_do_not_autoread(monkeypatch):
    from app import drive_general_grounding as mod
    monkeypatch.setattr(mod, "auth_ready", lambda request: True)
    monkeypatch.setattr(mod, "current_user_id", lambda request: "signed_user")
    engine = Engine()
    async def search(*, workspace_ref, query):
        result = await Engine().general_search(workspace_ref=workspace_ref, query=query)
        return {"files": result["files"] * 2, "more": False}
    engine.general_search = search
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        identity_shadow_store=Store(), control_plane_identity_authority=Authority(),
        drive_case_folder_engine_client=engine,
    )))
    ctx, _ = asyncio.run(drive_general_grounding(request, "드라이브 견적서 요약해줘"))
    assert "[선택된 파일 본문]" not in ctx
    assert not engine.calls
