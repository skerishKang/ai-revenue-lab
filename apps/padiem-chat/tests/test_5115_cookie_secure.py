"""#5115 — the session cookie's Secure flag is deployment-owned.

The Cloudflare deployment keeps ``Secure`` behind its TLS edge. The COM2
native CPython runtime serves plain loopback HTTP, where a Secure cookie is
never sent back by any conforming client — every authenticated request after
login would 401. ``Settings.cookie_secure`` (env
``PADIEM_CHAT_COOKIE_SECURE``) lets the loopback deployment set False without
touching the Cloudflare contract, whose default stays True.
"""
from __future__ import annotations

from pathlib import Path
import importlib.util

CHAT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]

SESSION_SECRET = "cookie-secure-session-secret-not-a-real-key-000"


def _settings(**overrides):
    from app.config import Settings

    values = dict(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url="https://chat.example.test",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )
    values.update(overrides)
    return Settings.from_values(**values)


def test_cookie_secure_defaults_to_true() -> None:
    assert _settings().cookie_secure is True
    assert _settings(cookie_secure="true").cookie_secure is True


def test_cookie_secure_accepts_false_spellings() -> None:
    for raw in ("false", "0", "no", "off", "False", "OFF"):
        assert _settings(cookie_secure=raw).cookie_secure is False, raw
    assert _settings(cookie_secure=False).cookie_secure is False


def test_cookie_secure_rejects_unknown_values() -> None:
    from app.config import ConfigError

    for raw in ("maybe", "2", "secure"):
        try:
            _settings(cookie_secure=raw)
        except ConfigError:
            continue
        raise AssertionError(f"invalid cookie_secure value accepted: {raw!r}")


def test_from_env_reads_the_deployment_flag(monkeypatch) -> None:
    from app.config import Settings

    monkeypatch.setenv("PADIEM_CHAT_COOKIE_SECURE", "false")
    assert Settings.from_env().cookie_secure is False
    monkeypatch.setenv("PADIEM_CHAT_COOKIE_SECURE", "true")
    assert Settings.from_env().cookie_secure is True
    monkeypatch.delenv("PADIEM_CHAT_COOKIE_SECURE")
    assert Settings.from_env().cookie_secure is True


def test_session_cookie_kwargs_follow_the_setting() -> None:
    from app.auth import session_cookie_kwargs

    assert session_cookie_kwargs(_settings())["secure"] is True
    loopback = session_cookie_kwargs(_settings(cookie_secure=False))
    assert loopback["secure"] is False
    assert loopback["httponly"] is True


def _loopback_app(cookie_secure: bool):
    from app.main import create_app
    from app.config import Settings
    from tests.test_password_auth import MemoryStore

    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url="https://chat.padiem.net",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
        cookie_secure=cookie_secure,
    )
    store = MemoryStore()
    return create_app(settings, history_store=store)


def test_loopback_http_runtime_holds_a_session_when_cookie_secure_is_false() -> None:
    """REAL local proof over plain HTTP: with cookie_secure=False the session
    cookie is sent back and /api/auth/status reports authenticated; with the
    default True the same http client loses the session (the exact COM2
    failure this setting fixes)."""
    import httpx

    email = "com2-cookie-probe@example.test"
    password = "Loopback-Cookie-2026-10-25!"

    async def journey(cookie_secure: bool, expect_auth: bool):
        app = _loopback_app(cookie_secure=cookie_secure)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:18764",
            timeout=60,
        ) as client:
            r = await client.post("/api/auth/password/register", json={
                "email": email, "password": password, "name": "loopback probe",
            })
            assert r.status_code == 200, (cookie_secure, r.text)
            r = await client.post("/api/auth/password/login", json={
                "identifier": email, "password": password,
            })
            assert r.status_code == 200, (cookie_secure, r.text)
            r = await client.get("/api/auth/status")
            return r.json().get("authenticated"), cookie_secure

    import asyncio

    for cookie_secure, expect_auth in ((False, True), (True, False)):
        authenticated, flag = asyncio.run(journey(cookie_secure, expect_auth))
        assert authenticated is expect_auth, (flag, authenticated)


def test_loopback_register_works_on_the_native_runtime_path() -> None:
    """The register route on main is email-only (#5424): no username field."""
    import httpx

    async def register_probe():
        app = _loopback_app(cookie_secure=False)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:18764",
            timeout=60,
        ) as client:
            return await client.post("/api/auth/password/register", json={
                "email": "no-username-field@example.test",
                "password": "Loopback-Cookie-2026-10-25!",
                "name": "no username field needed",
            })

    import asyncio

    r = asyncio.run(register_probe())
    assert r.status_code == 200, r.text
