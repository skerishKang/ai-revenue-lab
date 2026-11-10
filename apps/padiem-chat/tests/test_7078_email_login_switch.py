"""#7078 step 3 — the email-login switch is default OFF and moves the flow.

When ON, Chat's own email credential endpoints stop accepting credentials and
answer with a bounded redirect to the common login screen; padiem-auth then
owns the email flow and calls Chat's internal verification RPC. The default is
OFF, so no deployment changes behavior until it opts in.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.config import ConfigError, Settings
from app.main import create_app

BASE = "https://chat.example.test"


class BombStore:
    """History store whose credential surface must not be reached when ON."""

    def __init__(self):
        self.calls: list[str] = []

    def __getattr__(self, name):
        if name.startswith("_") or name == "calls":
            raise AttributeError(name)

        def _recorded(*args, **kwargs):
            self.calls.append(name)
            raise RuntimeError("credential store must not be reached")

        return _recorded


def _settings(**overrides):
    values = dict(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE,
        session_secret="7078-email-switch-session-secret-not-real",
        password_rpc_secret="7078-email-switch-rpc-secret-not-real-0000",
        session_max_age_seconds=3600,
    )
    values.update(overrides)
    return Settings.from_values(**values)


def _post(path, body, **settings):
    app = create_app(_settings(**settings), history_store=BombStore())
    async def inner():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            return await client.post(path, json=body, headers={"origin": BASE})
    return asyncio.run(inner()), app


def test_the_switch_is_off_by_default_and_parses_strictly(monkeypatch):
    assert _settings().email_login_via_shared is False
    monkeypatch.setenv("PADIEM_CHAT_EMAIL_LOGIN_VIA_SHARED", "true")
    assert Settings.from_env().email_login_via_shared is True
    monkeypatch.setenv("PADIEM_CHAT_EMAIL_LOGIN_VIA_SHARED", "false")
    assert Settings.from_env().email_login_via_shared is False
    monkeypatch.setenv("PADIEM_CHAT_EMAIL_LOGIN_VIA_SHARED", "yes")
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_switch_off_still_uses_the_existing_credential_path():
    response, _ = _post(
        "/api/auth/password/login",
        {"identifier": "owner@example.test", "password": "not-a-real-password"},
    )
    # The off path reaches the credential store; the bomb store fails closed.
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "auth_storage_error"


def test_switch_on_moves_login_before_any_credential_lookup():
    response, app = _post(
        "/api/auth/password/login",
        {"identifier": "owner@example.test", "password": "not-a-real-password"},
        email_login_via_shared=True,
    )
    assert response.status_code == 409
    payload = response.json()
    assert payload["error"]["code"] == "email_login_moved"
    assert payload["login_url"] == "/auth/shared/start"
    assert "owner@example.test" not in response.text
    assert "not-a-real-password" not in response.text


def test_switch_on_moves_registration_too():
    response, app = _post(
        "/api/auth/password/register",
        {"email": "new@example.test", "password": "not-a-real-password", "name": "N"},
        email_login_via_shared=True,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_login_moved"


def test_switch_on_keeps_the_internal_verification_rpc_reachable():
    def _call():
        app = create_app(
            _settings(email_login_via_shared=True), history_store=BombStore()
        )
        async def inner():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE
            ) as client:
                return await client.post(
                    "/internal/password-verify",
                    content=b'{"email":"x@example.test","password":"y"}',
                    headers={
                        "content-type": "application/json",
                        "x-padiem-service-at": "0",
                        "x-padiem-service-id": "00000000-0000-0000-0000-000000000000",
                        "x-padiem-service-proof": "v2=bad",
                    },
                )
        return asyncio.run(inner())

    response = _call()
    # The route exists and rejects the unsigned call; the switch never blocks
    # the padiem-auth verification surface.
    assert response.status_code == 401


def test_the_common_auth_client_config_keeps_email_login_and_the_callback():
    """The padiem-auth side of the migration precondition (no code change).

    b62 must keep `password_login` so the common login screen can take the
    email flow, and the Chat shared callback must stay registered for the
    access token exchange the switch depends on.
    """
    import json
    import re
    from pathlib import Path

    toml = (
        Path(__file__).resolve().parents[2]
        / "padiem-auth"
        / "wrangler.toml"
    ).read_text(encoding="utf-8")
    match = re.search(r"PADIEM_AUTH_CLIENTS = '''(.*?)'''", toml, re.S)
    assert match is not None
    client = json.loads(match.group(1))["b62"]
    assert client["password_login"] is True
    assert "https://chat.padiem.net/auth/shared/callback" in client["redirect_uris"]

