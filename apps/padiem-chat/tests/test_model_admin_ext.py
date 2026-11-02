"""Owner model console: same authority, closed failures, no key value out.

The screen adds Providers, models and credential slots, so these tests pin the
edge rules that matter more than the happy path: the existing global-model-admin
check runs before any upstream call, a key write needs a login minted in the last
five minutes, and even a regressed B14 answer cannot carry a key value or an
unknown field into the browser.
"""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from app import auth
from app.auth import SESSION_COOKIE, create_session_token, decode_session_claims
from app.b14_model_ops_source import (
    PROOF_UNCONFIGURED,
    REFUSED,
    ModelOpsUnavailable,
)
from app.config import Settings
from app.main import create_app

BASE = "https://chat.test"
CREDENTIAL_VALUE = "sk-synthetic-owner-value-0123456789-wxyz"


class GlobalAdmin:
    def __init__(self, allowed: bool = True):
        self.allowed = allowed
        self.calls: list[str] = []

    async def is_global_model_admin(self, *, user_id: str):
        self.calls.append(user_id)
        return self.allowed


class Source:
    def __init__(self, status=200, payload=None, *, error: Exception | None = None):
        self.status = status
        self.payload = payload if payload is not None else {"ok": True}
        self.error = error
        self.calls: list[tuple[str, dict | None]] = []

    async def call(self, path, payload=None):
        self.calls.append((path, payload))
        if self.error is not None:
            raise self.error
        return self.status, self.payload


def built_app(*, admin="default", source="absent"):
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password", public_base_url=BASE,
        session_secret="model-admin-ext-test-session-secret",
        session_max_age_seconds=3600,
    )
    if admin == "default":
        admin = GlobalAdmin()
    app = create_app(
        settings=settings, history_store=SimpleNamespace(),
        central_model_admin_authorizer=admin,
    )
    if source != "absent":
        app.state.b14_model_ops_source = source
    return app, settings


def call(app, settings, path, *, method="GET", body=None, cookie=None,
         owner="usr_model_owner"):
    async def inner():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            if cookie is not None:
                client.cookies.set(SESSION_COOKIE, cookie)
            elif owner is not None:
                client.cookies.set(SESSION_COOKIE, create_session_token(settings, owner))
            if method == "GET":
                return await client.get(path)
            return await client.post(
                path, content=body, headers={"Content-Type": "application/json"},
            )
    return asyncio.run(inner())


def stale_cookie(settings, *, age=400):
    return create_session_token(settings, "usr_model_owner", now=int(time.time()) - age)


def legacy_cookie(settings):
    return auth._signed_token(
        settings.session_secret, "padiem-chat/session/v1",
        {"v": 1, "uid": "usr_model_owner", "exp": int(time.time()) + 3600},
    )


# --- authority and transport -------------------------------------------------

def test_anonymous_is_rejected_before_any_upstream_call():
    source = Source()
    app, settings = built_app(source=source)
    response = call(app, settings, "/api/admin/model-admin/registry", owner=None)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert source.calls == []


def test_non_owner_is_forbidden_before_any_upstream_call():
    source = Source()
    app, settings = built_app(admin=GlobalAdmin(False), source=source)
    response = call(app, settings, "/api/admin/model-admin/registry")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "global_model_admin_forbidden"
    assert source.calls == []


def test_missing_source_is_reported_not_empty():
    app, settings = built_app(source="absent")
    response = call(app, settings, "/api/admin/model-admin/registry")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "b14_model_ops_unconfigured"


def test_registry_relay_returns_the_installed_document():
    source = Source(payload={"ok": True, "models": [{"id": "a/b"}],
                             "providers": [], "groups": {}})
    app, settings = built_app(source=source)
    response = call(app, settings, "/api/admin/model-admin/registry")
    assert response.status_code == 200
    assert response.json()["models"] == [{"id": "a/b"}]
    assert response.headers["cache-control"].startswith("private, no-store")
    assert source.calls[0][0].endswith("/registry")


def test_unconfigured_proof_stays_distinct_from_a_refusal():
    app, settings = built_app(source=Source(error=ModelOpsUnavailable(PROOF_UNCONFIGURED)))
    response = call(app, settings, "/api/admin/model-admin/registry")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == PROOF_UNCONFIGURED


def test_refused_upstream_keeps_its_closed_code():
    app, settings = built_app(source=Source(error=ModelOpsUnavailable(REFUSED)))
    response = call(app, settings, "/api/admin/model-admin/registry")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == REFUSED


def test_unexpected_transport_failure_is_not_reported_as_success():
    app, settings = built_app(source=Source(error=RuntimeError("driver traceback")))
    response = call(app, settings, "/api/admin/model-admin/registry")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "b14_model_ops_unavailable"


def test_b14_error_code_is_relayed_bounded():
    source = Source(409, {"ok": False, "error": {
        "code": "model_probe_required", "message": "점검을 먼저 통과해야 합니다.",
    }})
    app, settings = built_app(source=source)
    response = call(app, settings, "/api/admin/model-admin/model-apply",
                    method="POST", body=json.dumps({"model": {}}))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "model_probe_required"


def test_b14_error_code_is_never_echoed_when_malformed():
    source = Source(409, {"ok": False, "error": {"code": "Bad Code!", "message": "x"}})
    app, settings = built_app(source=source)
    response = call(app, settings, "/api/admin/model-admin/model-apply",
                    method="POST", body=json.dumps({"model": {}}))
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "b14_model_ops_invalid_response"


def test_unknown_status_is_not_passed_through():
    app, settings = built_app(source=Source(302, {"ok": True}))
    response = call(app, settings, "/api/admin/model-admin/registry")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "b14_model_ops_invalid_response"


def test_success_without_ok_is_not_a_success():
    app, settings = built_app(source=Source(200, {"models": []}))
    response = call(app, settings, "/api/admin/model-admin/registry")
    assert response.status_code == 502


def test_secret_field_in_a_regressed_payload_never_reaches_the_browser():
    source = Source(payload={"ok": True, "models": [{"id": "a/b", "value": CREDENTIAL_VALUE}]})
    app, settings = built_app(source=source)
    response = call(app, settings, "/api/admin/model-admin/registry")
    assert response.status_code == 502
    assert CREDENTIAL_VALUE not in response.text


# --- request bodies ----------------------------------------------------------

def test_malformed_body_is_a_closed_400():
    source = Source()
    app, settings = built_app(source=source)
    response = call(app, settings, "/api/admin/model-admin/provider-apply",
                    method="POST", body="{not json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "request_body_invalid"
    assert source.calls == []


def test_non_object_body_is_a_closed_400():
    source = Source()
    app, settings = built_app(source=source)
    response = call(app, settings, "/api/admin/model-admin/provider-apply",
                    method="POST", body="[]")
    assert response.status_code == 400
    assert source.calls == []


def test_oversized_body_is_rejected_before_the_upstream_call():
    source = Source()
    app, settings = built_app(source=source)
    response = call(app, settings, "/api/admin/model-admin/provider-apply",
                    method="POST", body=json.dumps({"pad": "x" * (70 * 1024)}))
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_body_too_large"
    assert source.calls == []


# --- credential write needs a fresh login ------------------------------------

def test_credential_write_rejects_a_stale_login():
    source = Source(payload={"ok": True})
    app, settings = built_app(source=source)
    response = call(
        app, settings, "/api/admin/model-admin/credential-write", method="POST",
        body=json.dumps({"slot_number": 5, "value": CREDENTIAL_VALUE}),
        cookie=stale_cookie(settings),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "reauth_required"
    assert source.calls == []


def test_credential_write_rejects_a_cookie_without_an_issue_time():
    source = Source(payload={"ok": True})
    app, settings = built_app(source=source)
    response = call(
        app, settings, "/api/admin/model-admin/credential-write", method="POST",
        body=json.dumps({"slot_number": 5, "value": CREDENTIAL_VALUE}),
        cookie=legacy_cookie(settings),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "reauth_required"
    assert source.calls == []


def test_credential_write_accepts_a_fresh_login_and_returns_no_value():
    source = Source(payload={
        "ok": True, "slot_number": 5, "slot": "PADIEM_B14_CREDENTIAL_05",
        "configured": True, "length": len(CREDENTIAL_VALUE),
        "last4": CREDENTIAL_VALUE[-4:], "target": "env_file", "backup_kept": True,
    })
    app, settings = built_app(source=source)
    response = call(
        app, settings, "/api/admin/model-admin/credential-write", method="POST",
        body=json.dumps({"slot_number": 5, "value": CREDENTIAL_VALUE}),
    )
    assert response.status_code == 200
    assert response.json()["last4"] == CREDENTIAL_VALUE[-4:]
    assert CREDENTIAL_VALUE not in response.text
    assert source.calls[0][1]["slot_number"] == 5


def test_other_write_routes_do_not_require_a_fresh_login():
    source = Source(payload={"ok": True, "provider_count": 3})
    app, settings = built_app(source=source)
    response = call(
        app, settings, "/api/admin/model-admin/provider-apply", method="POST",
        body=json.dumps({"provider": {"provider_id": "example"}}),
        cookie=stale_cookie(settings),
    )
    assert response.status_code == 200


# --- the session claim -------------------------------------------------------

def test_session_token_carries_the_issue_time():
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password", public_base_url=BASE,
        session_secret="issue-time-test-session-secret-value", session_max_age_seconds=3600,
    )
    token = create_session_token(settings, "usr_issued", now=1_000)
    claims = decode_session_claims(settings, token, now=1_000)
    assert claims is not None
    assert claims.user_id == "usr_issued"
    assert claims.issued_at == 1_000


def test_missing_issue_time_stays_a_valid_old_session():
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password", public_base_url=BASE,
        session_secret="issue-time-test-session-secret-value", session_max_age_seconds=3600,
    )
    token = auth._signed_token(
        settings.session_secret, "padiem-chat/session/v1",
        {"v": 1, "uid": "usr_old", "exp": 5_000},
    )
    claims = decode_session_claims(settings, token, now=1_000)
    assert claims is not None
    assert claims.issued_at is None


@pytest.mark.parametrize("bad", ["1000", -1, True, 1.5, [1]])
def test_a_malformed_issue_time_invalidates_the_token(bad):
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password", public_base_url=BASE,
        session_secret="issue-time-test-session-secret-value", session_max_age_seconds=3600,
    )
    token = auth._signed_token(
        settings.session_secret, "padiem-chat/session/v1",
        {"v": 1, "uid": "usr_bad", "iat": bad, "exp": 5_000},
    )
    assert decode_session_claims(settings, token, now=1_000) is None