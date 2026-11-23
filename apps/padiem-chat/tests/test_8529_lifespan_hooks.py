"""#8529: startup and shutdown handlers keep their contract on Starlette 1.x.

Starlette 1.0 removed ``Router.on_startup`` / ``Router.on_shutdown`` and the
default lifespan that ran them. ``app.lifespan_hooks.LifespanHooks`` replaces
them. These tests drive the real ASGI lifespan (``TestClient`` as a context
manager) and pin what the host relies on: registration order, the
``insert(0, ...)`` precedence the timers use, what happens when a handler
raises, and that an unhandled route error still crosses the middleware stack
as the same plain 500.
"""
from __future__ import annotations

import asyncio

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.config import Settings
from app.lifespan_hooks import LifespanHooks, lifespan_hooks


class _AuthReadyStore:
    async def get_user(self, user_id):
        return None

    async def list_projects(self, user_id):
        return []


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="x.apps.googleusercontent.com",
        google_client_secret="y",
        session_secret="s" * 32,
    )


def _chat_app():
    return create_app(settings=_settings(), history_store=_AuthReadyStore())


def _recorder(calls: list[str], name: str, *, is_async: bool):
    if is_async:
        async def handler():
            calls.append(name)
    else:
        def handler():
            calls.append(name)
    return handler


def test_handlers_run_in_list_order_around_the_serving_phase() -> None:
    calls: list[str] = []
    app = Starlette(lifespan=LifespanHooks())
    hooks = lifespan_hooks(app)
    hooks.on_startup.append(_recorder(calls, "start-1", is_async=True))
    hooks.on_startup.append(_recorder(calls, "start-2", is_async=False))
    hooks.on_shutdown.append(_recorder(calls, "stop-db", is_async=True))
    hooks.on_shutdown.append(_recorder(calls, "stop-client", is_async=False))
    # The timers stop before the database closes: they register at the front.
    hooks.on_shutdown.insert(0, _recorder(calls, "stop-timer", is_async=True))

    with TestClient(app):
        assert calls == ["start-1", "start-2"]
        calls.append("serving")

    assert calls == ["start-1", "start-2", "serving", "stop-timer", "stop-db", "stop-client"]


def test_one_app_can_be_started_and_stopped_more_than_once() -> None:
    calls: list[str] = []
    app = Starlette(lifespan=LifespanHooks())
    hooks = lifespan_hooks(app)
    hooks.on_startup.append(_recorder(calls, "start", is_async=True))
    hooks.on_shutdown.append(_recorder(calls, "stop", is_async=True))

    for _ in range(2):
        with TestClient(app):
            pass

    assert calls == ["start", "stop", "start", "stop"]


def test_a_failing_startup_skips_the_rest_and_runs_no_shutdown() -> None:
    calls: list[str] = []

    async def broken():
        calls.append("start-broken")
        raise RuntimeError("startup failed")

    app = Starlette(lifespan=LifespanHooks())
    hooks = lifespan_hooks(app)
    hooks.on_startup.append(_recorder(calls, "start-1", is_async=True))
    hooks.on_startup.append(broken)
    hooks.on_startup.append(_recorder(calls, "start-3", is_async=True))
    hooks.on_shutdown.append(_recorder(calls, "stop", is_async=True))

    with pytest.raises(RuntimeError, match="startup failed"):
        with TestClient(app):
            calls.append("serving")

    assert calls == ["start-1", "start-broken"]


def test_a_failing_shutdown_skips_the_later_shutdown_handlers() -> None:
    calls: list[str] = []

    async def broken():
        calls.append("stop-broken")
        raise RuntimeError("shutdown failed")

    app = Starlette(lifespan=LifespanHooks())
    hooks = lifespan_hooks(app)
    hooks.on_shutdown.append(_recorder(calls, "stop-1", is_async=True))
    hooks.on_shutdown.append(broken)
    hooks.on_shutdown.append(_recorder(calls, "stop-3", is_async=True))

    with pytest.raises(RuntimeError, match="shutdown failed"):
        with TestClient(app):
            pass

    assert calls == ["stop-1", "stop-broken"]


def test_shutdown_still_runs_when_serving_ends_with_an_error() -> None:
    calls: list[str] = []
    hooks = LifespanHooks()
    hooks.on_startup.append(_recorder(calls, "start", is_async=True))
    hooks.on_shutdown.append(_recorder(calls, "stop", is_async=True))

    async def scenario():
        async with hooks(object()):
            raise KeyError("serving failed")

    with pytest.raises(KeyError):
        asyncio.run(scenario())

    assert calls == ["start", "stop"]


def test_the_chat_app_runs_the_hooks_it_exposes() -> None:
    """A handler registered through ``lifespan_hooks(app)`` is run by the app's
    own lifespan: the lists and the lifespan are one object, never two."""
    calls: list[str] = []
    app = _chat_app()
    hooks = lifespan_hooks(app)
    hooks.on_startup.append(_recorder(calls, "start", is_async=True))
    hooks.on_shutdown.insert(0, _recorder(calls, "stop", is_async=True))

    with TestClient(app) as client:
        assert calls == ["start"]
        assert client.get("/health").status_code == 200

    assert calls == ["start", "stop"]


def test_an_app_without_hooks_is_refused_instead_of_dropping_handlers() -> None:
    with pytest.raises(RuntimeError, match="LifespanHooks"):
        lifespan_hooks(Starlette())


def test_an_unhandled_route_error_crosses_the_stack_as_the_same_500() -> None:
    async def boom(request):
        raise ValueError("unhandled")

    async def fine(request):
        return JSONResponse({"ok": True})

    app = _chat_app()
    app.router.routes.insert(0, Route("/__8529_boom", boom, methods=["GET"]))
    app.router.routes.insert(0, Route("/__8529_fine", fine, methods=["GET"]))

    client = TestClient(app, raise_server_exceptions=False)
    failed = client.get("/__8529_boom")
    assert failed.status_code == 500
    assert failed.text == "Internal Server Error"
    assert failed.headers["content-type"] == "text/plain; charset=utf-8"
    # The stack is still usable for the next request.
    assert client.get("/__8529_fine").json() == {"ok": True}

    # Without the catch-all, the original exception reaches the server as is:
    # no middleware layer wraps or replaces it.
    with pytest.raises(ValueError, match="unhandled"):
        TestClient(app).get("/__8529_boom")
