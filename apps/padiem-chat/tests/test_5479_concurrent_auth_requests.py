"""#5479 - the auth lanes and the ordinary lanes under concurrent requests.

The Chat Python Worker serves the auth lanes (sign-in, session read, password
change, administrator authority) and the ordinary lanes (chat, projects) from
one isolate. The reported production failure was a runtime race that makes the
Worker fail to answer at all (``NoGilError``, ``cloudflare/workerd#6624``), so
these tests do not try to reproduce the platform race inside the process. They
pin the two things this repository actually owns:

1. **the PyProxy boundary.** The Worker creates exactly one JS proxy, per
   request, and resets the scheduler that owns it in a ``finally`` block, so no
   proxy and no request-scoped context outlives the request. The GIL error is
   therefore raised by the runtime's own instance bootstrap, never by a proxy
   this application kept alive.

2. **the request lanes.** A burst of concurrent auth and ordinary requests
   answers every request with that request's own identity and never leaks one
   request's session, credential or authority into another.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import types
from types import SimpleNamespace

import httpx

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.history import D1HistoryStore
from app.main import create_app
from app.password_auth import verify_password
from app.platform_admin_roles import D1PlatformAdminRoleStore
from test_5434_password_change import (
    CURRENT_PASSWORD,
    NEW_PASSWORD,
    CanonicalAuthority,
    seed_db,
)
from test_claw_automation_async_composition_seam import _load_worker

BASE = "https://chat.example.test"
SESSION_SECRET = "5479-concurrent-auth-test-session-secret-not-real-000"
OTHER_EMAIL = "other@example.test"
OTHER_PASSWORD = "other account secret"
WORKER = Path(__file__).resolve().parents[1] / "worker.py"


def build_app(db):
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE,
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )
    authority = CanonicalAuthority()
    app = create_app(
        settings=settings,
        history_store=D1HistoryStore(db),
        control_plane_identity_authority=authority,
        platform_admin_role_store=D1PlatformAdminRoleStore(db),
    )
    return app, settings, authority


def _cookie(token: str) -> dict:
    return {"Cookie": f"{SESSION_COOKIE}={token}"}


async def _concurrently(app, specs):
    """Run every (method, path, options) request at the same time."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE
    ) as client:

        async def run(spec):
            method, path, options = spec
            return await client.request(method, path, **options)

        return await asyncio.gather(*(run(spec) for spec in specs))


def _stored_hash(db, user_id) -> str:
    row = db.conn.execute(
        "SELECT password_hash FROM password_credentials WHERE user_id=?", (user_id,)
    ).fetchone()
    return str(row["password_hash"])


def test_the_worker_keeps_no_js_proxy_alive_across_a_request():
    """The application holds no PyProxy between requests.

    One proxy is created, inside the request handler, for the log-export
    awaitable only, and the scheduler that owns it is reset in a ``finally``.
    #6225 adds the release half: the handle the runtime receives is destroyed
    once that awaitable has settled, so a settled proxy cannot outlive the
    request that created it. Nothing survives the request that could be
    touched by a later request in the same isolate, which is what the runtime
    race needs to be a runtime problem rather than an application one.
    """
    worker = WORKER.read_text(encoding="utf-8")
    # The import and the single call, and nothing else.
    assert worker.count("create_proxy") == 2
    # #6225: inside the scheduler, the awaitable settles first and the JS
    # handle is destroyed second — the release cannot precede the export.
    awaitable_await = worker.index("await awaitable")
    release = worker.index("proxy.destroy()")
    call_site = worker.index("self.ctx.waitUntil(proxy)")
    install = worker.index("export_context = install_export_scheduler(")
    fetch = worker.index("response = await asgi.fetch(")
    reset = worker.index("reset_export_scheduler(export_context)")
    assert awaitable_await < release < call_site < install < fetch < reset
    # The reset runs in a finally block, so it also runs when the request fails.
    assert "finally:" in worker[fetch:reset]
    # The proxy is created per request, never at module scope.
    module_scope = worker.split("class ", 1)[0]
    assert "create_proxy(" not in module_scope


def test_the_scheduled_export_releases_its_proxy_when_it_settles(monkeypatch):
    """The waitUntil handle is destroyed once the export has settled.

    #6225: the scheduler hands the runtime one proxy per request. The runner
    keeps the export body and its ordering exactly as before and adds the
    release the old shape never had — the handle is destroyed after the
    awaitable settles, not at request end and not while it is still running.
    """
    module = _load_worker(monkeypatch)
    events: list[str] = []

    class _Proxy:
        def __init__(self, value):
            self.value = value
            self.destroyed = False

        def destroy(self):
            self.destroyed = True
            events.append("destroy")

        def __await__(self):
            return self.value.__await__()

    pyodide = types.ModuleType("pyodide")
    ffi = types.ModuleType("pyodide.ffi")
    ffi.create_proxy = lambda value: _Proxy(value)
    monkeypatch.setitem(sys.modules, "pyodide", pyodide)
    monkeypatch.setitem(sys.modules, "pyodide.ffi", ffi)

    async def _no_gateway(**kwargs):
        return None

    monkeypatch.setattr(module, "maybe_dispatch_connector_gateway", _no_gateway)

    # The fake app schedules one export the way the telemetry middleware does:
    # it reads the installed scheduler and hands it a background awaitable.
    async def dispatch(app, request, env):
        from app.request_telemetry import _CURRENT_EXPORT_SCHEDULER

        async def _export():
            events.append("export")

        scheduler = _CURRENT_EXPORT_SCHEDULER.get()
        assert scheduler is not None
        scheduler(_export())
        return module.Response("ok")

    asgi = types.ModuleType("asgi")
    asgi.fetch = dispatch
    monkeypatch.setitem(sys.modules, "asgi", asgi)

    async def build(self):
        return SimpleNamespace(state=SimpleNamespace())

    monkeypatch.setattr(module.Default, "_build_worker_app", build)

    waited: list[object] = []
    worker = module.Default(
        SimpleNamespace(),
        SimpleNamespace(waitUntil=waited.append),
    )
    request = SimpleNamespace(url="https://example.invalid/health", js_object=object())
    response = asyncio.run(worker.fetch(request))
    assert response.status == 200

    # Nothing has run and nothing is released yet: waitUntil owns the handle.
    assert len(waited) == 1
    proxy = waited[0]
    assert isinstance(proxy, _Proxy)
    assert proxy.destroyed is False
    assert events == []

    # The runtime awaits the handle in the background; settling it runs the
    # same export body as before and then releases the handle, in that order.
    async def _runtime_settles(value):
        await value

    asyncio.run(_runtime_settles(proxy))
    assert events == ["export", "destroy"]
    assert proxy.destroyed is True


def test_the_auth_status_and_the_ordinary_lanes_survive_a_concurrent_burst():
    """A signed-in status read and an anonymous chat answer each other."""
    db, ids = seed_db()
    app, settings, _ = build_app(db)
    token = create_session_token(settings, ids["member"])

    specs = []
    for index in range(8):
        specs.append(("GET", "/api/auth/status", {"headers": _cookie(token)}))
        specs.append(
            (
                "POST",
                "/api/chat",
                {
                    "json": {
                        "messages": [{"role": "user", "content": f"동시 질문 {index}"}],
                    }
                },
            )
        )

    responses = asyncio.run(_concurrently(app, specs))
    assert len(responses) == 16
    for response in responses:
        assert response.status_code == 200, response.text

    for response in responses:
        if response.request.url.path == "/api/auth/status":
            body = response.json()
            assert body["authenticated"] is True
            assert body["user"]["email"] == ids["member_email"]
        else:
            # The anonymous lane never inherits the member's identity.
            assert "conversation_id" not in response.json()


def test_concurrent_logins_keep_their_own_account():
    """Two sign-ins at the same time never swap identities."""
    db, ids = seed_db()
    app, settings, _ = build_app(db)

    async def inner():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            member, other = await asyncio.gather(
                client.post(
                    "/api/auth/password/login",
                    json={
                        "identifier": ids["member_email"],
                        "password": CURRENT_PASSWORD,
                    },
                ),
                client.post(
                    "/api/auth/password/login",
                    json={"identifier": OTHER_EMAIL, "password": OTHER_PASSWORD},
                ),
            )
            return member, other

    member, other = asyncio.run(inner())
    assert member.status_code == 200, member.text
    assert other.status_code == 200, other.text
    member_token = member.cookies.get(SESSION_COOKIE)
    other_token = other.cookies.get(SESSION_COOKIE)
    assert member_token and other_token and member_token != other_token

    responses = asyncio.run(
        _concurrently(
            app,
            [
                ("GET", "/api/auth/status", {"headers": _cookie(member_token)}),
                ("GET", "/api/auth/status", {"headers": _cookie(other_token)}),
            ],
        )
    )
    member_status, other_status = responses
    assert member_status.status_code == 200
    assert other_status.status_code == 200
    assert member_status.json()["user"]["email"] == ids["member_email"]
    assert other_status.json()["user"]["email"] == OTHER_EMAIL


def test_a_concurrent_password_change_never_exposes_a_partial_credential():
    """The credential moves atomically while the session lane keeps reading."""
    db, ids = seed_db()
    app, settings, authority = build_app(db)
    token = create_session_token(
        settings, ids["member"], canonical_session_id="authsession:b62:5479"
    )
    before = _stored_hash(db, ids["member"])

    specs = [
        (
            "POST",
            "/api/auth/password/change",
            {
                "headers": _cookie(token),
                "json": {
                    "current_password": CURRENT_PASSWORD,
                    "new_password": NEW_PASSWORD,
                },
            },
        )
    ]
    for _ in range(6):
        specs.append(("GET", "/api/auth/status", {"headers": _cookie(token)}))

    responses = asyncio.run(_concurrently(app, specs))
    change = responses[0]
    assert change.status_code == 200, change.text
    assert change.json() == {"ok": True}
    for response in responses[1:]:
        assert response.status_code == 200, response.text
        assert response.json()["ready"] is True

    after = _stored_hash(db, ids["member"])
    assert after != before
    assert verify_password(NEW_PASSWORD, after) is True
    assert verify_password(CURRENT_PASSWORD, after) is False
    # The session that changed the credential is revoked exactly once.
    assert authority.revoked == [("b62", "authsession:b62:5479")]

    old_login = asyncio.run(
        _concurrently(
            app,
            [
                (
                    "POST",
                    "/api/auth/password/login",
                    {
                        "json": {
                            "identifier": ids["member_email"],
                            "password": CURRENT_PASSWORD,
                        }
                    },
                )
            ],
        )
    )[0]
    assert old_login.status_code == 401
    new_login = asyncio.run(
        _concurrently(
            app,
            [
                (
                    "POST",
                    "/api/auth/password/login",
                    {
                        "json": {
                            "identifier": ids["member_email"],
                            "password": NEW_PASSWORD,
                        }
                    },
                )
            ],
        )
    )[0]
    assert new_login.status_code == 200
    assert new_login.json()["user"]["email"] == ids["member_email"]


def test_the_admin_permission_query_under_concurrency_never_widens_authority():
    """The administrator lane answers with the caller's own authority only."""
    db, ids = seed_db()
    app, settings, _ = build_app(db)
    admin_token = create_session_token(settings, ids["member"])
    plain_token = create_session_token(settings, ids["other"])

    specs = []
    for _ in range(4):
        specs.append(("GET", "/api/admin/session", {"headers": _cookie(admin_token)}))
        specs.append(("GET", "/api/admin/session", {"headers": _cookie(plain_token)}))
        specs.append(("GET", "/api/admin/session", {}))

    responses = asyncio.run(_concurrently(app, specs))
    assert len(responses) == 12
    for response in responses:
        request_token = response.request.headers.get("Cookie", "")
        body = response.json()
        assert response.status_code == 200, response.text
        if admin_token in request_token:
            assert body["authenticated"] is True
            assert body["role"] == "ADMIN"
            assert body["capabilities"]["admin_hub"] is True
            # ADMIN is not the super administrator, so role management stays shut.
            assert body["capabilities"]["role_management"] is False
        elif plain_token in request_token:
            assert body["authenticated"] is True
            assert body["role"] is None
            assert body["capabilities"]["admin_hub"] is False
        else:
            # An anonymous caller is refused an authority, and stays refused.
            assert body["authenticated"] is False
            assert body["role"] is None
            assert body["capabilities"]["admin_hub"] is False
