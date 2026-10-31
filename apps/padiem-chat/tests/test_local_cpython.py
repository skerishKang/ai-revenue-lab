"""#5573 stage 2 — the local CPython run's contract, in force from CI.

Two halves:

* The `PADIEM_LOCAL_DEV` allowance is loopback-only and opt-in. Without the
  flag the https-only validation and the same-origin expectation are byte-for-byte
  the production rules; with it only 127.0.0.1/localhost/::1 over http pass,
  and a non-loopback http base is still refused.
* `build_app()` runs the real create_app over SQLite + disk R2 and the whole
  signed-in lane works: register → conversation list → one mock chat turn that
  persists. That is the exact goal of the stage, asserted end-to-end, not
  described in a doc.
"""
from __future__ import annotations

import json
import os
import sqlite3

import pytest
from starlette.testclient import TestClient

from app.config import ConfigError, Settings
from app.local_cpython import _ensure_session_secret, apply_migrations, build_app
from app.local_r2 import LocalDiskR2
from app.local_service_bridge import HttpRpcBinding, LocalB66PdfRendererClient
from app.queue_store_proxy import (
    QueueBackedPairingStore,
    QueueBackedPresenceStore,
    QueueForwardingHistoryStore,
)
from app.same_origin_guard import expected_browser_origin
from app.web_tools import create_web_provider
from app.workspace_storage import _read_r2_object_bytes


def _settings(**overrides) -> Settings:
    base = dict(runtime_mode="mock", auth_mode="off", web_provider="off")
    base.update(overrides)
    return Settings.from_values(**base)


def test_public_base_url_https_only_without_the_local_flag():
    # The production rule, restated: http is refused when the flag is absent.
    with pytest.raises(ConfigError):
        _settings(public_base_url="http://127.0.0.1:8773")
    with pytest.raises(ConfigError):
        _settings(local_dev="0", public_base_url="http://127.0.0.1:8773")


def test_local_flag_admits_loopback_http_only():
    settings = _settings(local_dev="1", public_base_url="http://127.0.0.1:8773",
                         auth_mode="password", session_secret="x" * 40,
                         cookie_secure=False)
    assert settings.local_dev is True
    assert settings.public_base_url == "http://127.0.0.1:8773"
    for host in ("localhost", "[::1]"):
        assert _settings(local_dev="1", public_base_url=f"http://{host}:8773",
                         auth_mode="off").public_base_url.startswith("http://")
    # A flag is not a blanket: a routable http base stays refused, and a typo
    # in the flag value raises instead of silently disabling the run.
    with pytest.raises(ConfigError):
        _settings(local_dev="1", public_base_url="http://example.com")
    with pytest.raises(ConfigError):
        _settings(local_dev="ture")


def test_expected_browser_origin_follows_the_same_narrow_rule():
    https = _settings(public_base_url="https://chat.example.com")
    assert expected_browser_origin(https) == "https://chat.example.com"

    loopback = _settings(local_dev="1", public_base_url="http://127.0.0.1:8773")
    assert expected_browser_origin(loopback) == "http://127.0.0.1:8773"

    # No flag, or flag with a non-loopback host: the guard keeps failing closed.
    # These two are built through the bare dataclass — a no-flag http base is
    # not something from_values would ever let exist (its own test above
    # asserts that), so the guard must deny it directly.
    assert expected_browser_origin(
        Settings(runtime_mode="mock", public_base_url="http://127.0.0.1:8773")
    ) is None
    assert expected_browser_origin(
        Settings(runtime_mode="mock", public_base_url="http://example.com", local_dev=True)
    ) is None
    # The flag is not a blanket even on the guard side: an https base with the
    # flag set behaves exactly as before.
    assert expected_browser_origin(
        Settings(runtime_mode="mock", public_base_url="https://chat.example.com", local_dev=True)
    ) == "https://chat.example.com"


def test_local_r2_roundtrip_and_key_fences(tmp_path):
    bucket = LocalDiskR2(tmp_path / "objects")
    bucket.put("claw-model-context/v1/chat_abc/msg_deadbeef.utf8", "전문".encode("utf-8"),
               httpMetadata={"contentType": "text/plain; charset=utf-8"})
    obj = bucket.get("claw-model-context/v1/chat_abc/msg_deadbeef.utf8")
    assert obj is not None and obj.size == len("전문".encode("utf-8"))

    # The exact reader the stores use (`_read_r2_object_bytes`) gets the bytes.
    import asyncio
    assert asyncio.run(_read_r2_object_bytes(obj)).decode("utf-8") == "전문"

    assert bucket.get("claw-model-context/v1/other/missing.utf8") is None
    bucket.delete("claw-model-context/v1/chat_abc/msg_deadbeef.utf8")
    assert bucket.get("claw-model-context/v1/chat_abc/msg_deadbeef.utf8") is None

    for hostile in ("../outside", "a/../../b", "/absolute", "C:/windows", "a//b", "..", ""):
        with pytest.raises(ValueError):
            bucket.get(hostile)


def test_apply_migrations_is_idempotent_over_the_real_files(tmp_path):
    connection = sqlite3.connect(str(tmp_path / "m.sqlite3"), isolation_level=None)
    try:
        first = apply_migrations(connection)
        assert first > 70
        assert apply_migrations(connection) == 0
        ledger = connection.execute(
            "SELECT COUNT(*) FROM padiem_local_migration_ledger").fetchone()[0]
        assert ledger == first
    finally:
        connection.close()


@pytest.fixture()
def local_client(tmp_path, monkeypatch):
    monkeypatch.setenv("PADIEM_LOCAL_DEV", "1")
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "mock")
    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "password")
    monkeypatch.setenv("PADIEM_CHAT_COOKIE_SECURE", "false")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")
    monkeypatch.setenv("PADIEM_CHAT_LIVE_ENABLED", "false")
    monkeypatch.setenv("PADIEM_CHAT_PUBLIC_BASE_URL", "http://127.0.0.1:8773")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    # The dev key is pinned here so build_app never writes the process
    # environment from inside a test — `_ensure_session_secret`'s own behavior
    # is covered separately below.
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", "test-local-secret-0123456789abcdef")

    app = build_app()
    with TestClient(app, headers={"Origin": "http://127.0.0.1:8773"}) as client:
        yield client


def test_web_search_is_not_runtime_blocked_on_cpython_only_key_configured():
    # The provider is the same core client the Worker builds; on CPython the
    # transport argument simply stays None and the core's real httpx is used.
    # So the only gates are the same two: keys in the environment and the
    # b14/live runtime the automatic search already requires.
    settings = Settings.from_values(
        runtime_mode="b14", b14_base_url="https://b14.example", live_enabled=True,
        web_provider="tinyfish_daum", tinyfish_api_key="t" * 40,
        daum_rest_api_key="d" * 40,
    )
    provider = create_web_provider(settings)
    assert type(provider).__name__ == "TinyFishDaumWebProvider"
    assert provider._automatic_search_enabled is True

    off = create_web_provider(Settings.from_values(runtime_mode="mock", web_provider="off"))
    assert off._automatic_search_enabled is False


@pytest.fixture()
def local_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PADIEM_LOCAL_DEV", "1")
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "mock")
    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "off")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")
    monkeypatch.setenv("PADIEM_CHAT_PUBLIC_BASE_URL", "http://127.0.0.1:8773")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", "test-local-secret-0123456789abcdef")
    return tmp_path


@pytest.fixture()
def staging_host_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PADIEM_CHAT_CPYTHON_HOST", "1")
    monkeypatch.setenv("PADIEM_CHAT_PUBLIC_BASE_URL", "https://chat-com2-staging.padiem.net")
    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "off")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "mock")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", "test-local-secret-0123456789abcdef")
    return tmp_path


def test_queue_wiring_stays_off_by_default(local_env, monkeypatch):
    monkeypatch.delenv("PC_QUEUE_BACKEND", raising=False)
    monkeypatch.delenv("PC_QUEUE_SERVICE_SECRET_FILE", raising=False)
    app = build_app()
    assert not isinstance(app.state.history_store, QueueForwardingHistoryStore)
    assert getattr(app.state, "pc_device_pairing_store", None) is None
    assert getattr(app.state, "mesh_device_presence_store", None) is None


def test_staging_queue_wiring_reads_the_secret_from_a_file(staging_host_env, monkeypatch):
    secret_file = staging_host_env / "queue-service-secret.txt"
    secret_file.write_text("queue-service-secret-0123456789", encoding="utf-8")
    monkeypatch.delenv("PC_QUEUE_SERVICE_SECRET", raising=False)
    monkeypatch.setenv("PC_QUEUE_BACKEND", "com2")
    monkeypatch.setenv("PC_QUEUE_ORIGIN", "http://127.0.0.1:8830")
    monkeypatch.setenv("PADIEM_CHAT_QUEUE_ALLOW_LOOPBACK_HTTP", "1")
    monkeypatch.setenv("PC_QUEUE_SERVICE_SECRET_FILE", str(secret_file))

    app = build_app()
    assert isinstance(app.state.history_store, QueueForwardingHistoryStore)
    assert isinstance(app.state.pc_device_pairing_store, QueueBackedPairingStore)
    assert isinstance(app.state.mesh_device_presence_store, QueueBackedPresenceStore)


def test_staging_queue_wiring_fails_closed_without_a_readable_secret(staging_host_env, monkeypatch):
    monkeypatch.delenv("PC_QUEUE_SERVICE_SECRET", raising=False)
    monkeypatch.setenv("PC_QUEUE_BACKEND", "com2")
    monkeypatch.setenv("PC_QUEUE_ORIGIN", "http://127.0.0.1:8830")
    monkeypatch.setenv("PADIEM_CHAT_QUEUE_ALLOW_LOOPBACK_HTTP", "1")
    monkeypatch.setenv("PC_QUEUE_SERVICE_SECRET_FILE", str(staging_host_env / "missing.txt"))

    with pytest.raises(ConfigError):
        build_app()


def test_service_stand_ins_bind_only_when_their_pair_is_configured(local_env, monkeypatch):
    app = build_app()
    assert app.state.control_plane_identity_authority is None
    assert app.state.b66_pdf_renderer_client is None

    monkeypatch.setenv("PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN", "https://identity.example")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET", "local-service-secret-0123456789abcd")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_B66_PDF_ORIGIN", "https://pdf.example")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_B66_PDF_SECRET", "local-service-secret-0123456789abcd")
    app = build_app()
    assert isinstance(app.state.control_plane_identity_authority, HttpRpcBinding)
    assert isinstance(app.state.b66_pdf_renderer_client, LocalB66PdfRendererClient)

    # A half-configured pair is a boot error, never a silent downgrade.
    monkeypatch.delenv("PADIEM_CHAT_LOCAL_B66_PDF_SECRET")
    with pytest.raises(ConfigError):
        build_app()


def test_host_mode_requires_https_and_never_mixes_with_the_local_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("PADIEM_CHAT_CPYTHON_HOST", "1")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", "test-local-secret-0123456789abcdef")
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "mock")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")

    # No https public base yet: a host run may not fall back to loopback rules.
    with pytest.raises(ConfigError):
        build_app()

    monkeypatch.setenv("PADIEM_CHAT_PUBLIC_BASE_URL", "https://chat-com2.padiem.net")
    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "off")
    build_app()

    # Host mode and the local loopback allowance are mutually exclusive.
    monkeypatch.setenv("PADIEM_LOCAL_DEV", "1")
    with pytest.raises(ConfigError):
        build_app()


def test_ensure_session_secret_generates_once_and_keeps_cookies_across_restart(tmp_path, monkeypatch):
    # Exactly one tracked setenv, before any direct mutation: the function
    # writes os.environ itself, and monkeypatch can only undo to the value it
    # recorded — which here is "not set", so the process ends as it started.
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", "")
    _ensure_session_secret(tmp_path)
    first = os.environ["PADIEM_CHAT_SESSION_SECRET"]
    assert len(first) >= 32
    assert (tmp_path / "session_secret").read_text(encoding="utf-8").strip() == first

    # A "restart" reads the persisted key back, so last run's cookie still
    # verifies — this is the whole reason the file exists.
    os.environ["PADIEM_CHAT_SESSION_SECRET"] = ""
    _ensure_session_secret(tmp_path)
    assert os.environ["PADIEM_CHAT_SESSION_SECRET"] == first

    # An explicit, already-valid key is never overwritten by the generator.
    os.environ["PADIEM_CHAT_SESSION_SECRET"] = "operator-supplied-secret-0123456789"
    _ensure_session_secret(tmp_path)
    assert os.environ["PADIEM_CHAT_SESSION_SECRET"] == "operator-supplied-secret-0123456789"


def test_local_boot_signed_in_chat_lane_end_to_end(local_client):
    health = local_client.get("/health")
    assert health.status_code == 200

    status = local_client.get("/api/auth/status")
    assert status.status_code == 200

    register = local_client.post(
        "/api/auth/password/register",
        json={"email": "astra3@example.com", "password": "astralane-pass-2026"},
    )
    assert register.status_code == 200, register.text

    listed = local_client.get("/api/conversations")
    assert listed.status_code == 200, listed.text
    assert listed.json()["conversations"] == []

    stream = local_client.post(
        "/api/chat/stream",
        json={"messages": [{"role": "user", "content": "로컬 CPython 기동 확인"}]},
    )
    assert stream.status_code == 200, stream.text
    assert stream.headers["content-type"].startswith("text/event-stream")
    done = json.loads(stream.text.rstrip().rsplit("data: ", 1)[1])
    conversation_id = done["conversation_id"]
    assert conversation_id.startswith("chat_")

    listed = local_client.get("/api/conversations")
    assert any(row["id"] == conversation_id for row in listed.json()["conversations"])
    detail = local_client.get(f"/api/conversations/{conversation_id}")
    assert detail.status_code == 200
    contents = [row["content"] for row in detail.json()["conversation"]["messages"]]
    assert any("로컬 CPython 기동 확인" in text for text in contents)
