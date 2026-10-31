"""The cutover write window: default off, mutations frozen, reads served (#5115).

The switch is the stage-3 maintenance window (#5573) grown by one dimension:
the same 503 answer, plus a configurable list of read-method routes that still
write. These tests never touch D1 — the middleware is exercised over a tiny
Starlette app, plus one composition check through the host app builder.
"""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.maintenance_mode import (
    MAINTENANCE_CODE,
    MaintenanceModeMiddleware,
    apply_write_freeze,
    frozen_paths_from_env,
    write_freeze_from_env,
)


async def _ok(request):
    return JSONResponse({"ok": True, "path": request.url.path})


def _app() -> Starlette:
    return Starlette(
        routes=[
            Route("/health", _ok),
            Route("/api/chat/stream", _ok, methods=["POST"]),
            Route("/api/love/start", _ok),
            Route("/api/auth/github/callback", _ok),
            Route("/api/files/capabilities", _ok),
        ]
    )


def _client(env: dict[str, str], **kwargs) -> TestClient:
    return TestClient(apply_write_freeze(_app(), env), **kwargs)


def test_no_configuration_keeps_todays_behavior() -> None:
    app = _app()
    assert apply_write_freeze(app, {}) is app
    assert write_freeze_from_env({}) is None

    with TestClient(app) as client:
        assert client.post("/api/chat/stream").status_code == 200


@pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off", ""])
def test_explicit_falsy_values_keep_the_window_closed(value: str) -> None:
    assert write_freeze_from_env({"PADIEM_CHAT_WRITE_FREEZE": value}) is None


def test_environment_switch_freezes_mutations_and_serves_reads() -> None:
    with _client({"PADIEM_CHAT_WRITE_FREEZE": "1"}) as client:
        refused = client.post("/api/chat/stream")
        assert refused.status_code == 503
        assert refused.json()["error"]["code"] == MAINTENANCE_CODE
        assert "점검" in refused.json()["error"]["message"]
        assert refused.headers["retry-after"] == "120"

        health = client.get("/health")
        assert health.status_code == 200 and health.json()["ok"] is True
        assert client.get("/api/files/capabilities").status_code == 200


def test_every_mutating_method_is_frozen() -> None:
    app = Starlette(
        routes=[
            Route("/r", _ok, methods=["POST", "PUT", "PATCH", "DELETE"]),
        ]
    )
    with TestClient(apply_write_freeze(app, {"PADIEM_CHAT_WRITE_FREEZE": "on"})) as client:
        for method in ("post", "put", "patch", "delete"):
            assert getattr(client, method)("/r").status_code == 503


def test_a_typo_fails_on_the_safe_side() -> None:
    config = write_freeze_from_env({"PADIEM_CHAT_WRITE_FREEZE": "ture"})
    assert config is not None and config.enabled is True


def test_late_write_gets_are_frozen_by_configured_path() -> None:
    env = {
        "PADIEM_CHAT_WRITE_FREEZE": "1",
        "PADIEM_CHAT_WRITE_FREEZE_PATHS": "/api/love/start, /api/auth/github/callback",
    }
    with _client(env) as client:
        assert client.get("/api/love/start").status_code == 503
        assert client.get("/api/auth/github/callback").status_code == 503
        # An unlisted read route keeps working.
        assert client.get("/api/files/capabilities").status_code == 200
        assert client.get("/health").status_code == 200


def test_frozen_paths_support_a_prefix_pattern() -> None:
    env = {
        "PADIEM_CHAT_WRITE_FREEZE": "1",
        "PADIEM_CHAT_WRITE_FREEZE_PATHS": "/api/auth/*",
    }
    with _client(env) as client:
        assert client.get("/api/auth/github/callback").status_code == 503
        assert client.get("/health").status_code == 200


def test_a_bare_star_is_refused_so_reads_never_all_freeze() -> None:
    assert frozen_paths_from_env("*") == ()
    env = {"PADIEM_CHAT_WRITE_FREEZE": "1", "PADIEM_CHAT_WRITE_FREEZE_PATHS": "*"}
    with _client(env) as client:
        assert client.get("/health").status_code == 200


def test_paths_are_normalized_and_deduplicated() -> None:
    assert frozen_paths_from_env("api/love/start, /api/love/start  /x*") == (
        "/api/love/start",
        "/x*",
    )


def test_sentinel_file_opens_and_closes_the_window_without_a_restart(tmp_path) -> None:
    sentinel = tmp_path / "WRITE_FREEZE"
    env = {"PADIEM_CHAT_MAINTENANCE_SENTINEL": str(sentinel)}

    with _client(env) as client:
        assert client.post("/api/chat/stream").status_code == 200
        sentinel.write_text("freeze\n", encoding="utf-8")
        assert client.post("/api/chat/stream").status_code == 503
        assert client.get("/health").status_code == 200
        sentinel.unlink()
        assert client.post("/api/chat/stream").status_code == 200


def test_an_unreadable_sentinel_counts_as_frozen(tmp_path, monkeypatch) -> None:
    middleware = MaintenanceModeMiddleware(_app(), sentinel_path=tmp_path / "SENTINEL")

    def unreadable(_self) -> bool:
        raise OSError("permission denied")

    monkeypatch.setattr(type(tmp_path), "is_file", unreadable)
    assert middleware._active() is True


def test_the_switch_alone_is_enough_to_compose(tmp_path, monkeypatch) -> None:
    """The Cloudflare entry has no filesystem: the env switch must work alone."""

    monkeypatch.setenv("PADIEM_LOCAL_DEV", "1")
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "mock")
    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "off")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")
    monkeypatch.setenv("PADIEM_CHAT_PUBLIC_BASE_URL", "http://127.0.0.1:8773")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", "test-local-secret-0123456789abcdef")
    monkeypatch.delenv("PADIEM_CHAT_MAINTENANCE_SENTINEL", raising=False)
    monkeypatch.setenv("PADIEM_CHAT_WRITE_FREEZE", "1")

    from app.local_cpython import build_app

    app = build_app()
    with TestClient(app, headers={"Origin": "http://127.0.0.1:8773"}) as client:
        refused = client.post("/api/chat/stream", json={"messages": []})
        assert refused.status_code == 503
        assert refused.json()["error"]["code"] == MAINTENANCE_CODE
        assert client.get("/health").status_code == 200
