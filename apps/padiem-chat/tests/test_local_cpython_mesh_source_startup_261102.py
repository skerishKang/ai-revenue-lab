"""#6697 — the CPython host composes the Mesh source inside app startup.

Uvicorn loads ``build_app`` inside its running event loop. The earlier host
wiring called ``asyncio.run(build_oracle_mesh_return_source_from_env(...))``
from the factory, so the host exited with "asyncio.run() cannot be called
from a running event loop". These tests build the real factory inside a
running loop and run the lifespan startup it registers.
"""
from __future__ import annotations

import asyncio

from app import local_cpython

MESH_ENV = {
    "ORACLE_MESH_EXECUTION_MODE": "off",
    "ORACLE_MESH_CHANNEL_SECRET": "s" * 32,
    "ORACLE_MESH_LEGACY_MAP_LANE": "off",
}


def _dev_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PADIEM_LOCAL_DEV", "1")
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "mock")
    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "password")
    monkeypatch.setenv("PADIEM_CHAT_COOKIE_SECURE", "false")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")
    monkeypatch.setenv("PADIEM_CHAT_LIVE_ENABLED", "false")
    monkeypatch.setenv("PADIEM_CHAT_PUBLIC_BASE_URL", "http://127.0.0.1:8796")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("PADIEM_CHAT_CPYTHON_HOST", raising=False)
    monkeypatch.delenv("PADIEM_CHAT_SHARED_LOGIN_ENABLED", raising=False)
    for name in (
        "ORACLE_MESH_EXECUTION_MODE",
        "ORACLE_MESH_CHANNEL_SECRET",
        "ORACLE_MESH_LEGACY_MAP_LANE",
        "ORACLE_MESH_OWNERSHIP_MAP",
        "CONNECTOR_WATCH_READ_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)


def _startup_configured():
    async def scenario():
        app = local_cpython.build_app()
        await app.router.startup()
        try:
            return bool(getattr(app.state.oracle_mesh_return_source, "configured", False))
        finally:
            await app.router.shutdown()

    return asyncio.run(scenario())


def test_factory_builds_inside_a_running_loop_and_startup_composes_the_source(
    monkeypatch, tmp_path, capsys
):
    _dev_env(monkeypatch, tmp_path)
    for name, value in MESH_ENV.items():
        monkeypatch.setenv(name, value)

    assert _startup_configured() is True

    out = capsys.readouterr().out
    assert "[local] oracle_mesh_return_source=mesh_env_configured" in out
    assert "[local] oracle_mesh_source_unconfigured=" not in out


def test_startup_without_mesh_env_stays_unconfigured_with_one_line(
    monkeypatch, tmp_path, capsys
):
    _dev_env(monkeypatch, tmp_path)

    assert _startup_configured() is False

    out = capsys.readouterr().out
    assert "[local] oracle_mesh_source_unconfigured=env_binding_unavailable" in out
    assert "[local] oracle_mesh_return_source=mesh_env_configured" not in out
