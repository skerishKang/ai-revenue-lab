"""#COM2 desktop-secret wire (2026-11-03): Chat fills the shared secret state.

The host entry never read ``CLAW_ENGINE_DESKTOP_SECRET``, so
``app.state.claw_engine_desktop_secret`` was always ``None`` and every signed
Engine desktop call answered 503 ``claw_engine_desktop_unconfigured``. These
tests pin the env wiring, the fixed startup marker, and the signing gate that
separates a valid proof from the unconfigured refusal.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app import local_cpython

SECRET = "desktop-shared-" + "x" * 40
BODY = json.dumps(
    {"subject_id": "sub_1", "run_id": "run_1", "mode": "run_status"},
    separators=(",", ":"),
).encode()


def _host_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PADIEM_LOCAL_DEV", "1")
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "mock")
    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "off")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")
    monkeypatch.setenv("PADIEM_CHAT_PUBLIC_BASE_URL", "http://127.0.0.1:8773")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", "test-local-secret-0123456789abcdef")


def test_a_configured_secret_reaches_the_app_state_without_being_logged(
    tmp_path, monkeypatch, capsys,
):
    _host_env(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAW_ENGINE_DESKTOP_SECRET", SECRET)

    app = local_cpython.build_app()

    assert app.state.claw_engine_desktop_secret == SECRET
    printed = capsys.readouterr().out
    assert "[local] claw_engine_desktop_secret=configured" in printed
    assert SECRET not in printed
    assert str(len(SECRET)) not in printed


def test_an_absent_secret_stays_unconfigured_and_fails_closed(
    tmp_path, monkeypatch, capsys,
):
    _host_env(tmp_path, monkeypatch)
    monkeypatch.delenv("CLAW_ENGINE_DESKTOP_SECRET", raising=False)

    app = local_cpython.build_app()

    assert app.state.claw_engine_desktop_secret is None
    printed = capsys.readouterr().out
    assert "[local] claw_engine_desktop_secret=unconfigured" in printed


def _proof_app(secret):
    # Imported here so the test file stays independent of route ordering.
    from app.oracle_mesh_read_return_routes import _verify_engine_proof

    async def endpoint(request):
        raw, error = await _verify_engine_proof(request)
        if error is not None:
            return error
        return JSONResponse({"ok": True, "bytes": len(raw or b"")})

    app = Starlette(routes=[Route("/probe", endpoint, methods=["POST"])])
    app.state.claw_engine_desktop_secret = secret
    return app


def _signed_headers(body: bytes, secret: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    proof = hmac.new(
        secret.encode(), timestamp.encode("ascii") + b"." + body, hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Claw-Engine-Time": timestamp,
        "X-Claw-Engine-Proof": proof,
    }


def test_a_valid_signed_request_is_not_the_unconfigured_refusal():
    with TestClient(_proof_app(SECRET)) as client:
        response = client.post(
            "/probe", content=BODY, headers=_signed_headers(BODY, SECRET)
        )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "bytes": len(BODY)}


@pytest.mark.parametrize("secret", [None, "", "s" * 31])
def test_the_signing_gate_refuses_before_the_body_when_unconfigured(secret):
    with TestClient(_proof_app(secret)) as client:
        response = client.post(
            "/probe", content=BODY, headers=_signed_headers(BODY, SECRET)
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "claw_engine_desktop_unconfigured"


def test_a_tampered_proof_is_refused_when_configured():
    headers = _signed_headers(BODY, SECRET)
    headers["X-Claw-Engine-Proof"] = "0" * 64
    with TestClient(_proof_app(SECRET)) as client:
        response = client.post("/probe", content=BODY, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "claw_engine_proof_required"
