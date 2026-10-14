"""#4139 real product app owner-consent route wiring, no production deployment.

Browser issue/grant/revoke are a separate authenticated owner lane; only
the canonical device-initiated WSS can redeem the credential.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.app_factory import create_app
from app.config import Settings
from app import claw_connector_enrollment_routes as owner_handlers
from app.connector_owner_runtime_mount import (
    ExactOwnerOrigin,
    OWNER_REGISTRATION_PRODUCTION_DEFAULT_MOUNTED,
    compose_owner_enrollment_from_worker,
)
from app.worker_config import (
    IDENTITY_AUTHORITY_SERVICE_BINDING_NAME as I,
    LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME as B,
)
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

ENABLED = {
    "PADIEM_CONNECTOR_OWNER_ENROLLMENT_ENABLED": "enabled",
    "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "isolated-operator-acceptance-4139",
}
ORIGIN = "https://chat.padiem.net"


class PrivateIdentity:
    def __getattr__(self, method):
        if method in (
            "grant_connector_enrollment_consent", "revoke_connector_enrollment_consent",
            "resolve_connector_enrollment_consent_for_device",
            "bind_connector_enrollment_challenge", "authorize_connector_enrollment_redeem",
        ):
            async def no_network(*args, **kw):
                raise AssertionError("private identity RPC not needed for this test")
            return no_network
        raise AttributeError(method)


class PrivateBroker:
    def __getattr__(self, method):
        if method in (
            "issue_enrollment_challenge", "get_enrollment_binding",
            "verify_enrollment_bootstrap", "redeem_enrollment", "revoke_binding",
        ):
            async def no_network(*args, **kw):
                raise AssertionError("private broker RPC not needed for this test")
            return no_network
        raise AttributeError(method)


def env():
    return {**ENABLED, I: PrivateIdentity(), B: PrivateBroker()}


def request(app, path, data, *, origin=ORIGIN):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
        ) as client:
            return await client.post(
                path, json=data, headers={"Origin": origin},
            )
    return asyncio.run(run())


def settings():
    return replace(Settings.from_env(), public_base_url=ORIGIN)


def test_product_default_has_no_owner_enrollment_routes():
    assert OWNER_REGISTRATION_PRODUCTION_DEFAULT_MOUNTED is False
    app = create_app(settings=settings())
    assert not any("/api/claw/connector/enrollments/" in getattr(r, "path", "") for r in app.routes)
    assert app.state.connector_enrollment_async_host is None
    assert app.state.connector_enrollment_browser_csrf is None
    for partial in (
        {}, {"PADIEM_CONNECTOR_OWNER_ENROLLMENT_ENABLED": "enabled"},
        {"PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": ENABLED["PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE"]},
        {**ENABLED, "PADIEM_CONNECTOR_OWNER_ENROLLMENT_ENABLED": True},
        {**ENABLED, "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "production"},
    ):
        assert compose_owner_enrollment_from_worker(partial) is None


def test_armed_missing_or_incomplete_authorities_fail_before_route_mount():
    for partial in (ENABLED, {**ENABLED, I: PrivateIdentity()},
                    {**ENABLED, B: PrivateBroker()},
                    {**ENABLED, I: object(), B: PrivateBroker()},
                    {**ENABLED, I: PrivateIdentity(), B: object()}):
        with pytest.raises(ValueError, match="authority unavailable"):
            compose_owner_enrollment_from_worker(partial)


def test_real_app_mounts_only_three_owner_mutations_not_http_redeem():
    ports = compose_owner_enrollment_from_worker(env())
    assert ports is not None
    app = create_app(settings=settings(), connector_owner_enrollment=ports)
    paths = [r.path for r in app.routes]
    for suffix in ("/consent/grant", "/consent/revoke", "/issue"):
        path = "/api/claw/connector/enrollments" + suffix
        assert path in paths
        assert next(r for r in app.routes if r.path == path).methods == {"POST"}
    assert "/api/claw/connector/enrollments/redeem" not in paths
    assert paths.index("/api/claw/connector/enrollments/issue") < len(paths) - 1
    assert app.routes[-1].name == "static"
    assert app.state.control_plane_identity_authority is ports.identity
    assert app.state.connector_enrollment_async_host is ports.host
    assert app.state.connector_enrollment_browser_csrf is ports.csrf
    # No valid session: existing auth blocks before any private Broker call.
    denied = request(app, "/api/claw/connector/enrollments/issue", {"device_id": "device.1"})
    assert denied.status_code in (401, 503)


def test_owner_origin_guard_fails_closed_with_no_host_or_foreign_browser():
    csrf = ExactOwnerOrigin()
    app = SimpleNamespace(state=SimpleNamespace(settings=settings()))
    for origin in (None, "https://evil.example", "http://chat.padiem.net",
                   "https://chat.padiem.net.evil.example", ""):
        req = SimpleNamespace(
            app=app, method="POST",
            headers={"content-type": "application/json", "origin": origin},
        )
        assert csrf.verify(req) is False
    req = SimpleNamespace(
        app=app, method="POST",
        headers={"content-type": "application/json", "origin": ORIGIN},
    )
    assert csrf.verify(req) is True
    app.state.settings = replace(settings(), public_base_url=None)
    assert csrf.verify(req) is False


def test_real_product_app_uses_signed_b54_owner_and_canonical_issue_only(monkeypatch):
    ports = compose_owner_enrollment_from_worker(env())
    assert ports is not None
    app = create_app(settings=settings(), connector_owner_enrollment=ports)
    moment = datetime.now(timezone.utc)
    signed = AuthSessionSnapshot(
        session_id="session.canonical.1", product_id="b54-padiem-claw",
        subject=CanonicalSubjectRef(
            subject_type=SubjectType.USER, subject_id="canonical.subject.1",
        ),
        issued_at=moment-timedelta(minutes=1),
        expires_at=moment+timedelta(hours=1),
        state=AuthSessionState.ACTIVE, tenant_id="tenant.1",
    )
    monkeypatch.setattr(owner_handlers, "auth_ready", lambda request: True)
    monkeypatch.setattr(owner_handlers, "current_user_id", lambda request: "product.user.1")
    async def bridge(request):
        return SimpleNamespace(product_user_id="product.user.1", auth_session=signed)
    monkeypatch.setattr(owner_handlers, "resolve_current_b54_canonical_session", bridge)
    calls = []

    async def grant(**kw):
        calls.append(("consent", kw))
        return {
            "consent_id": "consent.1", "device_id": kw["device_id"],
            "granted_at": datetime.now(timezone.utc).isoformat(),
            "withdrawn_at": None, "dispatch_authorized": False,
            "grants_read": False, "grants_write": False,
        }

    async def issue(**kw):
        calls.append(("issue", kw))
        return {
            "challenge": {"challenge_id": "challenge.1", "device_id": kw["device_id"]},
            "pairing_code": "synthetic-test-only",
            "code_returned_once": True,
            "raw_device_credential": False, "dispatch_authorized": False,
        }

    monkeypatch.setattr(ports.identity, "grant_connector_enrollment_consent", grant)
    monkeypatch.setattr(ports.host, "issue", issue)
    bad = request(app, "/api/claw/connector/enrollments/consent/grant", {
        "device_id": "device.1", "confirmed": True,
        "confirmation_version": "pc-enrollment-consent-v1",
    }, origin="https://evil.example")
    assert bad.status_code == 403 and calls == []
    good = request(app, "/api/claw/connector/enrollments/consent/grant", {
        "device_id": "device.1", "confirmed": True,
        "confirmation_version": "pc-enrollment-consent-v1",
    })
    assert good.status_code == 200
    issued = request(app, "/api/claw/connector/enrollments/issue", {
        "device_id": "device.1",
    })
    assert issued.status_code == 200
    assert calls[0][1]["session_id"] == signed.session_id
    assert calls[1][1] == {
        "canonical_session_id": signed.session_id, "device_id": "device.1",
    }


class PrivateOneClickBroker(PrivateBroker):
    def __init__(self):
        self.calls = []

    def __getattr__(self, method):
        if method in ("reserve_pending_pc_link", "deliver_pending_pc_link"):
            async def no_network(payload):
                self.calls.append((method, payload))
                # This is a transport stub; real Broker DO must own actual
                # live PC socket and a one-use SQLite pending offer.
                raise RuntimeError("source-only: no live Broker PC WSS")
            return no_network
        return super().__getattr__(method)


def test_review_one_click_requires_separate_server_flag_and_private_broker_rpc():
    from app.connector_one_click_approval_route import OWNER_APPROVE_LINK_PATH
    from app.connector_owner_one_click_factory import VerifiedOwnerOneClickFactory

    owner_env = env()
    owner_env["PADIEM_CONNECTOR_OWNER_ONE_CLICK_ENABLED"] = "enabled"
    with pytest.raises(ValueError, match="canonical Broker owner private RPC missing"):
        compose_owner_enrollment_from_worker(owner_env)

    private = PrivateOneClickBroker()
    owner_env[B] = private
    ports = compose_owner_enrollment_from_worker(owner_env)
    assert ports is not None
    assert type(ports.one_click_factory) is VerifiedOwnerOneClickFactory
    application = create_app(settings=settings(), connector_owner_enrollment=ports)
    assert application.state.connector_one_click_approval_factory is ports.one_click_factory
    assert OWNER_APPROVE_LINK_PATH in {r.path for r in application.routes}
    assert next(
        r.methods for r in application.routes if r.path == OWNER_APPROVE_LINK_PATH
    ) == {"POST"}

    # No signed B54 owner session: deny before even calling broker service.
    denied = request(application, OWNER_APPROVE_LINK_PATH, {
        "request_ref": "link."+"a"*32, "confirmed": True,
        "confirmation_version": "pc-enrollment-consent-v1",
    })
    assert denied.status_code in (401, 503)
    assert private.calls == []

    # Even in the explicit acceptance configuration there is NO public
    # enrollment-redeem route and no private code reflected to browser.
    assert "/api/claw/connector/enrollments/redeem" not in {
        r.path for r in application.routes
    }


def test_review_one_click_flag_does_not_override_normal_owner_default():
    from app.connector_one_click_approval_route import OWNER_APPROVE_LINK_PATH

    for value in ("true", True, "1", "on", None):
        provided=env()
        provided["PADIEM_CONNECTOR_OWNER_ONE_CLICK_ENABLED"] = value
        ports=compose_owner_enrollment_from_worker(provided)
        assert ports is not None and ports.one_click_factory is None
        app=create_app(settings=settings(),connector_owner_enrollment=ports)
        assert app.state.connector_one_click_approval_factory is None
        assert OWNER_APPROVE_LINK_PATH not in {r.path for r in app.routes}

    # One-click alone, without the canonical owner enrollment gates,
    # never exposes any browser route.
    assert compose_owner_enrollment_from_worker({
        "PADIEM_CONNECTOR_OWNER_ONE_CLICK_ENABLED": "enabled",
        I: PrivateIdentity(), B: PrivateOneClickBroker(),
    }) is None


class PrivateIdentityPcBroker(PrivateOneClickBroker):
    """Stub only; the real private DO gate is tested in the Broker suite."""
    def __getattr__(self, method):
        if method in ("pending_pc_identity_status", "claim_pending_pc_identity_proof"):
            async def no_network(payload):
                raise RuntimeError("source-only: no actual PC registered")
            return no_network
        return super().__getattr__(method)


def test_native_pc_identity_preflight_requires_separate_one_click_gate():
    from app.connector_owner_identity_pc_completion import (
        CanonicalOwnerPcIdentityPreflight,
        B54_NATIVE_PC_IDENTITY_COMPLETION_ROUTE_MOUNTED,
    )
    from app.connector_one_click_approval_route import OWNER_APPROVE_LINK_PATH

    preflight_flag="PADIEM_CONNECTOR_OWNER_PC_IDENTITY_PREFLIGHT_ENABLED"
    owner_env=env()
    owner_env[B]=PrivateIdentityPcBroker()
    owner_env[preflight_flag]="enabled"
    with pytest.raises(ValueError,match="one-click owner enrollment"):
        compose_owner_enrollment_from_worker(owner_env)

    owner_env["PADIEM_CONNECTOR_OWNER_ONE_CLICK_ENABLED"]="enabled"
    ports=compose_owner_enrollment_from_worker(owner_env)
    assert type(ports.identity_pc_preflight) is CanonicalOwnerPcIdentityPreflight
    assert ports.one_click_factory is not None
    application=create_app(settings=settings(),connector_owner_enrollment=ports)
    assert OWNER_APPROVE_LINK_PATH in {r.path for r in application.routes}
    # The new proof is a private B54 Service Binding only, not a public
    # redeem/DPAPI completion endpoint or a browser-readable proof.
    assert B54_NATIVE_PC_IDENTITY_COMPLETION_ROUTE_MOUNTED is False
    assert not any("identity-proof" in r.path for r in application.routes)
    assert "/api/claw/connector/enrollments/redeem" not in {
        r.path for r in application.routes
    }


def test_wrong_native_identity_preflight_flag_does_not_change_existing_routes():
    flag="PADIEM_CONNECTOR_OWNER_PC_IDENTITY_PREFLIGHT_ENABLED"
    for value in ("true",True,"1",None):
        owner_env=env()
        owner_env[B]=PrivateOneClickBroker()
        owner_env["PADIEM_CONNECTOR_OWNER_ONE_CLICK_ENABLED"]="enabled"
        owner_env[flag]=value
        ports=compose_owner_enrollment_from_worker(owner_env)
        assert ports.identity_pc_preflight is None
        assert ports.one_click_factory is not None


class PrivateNativeGatewayBroker(PrivateIdentityPcBroker):
    def __getattr__(self, method):
        if method in (
            "reserve_native_pc_gateway", "authenticate_native_pc_gateway",
            "transfer_native_pc_credential_once",
            "receive_native_pc_install_ack", "authenticate_native_pc_install_ack",
        ):
            async def no_network(payload):
                raise RuntimeError("default-off reviewed synthetic transport")
            return no_network
        return super().__getattr__(method)


def test_canonical_native_gateway_completion_has_three_separate_server_gates():
    from app.connector_owner_native_pc_completion import (
        CanonicalOwnerNativePcCompletion, NATIVE_OWNER_PC_COMPLETION_PUBLIC_MOUNTED,
        NATIVE_OWNER_PC_COMPLETION_PRODUCTION_ENABLED,
    )
    from app.connector_one_click_approval_route import OWNER_APPROVE_LINK_PATH

    flag="PADIEM_CONNECTOR_OWNER_PC_NATIVE_DELIVERY_ENABLED"
    owner_env=env()
    owner_env[B]=PrivateNativeGatewayBroker()
    owner_env[flag]="enabled"
    with pytest.raises(ValueError,match="identity preflight required"):
        compose_owner_enrollment_from_worker(owner_env)

    owner_env["PADIEM_CONNECTOR_OWNER_ONE_CLICK_ENABLED"]="enabled"
    owner_env["PADIEM_CONNECTOR_OWNER_PC_IDENTITY_PREFLIGHT_ENABLED"]="enabled"
    ports=compose_owner_enrollment_from_worker(owner_env)
    assert type(ports.native_pc_completion) is CanonicalOwnerNativePcCompletion
    assert ports.identity_pc_preflight is not None
    assert ports.one_click_factory is not None
    application=create_app(settings=settings(),connector_owner_enrollment=ports)
    assert OWNER_APPROVE_LINK_PATH in {r.path for r in application.routes}
    assert "/api/claw/connector/enrollments/redeem" not in {
        r.path for r in application.routes
    }
    assert NATIVE_OWNER_PC_COMPLETION_PUBLIC_MOUNTED is False
    assert NATIVE_OWNER_PC_COMPLETION_PRODUCTION_ENABLED is False

    # Wrong/absent opt-in leaves the approved B54 consent pathway working,
    # with no native credential delivery/redeem endpoint registered.
    for value in (None,True,"1","on"):
        source=dict(owner_env)
        source[flag]=value
        p=compose_owner_enrollment_from_worker(source)
        assert p.native_pc_completion is None
        assert p.identity_pc_preflight is not None


def test_missing_protected_same_DO_delivery_ports_are_rejected_before_activation():
    owner_env=env()
    owner_env[B]=PrivateIdentityPcBroker()
    owner_env.update({
        "PADIEM_CONNECTOR_OWNER_ONE_CLICK_ENABLED":"enabled",
        "PADIEM_CONNECTOR_OWNER_PC_IDENTITY_PREFLIGHT_ENABLED":"enabled",
        "PADIEM_CONNECTOR_OWNER_PC_NATIVE_DELIVERY_ENABLED":"enabled",
    })
    with pytest.raises(ValueError,match="same-PC private native gateway"):
        compose_owner_enrollment_from_worker(owner_env)


def test_all_logged_in_accounts_use_normal_identity_ports_not_ceo_whitelist():
    # Server-side "owner" means the signed-in owner of EACH device.
    # It is never the representative account or one configured user ID.
    cfg = {
        **env(),
        "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "owner-controlled-production-4139",
        "PADIEM_CONNECTOR_OWNER_PRODUCTION_ENABLED": "enabled",
    }
    ports = compose_owner_enrollment_from_worker(cfg)
    assert ports is not None
    app = create_app(settings=settings(), connector_owner_enrollment=ports)
    assert any(
        getattr(r, "path", "") == "/api/claw/connector/enrollments/setup"
        for r in app.routes
    )
    assert "OWNER_ACCOUNT_ID" not in cfg
    del cfg["PADIEM_CONNECTOR_OWNER_PRODUCTION_ENABLED"]
    assert compose_owner_enrollment_from_worker(cfg) is None
