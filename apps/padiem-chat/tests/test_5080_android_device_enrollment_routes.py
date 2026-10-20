"""#5080: the Android device enrollment challenge route.

The route must reuse the canonical enrollment exactly: the owner session, the
canonical Identity consent, the canonical asynchronous enrollment host and the
canonical Broker challenge. It releases the one-time pairing code to the DEVICE
and never a credential, a browser reference or an account/workspace scope.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "padiem-chat"))

from starlette.requests import Request  # noqa: E402


def _receive(payload: bytes):
    async def _call() -> dict[str, Any]:
        return {"type": "http.request", "body": payload, "more_body": False}

    return _call


def _request(
    body: bytes,
    *,
    content_type: str = "application/json",
    path: str = "/api/claw/connector/android-enrollment/challenge",
    app: Any = None,
) -> Request:
    headers = [(b"content-type", content_type.encode("utf-8"))]
    if body:
        headers.append((b"content-length", str(len(body)).encode("ascii")))
    scope: dict[str, Any] = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("chat.padiem.net", 443),
    }
    if app is not None:
        scope["app"] = app
    return Request(scope, _receive(body))


def _module():
    import app.android_device_enrollment_routes as module

    return module


def _valid_body(**overrides: Any) -> bytes:
    payload = {
        "device_id": "device.android.1",
        "confirmed": True,
        "confirmation_version": "android-enrollment-consent-v1",
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


def _consent_fields(body: bytes) -> dict[str, Any] | None:
    module = _module()
    return asyncio.run(module._consent_payload(
        _request(body), frozenset({"device_id", "confirmed", "confirmation_version"}),
    ))


def test_the_closed_consent_payload_is_accepted() -> None:
    fields = _consent_fields(_valid_body())
    assert fields is not None
    assert fields["device_id"] == "device.android.1"
    assert fields["confirmed"] is True
    assert fields["confirmation_version"] == "android-enrollment-consent-v1"


@pytest.mark.parametrize("body", [
    _valid_body(device_id="../escape"),
    _valid_body(device_id=""),
    _valid_body(device_id="device android"),
    _valid_body(confirmed=False),
    _valid_body(confirmed="true"),
    json.dumps({"device_id": "device.android.1"}).encode("utf-8"),
    json.dumps({
        "device_id": "device.android.1", "confirmed": True,
        "confirmation_version": "android-enrollment-consent-v1", "extra": "x",
    }).encode("utf-8"),
])
def test_an_out_of_contract_consent_payload_is_refused(body: bytes) -> None:
    assert _consent_fields(body) is None


def test_a_non_json_content_type_is_refused() -> None:
    module = _module()
    fields = asyncio.run(module._consent_payload(
        _request(_valid_body(), content_type="text/plain"),
        frozenset({"device_id", "confirmed", "confirmation_version"}),
    ))
    assert fields is None


def test_an_oversized_body_is_refused() -> None:
    module = _module()
    fields = asyncio.run(module._consent_payload(
        _request(b"x" * (module.MAX_BODY_BYTES + 1)),
        frozenset({"device_id", "confirmed", "confirmation_version"}),
    ))
    assert fields is None


def _install_session_stubs(route_module: Any, monkeypatch: Any) -> None:
    import app.auth_routes as auth_routes
    import app.b54_canonical_session as session_module

    class _Session:
        product_id = "b54-padiem-claw"
        session_id = "session.android.1"
        tenant_id = "tenant.1"

        def is_active(self, *, now: Any) -> bool:
            return True

    class _Bridged:
        product_user_id = "user-1"
        auth_session = _Session()

    async def _resolve(request: Any) -> Any:
        return _Bridged()

    monkeypatch.setattr(
        session_module, "resolve_current_b54_canonical_session", _resolve,
    )
    monkeypatch.setattr(auth_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(auth_routes, "current_user_id", lambda request: "user-1")
    # The route checks the canonical session type; the stub stands in for it.
    monkeypatch.setattr(route_module, "AuthSessionSnapshot", _Session)


def test_the_route_releases_the_pairing_code_to_the_device(monkeypatch: Any) -> None:
    """The device gets the challenge and the one-time code, never a credential."""
    import app.android_device_enrollment_routes as route_module

    granted: dict[str, Any] = {}
    issued: dict[str, Any] = {}

    class _Identity:
        async def grant_connector_enrollment_consent(self, **kwargs: Any) -> dict[str, Any]:
            granted.update(kwargs)
            return {"device_id": kwargs.get("device_id"), "withdrawn_at": None}

    class _Host:
        async def issue(self, **kwargs: Any) -> dict[str, Any]:
            issued.update(kwargs)
            return {
                "challenge": {
                    "challenge_id": "challenge.android.1",
                    "expires_at": "2026-10-20T00:10:00Z",
                },
                "pairing_code": "a" * 32,
            }

    class _State:
        connector_enrollment_async_host = _Host()
        control_plane_identity_authority = _Identity()

    class _App:
        state = _State()

    _install_session_stubs(route_module, monkeypatch)
    response = asyncio.run(
        route_module.android_enrollment_challenge(_request(_valid_body(), app=_App()))
    )
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["ok"] is True
    assert body["challenge_id"] == "challenge.android.1"
    assert body["pairing_code"] == "a" * 32
    # The credential, the binding and the account/workspace scope never leave.
    rendered = json.dumps(body)
    assert "credential" not in rendered
    assert "binding_ref" not in rendered
    assert "account_ref" not in rendered
    assert "workspace_ref" not in rendered
    # The consent was granted for THIS device through the canonical Identity port.
    assert granted["device_id"] == "device.android.1"
    assert granted["confirmed"] is True
    assert issued["device_id"] == "device.android.1"


def test_the_route_fails_closed_without_the_canonical_authorities(monkeypatch: Any) -> None:
    import app.android_device_enrollment_routes as route_module

    class _State:
        connector_enrollment_async_host = None
        control_plane_identity_authority = None

    class _App:
        state = _State()

    _install_session_stubs(route_module, monkeypatch)
    response = asyncio.run(
        route_module.android_enrollment_challenge(_request(_valid_body(), app=_App()))
    )
    assert response.status_code == 503
    assert json.loads(response.body)["error"]["code"] == "enrollment_server_dependency_unavailable"


def test_the_route_fails_closed_without_an_owner_session(monkeypatch: Any) -> None:
    import app.android_device_enrollment_routes as route_module
    import app.auth_routes as auth_routes

    monkeypatch.setattr(auth_routes, "auth_ready", lambda request: False)
    monkeypatch.setattr(auth_routes, "current_user_id", lambda request: None)
    response = asyncio.run(
        route_module.android_enrollment_challenge(_request(_valid_body()))
    )
    assert response.status_code == 401
    assert json.loads(response.body)["error"]["code"] == "canonical_session_required"


def test_the_route_refuses_another_lanes_confirmation_version(monkeypatch: Any) -> None:
    """The PC consent version is not accepted on the Android device route."""
    import app.android_device_enrollment_routes as route_module

    class _Identity:
        async def grant_connector_enrollment_consent(self, **kwargs: Any) -> dict[str, Any]:
            return {"device_id": kwargs.get("device_id"), "withdrawn_at": None}

    class _Host:
        async def issue(self, **kwargs: Any) -> dict[str, Any]:
            return {"challenge": {"challenge_id": "c"}, "pairing_code": "a" * 32}

    class _State:
        connector_enrollment_async_host = _Host()
        control_plane_identity_authority = _Identity()

    class _App:
        state = _State()

    _install_session_stubs(route_module, monkeypatch)
    response = asyncio.run(route_module.android_enrollment_challenge(
        _request(
            _valid_body(confirmation_version="pc-enrollment-consent-v1"), app=_App(),
        )
    ))
    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == "connector_enrollment_invalid_request"
