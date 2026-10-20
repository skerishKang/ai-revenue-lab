"""Project file lists have no count ceiling; D1 reads remain owner-scoped pages."""
from __future__ import annotations

import pytest
from app.project_files import D1ProjectFileStore, MAX_OWNER_FILES_PAGE


@pytest.mark.asyncio
async def test_project_files_list_all_keyset_pages_and_preserve_owner_scope(monkeypatch):
    store = D1ProjectFileStore(object())
    owner, project = "owner-a", "project-a"
    timestamp = "2026-10-20T00:00:00.000Z"
    rows = [
        {"id": f"file_{n:032x}", "project_id": project, "name": str(n),
         "media_type": "text/plain", "content_text": "x", "content_chars": 1,
         "created_at": timestamp, "updated_at": timestamp}
        for n in range(MAX_OWNER_FILES_PAGE + 1)
    ]
    queries = []

    async def fake_all(sql, *values):
        queries.append((sql, values))
        assert "user_id=? AND project_id=?" in sql
        assert values[:2] == (owner, project)
        assert values[-1] == MAX_OWNER_FILES_PAGE
        if len(values) == 3:
            return rows[:MAX_OWNER_FILES_PAGE]
        assert values[2:5] == (timestamp, timestamp, rows[99]["id"])
        return rows[MAX_OWNER_FILES_PAGE:]

    monkeypatch.setattr(store, "_all", fake_all)
    result = await store.list_files(owner, project)
    assert len(result) == MAX_OWNER_FILES_PAGE + 1
    assert result[-1].id == rows[-1]["id"]
    assert len(queries) == 2


@pytest.mark.asyncio
async def test_project_files_empty_owner_scope_does_not_fall_back(monkeypatch):
    store = D1ProjectFileStore(object())
    async def fake_all(sql, *values):
        assert values[:2] == ("other-owner", "project-a")
        return []
    monkeypatch.setattr(store, "_all", fake_all)
    assert await store.list_files("other-owner", "project-a") == []
