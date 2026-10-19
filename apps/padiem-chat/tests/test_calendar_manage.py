"""Native Calendar authenticated, workspace-scoped edit/delete contract."""
from __future__ import annotations

import asyncio

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import app.calendar_routes as routes
from app.calendar_store import InMemoryCalendarStore


def _client(monkeypatch):
    async def workspace(_request, uid):
        return "workspace_" + uid
    monkeypatch.setattr(routes, "_require_owner", lambda request: request.headers.get("x-test-owner"))
    monkeypatch.setattr(routes, "_resolve_memory_workspace", workspace)
    app = Starlette(routes=[
        Route("/api/calendar/appointments", routes.calendar_appointments_create, methods=["POST"]),
        Route("/api/calendar/appointments/{appointment_id}", routes.calendar_appointment_manage, methods=["PUT", "DELETE"]),
        Route("/api/calendar/work-logs", routes.calendar_work_logs_create, methods=["POST"]),
        Route("/api/calendar/work-logs/{log_id}", routes.calendar_work_log_manage, methods=["PUT", "DELETE"]),
    ])
    app.state.calendar_store = InMemoryCalendarStore()
    return TestClient(app)


def test_appointment_edit_delete_scope(monkeypatch):
    client = _client(monkeypatch)
    owner = {"x-test-owner": "alice"}
    foreign = {"x-test-owner": "bob"}
    created = client.post("/api/calendar/appointments", json={
        "appointment_type": "date_only", "title": "Visit", "date": "2026-10-23"
    }, headers=owner)
    assert created.status_code == 201, created.text
    ref = created.json()["appointment"]["calendar_item_id"].removeprefix("item_apt_")
    path = "/api/calendar/appointments/" + ref
    foreign_edit = client.put(path, json={"title": "Steal"}, headers=foreign)
    assert foreign_edit.status_code == 404
    foreign_delete = client.delete(path, headers=foreign)
    assert foreign_delete.status_code == 404
    bad = client.put(path, json={"workspace_id": "workspace_bob", "title": "Forgery"}, headers=owner)
    assert bad.status_code == 400
    updated = client.put(path, json={"title": "Revised", "date": "2026-10-24"}, headers=owner)
    assert updated.status_code == 200, updated.text
    assert updated.json()["appointment"]["title"] == "Revised"
    assert updated.json()["appointment"]["date"] == "2026-10-24"
    deleted = client.delete(path, headers=owner)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert client.delete(path, headers=owner).status_code == 404
    assert client.put(path, json={"title": "After"}, headers=owner).status_code == 404


def test_work_log_edit_delete_scope(monkeypatch):
    client = _client(monkeypatch)
    owner = {"x-test-owner": "alice"}
    other = {"x-test-owner": "bob"}
    created = client.post("/api/calendar/work-logs", json={
        "title": "Daily record", "date": "2026-10-24", "content": "Original"
    }, headers=owner)
    assert created.status_code == 201, created.text
    ref = created.json()["work_log"]["calendar_item_id"].removeprefix("item_log_")
    path = "/api/calendar/work-logs/" + ref
    assert client.delete(path, headers=other).status_code == 404
    updated = client.put(path, json={"title": "Edited record", "content": "Updated"}, headers=owner)
    assert updated.status_code == 200, updated.text
    assert updated.json()["work_log"]["title"] == "Edited record"
    assert updated.json()["work_log"]["summary"] == "Updated"
    assert client.delete(path, headers=owner).status_code == 200
    assert client.put(path, json={"title": "Retry"}, headers=owner).status_code == 404


def test_unsigned_calendar_write_denied(monkeypatch):
    client = _client(monkeypatch)
    assert client.delete("/api/calendar/appointments/unknown").status_code == 401
    assert client.put("/api/calendar/work-logs/unknown", json={"title": "x"}).status_code == 401
