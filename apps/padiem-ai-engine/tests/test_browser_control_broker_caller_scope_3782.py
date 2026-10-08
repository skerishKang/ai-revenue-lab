"""#3782 Broker-only audience requires existing verified Engine caller identity.

No bearer authority is minted by a name. The registry validates a secret
and the Engine app, while the owner-controlled second audience denies B54.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.auth_boundary_diagnostic import P01_CHAT_CALLER_ID
from app.browser_control_broker_caller_scope import (
    BROKER_P01_CALLER_ID_ENV,
    BROKER_P01_CALLER_SCOPE_WIRED,
    authenticate_broker_p01_receipt_reader,
)
from app.identity_enforcement import CALLER_CREDENTIAL_HEADER, CALLER_ID_HEADER

ENGINE_APP = "b54-engine-browser-approval"
BROKER = "broker-browser-p01"
SECRET = "K" * 48
CHAT = "b54-p01-overlay-20260914-a1"


class Env:
    PADIEM_ENGINE_CALLER_ID = BROKER
    PADIEM_ENGINE_CALLER_SECRET = SECRET
    PADIEM_ENGINE_ALLOWED_APPS = ENGINE_APP
    PADIEM_ENGINE_BROWSER_BROKER_CALLER_ID = BROKER


def _check(env=None, headers=None, app=ENGINE_APP):
    if env is None:
        env = Env()
    if headers is None:
        headers = {
            CALLER_ID_HEADER: BROKER,
            CALLER_CREDENTIAL_HEADER: SECRET,
        }
    return authenticate_broker_p01_receipt_reader(
        env=env, headers=headers, requested_app_id=app,
    )


def test_canonical_broker_authenticated_secret_and_allowed_app_only():
    assert BROKER_P01_CALLER_SCOPE_WIRED is False
    assert BROKER_P01_CALLER_ID_ENV == "PADIEM_ENGINE_BROWSER_BROKER_CALLER_ID"
    assert _check() is True


@pytest.mark.parametrize("change", [
    {CALLER_ID_HEADER: CHAT},
    {CALLER_ID_HEADER: "other-registered-caller"},
    {CALLER_ID_HEADER: BROKER, CALLER_CREDENTIAL_HEADER: "X" * 48},
    {CALLER_ID_HEADER: BROKER, CALLER_CREDENTIAL_HEADER: ""},
    {CALLER_ID_HEADER: BROKER, CALLER_CREDENTIAL_HEADER: SECRET[:-2]},
])
def test_spoofed_role_or_credential_does_not_read_broker_p01(change):
    wire = {CALLER_ID_HEADER: BROKER, CALLER_CREDENTIAL_HEADER: SECRET}
    wire.update(change)
    assert _check(headers=wire) is False
    assert SECRET not in repr(change)


def test_b54_existing_engine_credential_cannot_claim_broker_audience():
    assert P01_CHAT_CALLER_ID == CHAT

    class SameChatIdentity:
        PADIEM_ENGINE_CALLER_ID = CHAT
        PADIEM_ENGINE_CALLER_SECRET = SECRET
        PADIEM_ENGINE_ALLOWED_APPS = ENGINE_APP
        PADIEM_ENGINE_BROWSER_BROKER_CALLER_ID = CHAT

    assert _check(
        env=SameChatIdentity(),
        headers={CALLER_ID_HEADER: CHAT, CALLER_CREDENTIAL_HEADER: SECRET},
    ) is False


@pytest.mark.parametrize("expected", [
    None, "", "b54-some-valid-app", "b62-some-service",
    "b54-kagent", "Bad Spaces", "../bad", "x" * 200,
])
def test_unprovisioned_or_product_identity_audience_fails_closed(expected):
    class Config:
        PADIEM_ENGINE_CALLER_ID = BROKER
        PADIEM_ENGINE_CALLER_SECRET = SECRET
        PADIEM_ENGINE_ALLOWED_APPS = ENGINE_APP
        PADIEM_ENGINE_BROWSER_BROKER_CALLER_ID = expected

    assert _check(env=Config()) is False


def test_broker_cannot_read_other_engine_app_even_with_valid_credential():
    assert _check(app="another.app") is False


def test_worker_enforces_audience_after_existing_auth_and_before_service():
    worker = (
        Path(__file__).resolve().parents[1] / "worker_identity.py"
    ).read_text(encoding="utf-8")
    body = worker.split("async def _fetch_browser_broker_receipt_read", 1)[1].split(
        "async def _fetch_browser_owner_p01_resume", 1
    )[0]
    assert body.index("_authenticate_non_health_request(") < body.index(
        "authenticate_broker_p01_receipt_reader("
    ) < body.index("services.browser_p01_broker_receipt_read")
    assert "_read_requested_app_id(body)" in body
    assert "browser_p01_broker_caller_denied" in body
    assert "browser_p01_broker_receipt_read=" not in worker
