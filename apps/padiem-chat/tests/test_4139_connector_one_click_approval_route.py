"""Unmounted no-manual-code browser approval HTTP boundary — fake PC only."""
from __future__ import annotations

import asyncio

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Route

from app import connector_one_click_approval_route as page
from app.app_factory import create_app
from app.config import Settings
from app.connector_one_click_approval import ONE_CLICK_ENROLLMENT_HTTP_MOUNTED
from test_4139_connector_one_click_approval import Fixture, REQUEST, CODE, session


def post(*, monkeypatch, payload=None, fixture=None, signed=True, configured=True,
         completion=None):
    fx = fixture or Fixture()
    application = Starlette(routes=[
        Route(page.OWNER_APPROVE_LINK_PATH, page.owner_approve_pc_link, methods=["POST"])
    ])
    if configured:
        application.state.connector_one_click_approval = fx.service()
    if completion is not None:
        application.state.connector_owner_native_pc_completion = completion

    async def owner(request):
        if signed:
            return session(), None
        from app.claw_connector_enrollment_routes import _error
        return None, _error(401, "canonical_session_required")
    monkeypatch.setattr(page, "_verified_owner_request", owner)

    if payload is None:
        payload = {"request_ref": REQUEST}

    async def call():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="https://chat.padiem.net",
        ) as client:
            return await client.post(page.OWNER_APPROVE_LINK_PATH, json=payload)
    return asyncio.run(call()), fx


def test_unmounted_for_default_and_existing_owner_registration_routes():
    assert page.OWNER_APPROVE_LINK_MOUNTED is False
    assert ONE_CLICK_ENROLLMENT_HTTP_MOUNTED is False
    application = create_app(settings=Settings.from_env())
    assert page.OWNER_APPROVE_LINK_PATH not in {
        getattr(route, "path", None) for route in application.routes
    }


def test_one_click_owner_http_ack_is_not_a_connected_or_authenticated_pc(monkeypatch):
    response, fx = post(monkeypatch=monkeypatch)
    assert response.status_code == 200
    assert response.json() == {
        "ok": True, "state": "awaiting_device_confirmation",
        "device_id": "windows.device.1", "connected": False,
        "registered": False, "dispatch_authorized": False,
    }
    assert CODE not in response.text
    assert "challenge.1" not in response.text
    assert response.headers["cache-control"].startswith("no-store")
    assert [event[0] for event in fx.calls] == [
        "attest", "consent", "issue", "deliver",
    ]


def test_non_owner_denied_before_even_fetching_pending_pc(monkeypatch):
    response, fx = post(monkeypatch=monkeypatch, signed=False)
    assert response.status_code == 401
    assert fx.calls == []


def test_configured_completion_reuses_original_owner_and_confirms_installation(monkeypatch):
    from app.connector_owner_native_pc_completion import CanonicalOwnerNativePcCompletion
    calls = []
    async def complete(self, *, signed_owner, request_ref):
        calls.append((signed_owner.session_id, request_ref))
        return {
            "device_id": "windows.device.1", "lifecycle": "paired_offline",
            "credential_installed_by_canonical_handoff": True,
        }
    monkeypatch.setattr(CanonicalOwnerNativePcCompletion, "complete", complete)
    completion = object.__new__(CanonicalOwnerNativePcCompletion)
    response, fx = post(monkeypatch=monkeypatch, completion=completion)
    assert response.status_code == 200
    assert calls == [(session().session_id, REQUEST)]
    assert response.json() == {
        "ok": True, "state": "paired_offline", "device_id": "windows.device.1",
        "registered": True, "connected": False, "dispatch_authorized": False,
    }
    assert [event[0] for event in fx.calls] == ["attest", "consent", "issue", "deliver"]
    assert CODE not in response.text


@pytest.mark.parametrize("failure", [
    "enrollment_credential_handoff_failed", "credential_handoff_unavailable",
    "broker_rpc_invalid", "durable_pairing_store_unavailable",
    "not_a_public_error_" + CODE,
])
def test_failed_completion_never_claims_registered_or_exposes_credential(monkeypatch, failure):
    from app.connector_owner_native_pc_completion import CanonicalOwnerNativePcCompletion
    from app.control_plane_identity import IdentityBridgeError
    async def complete(self, **kwargs):
        raise IdentityBridgeError(503, failure, CODE)
    monkeypatch.setattr(CanonicalOwnerNativePcCompletion, "complete", complete)
    response, fx = post(
        monkeypatch=monkeypatch, completion=object.__new__(CanonicalOwnerNativePcCompletion),
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == (
        failure if failure in page._NATIVE_FAILURE_CODES else "native_pc_registration_unconfirmed"
    )
    assert CODE not in response.text
    assert '"registered":true' not in response.text


def test_missing_transport_dependency_returns_503_before_pc_action(monkeypatch):
    response, fx = post(monkeypatch=monkeypatch, configured=False)
    assert response.status_code == 503
    assert fx.calls == []


def test_explicit_consent_required_without_side_effects(monkeypatch):
    for payload in (
        {"request_ref": REQUEST, "confirmed": False,
         "confirmation_version": "pc-enrollment-consent-v1"},
        {"request_ref": REQUEST, "confirmed": "true",
         "confirmation_version": "pc-enrollment-consent-v1"},
        {"request_ref": REQUEST, "confirmed": True,
         "confirmation_version": "fake"},
        {"request_ref": REQUEST, "confirmed": True,
         "confirmation_version": "pc-enrollment-consent-v1",
         "browser_owner_id": "forged"},
    ):
        response, fx = post(monkeypatch=monkeypatch, payload=payload)
        assert response.status_code == 400
        assert fx.calls == []


def test_untrusted_or_expired_pending_device_rejected(monkeypatch):
    fx = Fixture()
    fx.pending["device_possession_verified"] = False
    response, same = post(monkeypatch=monkeypatch, fixture=fx)
    assert same is fx
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "pending_pc_not_authenticated"
    assert [row[0] for row in fx.calls] == ["attest"]


def test_failed_delivery_never_returns_browser_code_or_success(monkeypatch):
    fx = Fixture()
    fx.delivery_fails = True
    response, _ = post(monkeypatch=monkeypatch, fixture=fx)
    assert response.status_code == 503
    assert CODE not in response.text
    assert response.json()["error"]["code"] == "pc_delivery_unconfirmed"
    assert [row[0] for row in fx.calls] == ["attest", "consent", "issue", "deliver"]


def test_actual_canonical_session_and_same_origin_guard_cannot_be_bypassed(monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace
    from app import claw_connector_enrollment_routes as original
    from app.connector_owner_runtime_mount import ExactOwnerOrigin

    fx = Fixture()
    application = Starlette(routes=[
        Route(page.OWNER_APPROVE_LINK_PATH, page.owner_approve_pc_link, methods=["POST"])
    ])
    application.state.connector_one_click_approval = fx.service()
    application.state.connector_enrollment_browser_csrf = ExactOwnerOrigin()
    application.state.settings = replace(
        Settings.from_env(), public_base_url="https://chat.padiem.net"
    )
    monkeypatch.setattr(original, "auth_ready", lambda request: True)
    monkeypatch.setattr(original, "current_user_id", lambda request: "owner.product")
    current = {"product_user_id": "other", "auth_session": session()}

    async def bridged(request):
        return SimpleNamespace(**current)
    monkeypatch.setattr(original, "resolve_current_b54_canonical_session", bridged)

    payload = {"request_ref": REQUEST}

    async def send(origin):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="https://chat.padiem.net",
        ) as client:
            return await client.post(
                page.OWNER_APPROVE_LINK_PATH, json=payload,
                headers={"Origin": origin},
            )

    assert asyncio.run(send("https://evil.invalid")).status_code == 403
    assert asyncio.run(send("https://chat.padiem.net")).status_code == 401
    current["product_user_id"] = "owner.product"
    current["auth_session"] = session(product="b66-quote")
    assert asyncio.run(send("https://chat.padiem.net")).status_code == 401
    assert fx.calls == []
    current["auth_session"] = session()
    accepted = asyncio.run(send("https://chat.padiem.net"))
    assert accepted.status_code == 200
    assert accepted.json()["connected"] is False
    assert [item[0] for item in fx.calls] == [
        "attest", "consent", "issue", "deliver",
    ]

def test_503_stage_uses_existing_grafana_export_and_never_includes_offer_material(monkeypatch):
    """The next real 503 must yield its HTTP status and safe denial stage in Loki."""
    from app.request_telemetry import (
        RequestTelemetryMiddleware, install_export_scheduler, reset_export_scheduler,
    )
    fx = Fixture()
    fx.attestation_fails = True
    app = Starlette(routes=[
        Route(page.OWNER_APPROVE_LINK_PATH, page.owner_approve_pc_link, methods=["POST"])
    ])
    app.state.connector_one_click_approval = fx.service()

    async def owner(_request):
        return session(), None
    monkeypatch.setattr(page, "_verified_owner_request", owner)
    tasks, batches = [], []

    async def exporter(batch):
        batches.append(batch)

    middleware = RequestTelemetryMiddleware(
        app, exporter=exporter, emitter=lambda _row: None,
    )

    async def probe():
        token = install_export_scheduler(tasks.append)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=middleware),
                base_url="https://chat.padiem.net",
            ) as client:
                response = await client.post(
                    page.OWNER_APPROVE_LINK_PATH, json={"request_ref": REQUEST},
                )
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "pending_pc_unavailable"
            assert len(tasks) == 1
            await tasks[0]
        finally:
            reset_export_scheduler(token)
    asyncio.run(probe())
    assert len(batches) == 1
    http, *stages = batches[0]
    assert http["status"] == 503
    assert http["route"] == page.OWNER_APPROVE_LINK_PATH
    assert stages[-1]["stage"] == "pc_owner.approve"
    assert stages[-1]["code"] == "pending_pc_unavailable"
    assert http["request_id"] == stages[-1]["request_id"]
    contents = str(batches)
    assert REQUEST not in contents
    assert CODE not in contents
    assert "windows.device.1" not in contents
