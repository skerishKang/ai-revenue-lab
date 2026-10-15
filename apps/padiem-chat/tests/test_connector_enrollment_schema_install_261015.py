"""Enrollment schema install route: explicit action, fixed migration, no new authority."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app import connector_enrollment_schema_install as schema_route
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

NOW = datetime(2026, 10, 15, 7, 0, tzinfo=timezone.utc)


class Request:
    def __init__(self, data, state):
        self.app = SimpleNamespace(state=state)
        self.headers = {"content-type": "application/json", "content-length": str(len(json.dumps(data)))}
        self._data = data

    async def body(self):
        return json.dumps(self._data).encode()


def run(handler, request):
    response = asyncio.run(handler(request))
    return response.status_code, json.loads(response.body)


class Csrf:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def verify(self, request):
        del request
        return self.allowed


class SchemaAuthority:
    def __init__(self):
        self.calls = []

    async def install_connector_enrollment_schema(self, *, migration_id):
        self.calls.append(migration_id)
        return {"schema": migration_id, "installed_by_default": False}


def canonical_session():
    return AuthSessionSnapshot(
        session_id="session.canonical.owner.1", product_id="b54-padiem-claw",
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="subject.canonical.owner.1"),
        issued_at=NOW - timedelta(days=1), expires_at=NOW + timedelta(days=30),
        state=AuthSessionState.ACTIVE, tenant_id="tenant_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )


def state_for(authority, *, csrf=True):
    return SimpleNamespace(
        control_plane_identity_authority=authority,
        connector_enrollment_browser_csrf=Csrf(csrf),
    )


def setup_auth(monkeypatch):
    from app import claw_connector_enrollment_routes as routes

    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: "product-user-1")

    async def resolve(request):
        del request
        return SimpleNamespace(product_user_id="product-user-1", auth_session=canonical_session())

    monkeypatch.setattr(routes, "resolve_current_b54_canonical_session", resolve)


def body():
    return {"confirmed": True, "confirmation_version": "pc-enrollment-consent-v1"}


def test_install_runs_fixed_reviewed_migration_once(monkeypatch):
    setup_auth(monkeypatch)
    authority = SchemaAuthority()
    status, result = run(schema_route.install_enrollment_schema, Request(body(), state_for(authority)))
    assert status == 200
    assert result == {"ok": True, "schema": "connector-enrollment-v1", "installed_by_default": False}
    assert authority.calls == ["connector-enrollment-v1"]


def test_install_requires_csrf_and_exact_confirmation(monkeypatch):
    setup_auth(monkeypatch)
    authority = SchemaAuthority()
    assert run(schema_route.install_enrollment_schema, Request(body(), state_for(authority, csrf=False)))[0] == 403
    assert run(
        schema_route.install_enrollment_schema,
        Request({"confirmed": "true", "confirmation_version": "pc-enrollment-consent-v1"}, state_for(authority)),
    )[0] == 400
    assert run(
        schema_route.install_enrollment_schema,
        Request({"confirmed": True, "confirmation_version": "pc-enrollment-consent-v1", "migration_id": "other"}, state_for(authority)),
    )[0] == 400
    assert authority.calls == []


def test_missing_authority_fails_closed(monkeypatch):
    setup_auth(monkeypatch)
    bare = SimpleNamespace(
        control_plane_identity_authority=SimpleNamespace(),
        connector_enrollment_browser_csrf=Csrf(True),
    )
    status, _ = run(schema_route.install_enrollment_schema, Request(body(), bare))
    assert status == 503
