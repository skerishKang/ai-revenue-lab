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
from app.control_plane_identity_shadow import D1IdentityShadowStore
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
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
    from app.pc_device_pairing_store import D1PcPairingStore
    from app.mesh_device_presence_store import D1MeshDevicePresenceStore
    assert isinstance(app.state.pc_device_pairing_store, D1PcPairingStore)
    assert isinstance(app.state.mesh_device_presence_store, D1MeshDevicePresenceStore)


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
    assert isinstance(app.state.control_plane_identity_authority, CloudflareControlPlaneIdentityAuthority)
    assert isinstance(app.state.control_plane_identity_authority._binding, HttpRpcBinding)
    assert isinstance(app.state.identity_shadow_store, D1IdentityShadowStore)
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


@pytest.mark.asyncio
async def test_cpython_shared_login_es256_wire_and_existing_verifier(monkeypatch):
    import base64
    from pathlib import Path
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    from app.cpython_shared_login import NativeES256Signer, NativeTokenVerifier
    from app.shared_auth_compare_flow import ComparisonFlow
    def b64num(value):
        return base64.urlsafe_b64encode(value.to_bytes(32, 'big')).rstrip(b'=').decode()
    # Well-known P-256 generator is a synthetic test key, not an installed credential.
    jwk = {'kty':'EC', 'crv':'P-256', 'd':b64num(1),
           'x':b64num(0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296),
           'y':b64num(0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5)}
    signer = NativeES256Signer()
    flow = ComparisonFlow(state_key=b'x'*32, client_id='b62-staging', client_jwk=jwk, kid='synthetic',
        operator_guard=lambda r:True, legacy_user=lambda r:None, comparator=lambda *a:None,
        exchange=lambda *a:None, crypto=signer, clock=lambda:1000)
    assertion = await flow._assertion(1000)
    head, body, sig = assertion.split('.')
    decode = lambda x: base64.urlsafe_b64decode(x + '=' * (-len(x) % 4))
    assert json.loads(decode(head)) == {'alg':'ES256','kid':'synthetic'}
    assert json.loads(decode(body))['iss'] == 'b62-staging'
    raw = decode(sig)
    assert len(raw) == 64
    with pytest.raises(ValueError):
        await signer.sign({**jwk, 'x': b64num(2)}, b'test')
    public = ec.EllipticCurvePublicNumbers(int.from_bytes(decode(jwk['x']),'big'), int.from_bytes(decode(jwk['y']),'big'), ec.SECP256R1()).public_key()
    public.verify(encode_dss_signature(int.from_bytes(raw[:32],'big'), int.from_bytes(raw[32:],'big')), (head+'.'+body).encode(), ec.ECDSA(hashes.SHA256()))
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'packages/padiem-auth-verify'))
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location('padiem_auth_verify', Path(__file__).resolve().parents[3] / 'packages/padiem-auth-verify/verify.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, 'padiem_auth_verify', module)
    vector = json.loads((Path(__file__).resolve().parents[3] / 'packages/padiem-auth-verify/tests/vectors.json').read_text(encoding='utf-8'))
    verifier = NativeTokenVerifier(vector['audience'])
    verifier._verifier.fetcher = lambda: vector['jwks']
    verifier._verifier.clock = lambda: vector['now']
    assert (await verifier.verify(vector['tokens']['valid']))['accountId'] == 'sub_existing'
    with pytest.raises(Exception):
        await verifier.verify(vector['tokens']['forged'])


def test_shared_login_host_switch_and_real_configuration(staging_host_env, monkeypatch, capsys):
    import base64, sys, importlib.util
    from pathlib import Path
    monkeypatch.delenv('PADIEM_CHAT_SHARED_LOGIN_ENABLED', raising=False)
    app = build_app()
    assert '/auth/shared/start' not in [getattr(r, 'path', None) for r in app.routes]
    monkeypatch.setenv('PADIEM_CHAT_SHARED_LOGIN_ENABLED', 'true')
    monkeypatch.setenv('PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN', 'https://identity.example')
    monkeypatch.setenv('PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET', 'synthetic-identity-secret-0123456789')
    monkeypatch.setenv('PADIEM_CHAT_SHARED_AUTH_CLIENT_ID', 'b62-staging')
    monkeypatch.setenv('PADIEM_CHAT_SHARED_AUTH_CLIENT_KID', 'synthetic')
    key = staging_host_env / 'jwk.json'
    state = staging_host_env / 'state.txt'
    key.write_text(json.dumps({'kty':'EC','crv':'P-256','x':'x','y':'y','d':'d'}), encoding='utf-8')
    state.write_text(base64.urlsafe_b64encode(b'x'*32).rstrip(b'=').decode(), encoding='utf-8')
    monkeypatch.setenv('PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK_FILE', str(key))
    monkeypatch.setenv('PADIEM_CHAT_SHARED_AUTH_COMPARE_STATE_KEY_FILE', str(state))
    spec = importlib.util.spec_from_file_location('padiem_auth_verify', Path(__file__).resolve().parents[3] / 'packages/padiem-auth-verify/verify.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, 'padiem_auth_verify', module)
    app = build_app()
    assert '/auth/shared/start' in [getattr(r, 'path', None) for r in app.routes]
    assert app.state.shared_login_flow.client_id == 'b62-staging'
    with TestClient(app, base_url='https://chat-com2-staging.padiem.net') as client:
        response = client.get('/auth/shared/start', follow_redirects=False)
        assert response.status_code == 302
        from urllib.parse import parse_qs, urlsplit
        query = parse_qs(urlsplit(response.headers['location']).query)
        assert query['client_id'] == ['b62-staging']
        assert query['redirect_uri'] == ['https://chat-com2-staging.padiem.net/auth/shared/callback']
    key.unlink()
    app = build_app()
    assert '/auth/shared/start' not in [getattr(r, 'path', None) for r in app.routes]
    assert 'PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK' in capsys.readouterr().out


def test_worker_dependency_lock_excludes_native_cryptography():
    import tomllib
    from pathlib import Path
    lock = tomllib.loads((Path(__file__).resolve().parents[1] / 'pylock.toml').read_text(encoding='utf-8'))
    assert all(package.get('name') != 'cryptography' for package in lock['packages'])


def test_host_missing_routes_are_owner_scoped_and_use_existing_stores(staging_host_env, monkeypatch):
    import httpx
    from app.auth import SESSION_COOKIE, create_session_token

    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "password")
    monkeypatch.setenv("PADIEM_CHAT_CUSTOM_KEY_SECRET", "synthetic-custom-key-secret-1234567890")
    broker_file = staging_host_env / "broker-test-secret"
    broker_file.write_text("synthetic-broker-secret-0123456789abcdef", encoding="utf-8")
    monkeypatch.setenv("PADIEM_COM2_BROKER_RPC_SECRET_FILE", str(broker_file))
    calls = []

    def broker_reply(request):
        calls.append(request)
        assert "x-padiem-service-id" in request.headers
        assert request.url.path == "/internal/rpc/device_directory"
        return httpx.Response(200, json={"ok": True, "available": False, "reason": "no_device_binding"})

    from app.com2_connector_websocket import LoopbackRpcBinding
    original_init = LoopbackRpcBinding.__init__
    def recording_init(self, **kwargs):
        original_init(self, **kwargs)
        assert self._sign_request_id is True
        self._client = httpx.AsyncClient(transport=httpx.MockTransport(broker_reply))
    monkeypatch.setattr(LoopbackRpcBinding, "__init__", recording_init)
    app = build_app()
    # No canonical authority is configured in this local-only fixture.
    app.state.identity_shadow_store = None
    assert app.state.claw_device_directory_source.configured is True
    paths = ("/api/claw/local-access/devices", "/api/claw/inbox/tasks",
             "/api/claw/inbox/alerts", "/api/pc/pairings", "/api/chat/custom/credential")
    with TestClient(app, base_url="https://chat-com2-staging.padiem.net") as client:
        for path in paths:
            assert client.get(path).status_code == 401, path
        registration = client.post(
            "/api/auth/password/register",
            headers={"Origin": "https://chat-com2-staging.padiem.net"},
            json={"email": "route-owner@example.test", "password": "test-password-012345"},
        )
        assert registration.status_code == 200, registration.text
        for path in paths:
            response = client.get(path)
            assert response.status_code == 200, (path, response.status_code, response.text)
        assert calls


def test_host_directory_uses_existing_broker_secret_and_fails_closed(staging_host_env, monkeypatch):
    from app.config import ConfigError
    monkeypatch.setenv("PADIEM_COM2_BROKER_RPC_SECRET_FILE", str(staging_host_env / "missing"))
    with pytest.raises(ConfigError, match="PADIEM_COM2_BROKER_RPC_SECRET_FILE"):
        build_app()


@pytest.mark.parametrize("reason,shared,expected", [
    ("control_plane_identity_not_linked", True, "tenant:verified"),
    ("control_plane_session_mismatch", True, None),
    ("control_plane_session_inactive", True, None),
    ("control_plane_identity_not_linked", False, None),
])
def test_shared_workspace_fallback_only_for_missing_shadow(reason, shared, expected, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from app import claw_memory_routes, chat_pc_drive
    from app.control_plane_identity import IdentityBridgeError
    user = "usr_" + "a" * 32
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(identity_shadow_store=object(),
                                                   control_plane_identity_authority=object())),
        state=SimpleNamespace(padiem_shared_user_id=user if shared else None),
    )
    monkeypatch.setattr(claw_memory_routes, "auth_ready", lambda request: True)
    async def missing(**kwargs):
        raise IdentityBridgeError(503, reason, "unavailable")
    calls = []
    async def verified(request, uid):
        calls.append(uid)
        return object(), "subject:verified", "tenant:verified"
    monkeypatch.setattr(claw_memory_routes, "resolve_refreshed_session", missing)
    monkeypatch.setattr(chat_pc_drive, "_resolve_chat_owner", verified)
    assert asyncio.run(claw_memory_routes._resolve_memory_workspace(request, user)) == expected
    assert calls == ([user] if expected else [])


def test_com2_pdfmd_local_roundtrip_and_owner_fence(staging_host_env, monkeypatch):
    import importlib.util
    from types import SimpleNamespace
    from app import document_convert_routes

    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "password")
    original_find_spec = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a, **kw: (
        object() if name == "pypdf" else original_find_spec(name, *a, **kw)
    ))
    monkeypatch.setattr(document_convert_routes, "convert_pdf_to_markdown", lambda **kw: SimpleNamespace(
        markdown="# synthetic conversion", page_count=1, public_dict=lambda: {}
    ))
    app = build_app()
    assert app.state.pdfmd_com2_ready is True
    origin = "https://chat-com2-staging.padiem.net"
    with TestClient(app, base_url=origin, headers={"Origin": origin}) as owner:
        assert owner.post("/api/auth/password/register", json={
            "email": "owner@example.com", "password": "test-password-1234"
        }).status_code == 200
        listing = owner.get("/api/document-conversions")
        assert listing.status_code == 200
        assert listing.json()["new_work_enabled"] is True
        created = owner.post("/api/document-conversions", json={"mode": "fast"})
        assert created.status_code == 201, created.text
        job = created.json()["job"]["id"]
        uploaded = owner.post(f"/api/document-conversions/{job}/files", content=b"%PDF-1.4\nsynthetic",
            headers={"Content-Type": "application/octet-stream", "X-Padiem-Filename": "test.pdf",
                     "X-Padiem-Media-Type": "application/pdf"})
        assert uploaded.status_code == 201, uploaded.text
        item = uploaded.json()["items"][0]["id"]
        converted = owner.post(f"/api/document-conversions/items/{item}/run")
        assert converted.status_code == 200, converted.text
        downloaded = owner.get(f"/api/document-conversions/items/{item}/markdown")
        assert downloaded.status_code == 200 and downloaded.text == "# synthetic conversion"
        with TestClient(app, base_url=origin, headers={"Origin": origin}) as other:
            assert other.post("/api/auth/password/register", json={
                "email": "other@example.com", "password": "test-password-5678"
            }).status_code == 200
            assert other.get(f"/api/document-conversions/items/{item}/markdown").status_code == 404
            assert other.get(f"/api/document-conversions/{job}").status_code == 404


def test_com2_pdfmd_missing_dependency_keeps_writes_closed(staging_host_env, monkeypatch):
    import importlib.util
    from app import document_convert_routes

    original_find_spec = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a, **kw: (
        None if name == "pypdf" else original_find_spec(name, *a, **kw)
    ))
    app = build_app()
    assert app.state.pdfmd_com2_ready is False
    assert document_convert_routes.PDFMD_NEW_WORK_DISABLED is True



def test_open_source_notice_is_reachable_from_chat(local_client):
    index = local_client.get("/")
    assert index.status_code == 200
    assert 'href="./third-party-licenses.html"' in index.text
    notice = local_client.get("/third-party-licenses.html")
    assert notice.status_code == 200
    assert "PyMuPDF" in notice.text
    assert "AGPL-3.0" in notice.text
    assert "https://github.com/pymupdf/PyMuPDF" in notice.text


def test_com2_council_entry_and_the_retired_councillor_alias(staging_host_env):
    # Exercise actual CPython composition, not a standalone static test app.
    app = build_app()
    origin = "https://chat-com2-staging.padiem.net"
    with TestClient(app, base_url=origin) as client:
        council = client.get("/apps/council/")
        assert council.status_code == 200
        assert "./static/council-app.css" in council.text
        for url in ("/apps/council/static/council-app.css",
                    "/apps/council/static/council-app.js",
                    "/apps/council/static/assets/parliament-hero.jpg"):
            assert client.get(url).status_code == 200, url
        # 2026-11-01: the old profile screen is gone; the alias redirects to
        # the one council product, and the deleted assets are no longer served.
        councillor = client.get("/councillor/", follow_redirects=False)
        assert councillor.status_code == 302
        assert councillor.headers["location"] == "/apps/council/"
        assert client.get("/councillor/").url.path == "/apps/council/"
        assert client.get("/councillor/councillor.css").status_code == 404
        assert client.get("/councillor/councillor.js").status_code == 404
        assert client.get("/api/auth/status").status_code == 200
        assert client.get("/apps/council/static/missing.js").status_code == 404



def test_hwpx_project_upload_real_sqlite_and_owner_scope(local_client, monkeypatch):
    from padiem_ai_core.hwpx_package_serializer import (
        HwpxPackageContent, HwpxPackageSection, serialize_hwpx_package,
    )
    registered = local_client.post("/api/auth/password/register", json={
        "email":"hwpx-owner@example.test", "password":"test-password-12345"
    })
    assert registered.status_code == 200, registered.text
    project = local_client.post("/api/projects", json={"name":"HWPX sample", "instructions":""})
    assert project.status_code == 201, project.text
    project_id = project.json()["project"]["id"]
    payload = serialize_hwpx_package(HwpxPackageContent(
        sections=(HwpxPackageSection(paragraphs=("HWPX project context 261101",)),)
    ))
    uploaded = local_client.post(f"/api/projects/{project_id}/files", content=payload, headers={
        "Content-Type":"application/octet-stream", "X-Padiem-Filename":"sample.hwpx",
        "X-Padiem-Media-Type":"application/hwp+zip",
    })
    assert uploaded.status_code == 201, uploaded.text
    record = uploaded.json()["file"]
    assert record["media_type"] == "extracted/hwpx"
    file_id = record["id"]
    detail = local_client.get(f"/api/projects/{project_id}/files/{file_id}")
    assert detail.status_code == 200
    assert "HWPX project context 261101" in detail.json()["file"]["content"]
    original = local_client.get(f"/api/projects/{project_id}/files/{file_id}/original")
    assert original.status_code == 200 and original.content == payload
    assert original.headers["content-type"] == "application/hwp+zip"
    from app.b14_client import B14Client
    observed = []
    async def fake_model(self, messages, **kwargs):
        observed.append(kwargs.get("additional_system_context"))
        return {"answer": "synthetic project answer"}
    monkeypatch.setattr(B14Client, "complete", fake_model)
    answer = local_client.post("/api/chat", json={
        "messages":[{"role":"user","content":"Summarize"}], "project_id":project_id
    })
    assert answer.status_code == 200, answer.text
    assert answer.json()["answer"] == "synthetic project answer"
    assert observed and "HWPX project context 261101" in observed[0]
    local_client.post("/api/auth/logout")
    other = local_client.post("/api/auth/password/register", json={
        "email":"hwpx-other@example.test", "password":"test-password-67890"
    })
    assert other.status_code == 200
    assert local_client.get(f"/api/projects/{project_id}/files/{file_id}").status_code == 404
    assert local_client.get(f"/api/projects/{project_id}/files/{file_id}/original").status_code == 404



def test_hwpx_schema_migration_keeps_existing_rows_and_indexes():
    from pathlib import Path
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE users(id TEXT PRIMARY KEY);
        CREATE TABLE projects(id TEXT PRIMARY KEY);
        CREATE TABLE project_files(
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, user_id TEXT NOT NULL,
            name TEXT NOT NULL, media_type TEXT NOT NULL, content_text TEXT NOT NULL,
            content_chars INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            country TEXT NOT NULL DEFAULT 'kr');
        INSERT INTO users VALUES ('u'); INSERT INTO projects VALUES ('p');
        INSERT INTO project_files VALUES ('f','p','u','old.txt','text/plain','hello',5,'a','b','kr');
    """)
    con.executescript((migrations / "077_project_files_text_byte_bound.sql").read_text(encoding="utf-8"))
    con.executescript((migrations / "078_project_files_doc_kind.sql").read_text(encoding="utf-8"))
    con.execute("UPDATE project_files SET doc_kind='meeting', doc_version_of='old' WHERE id='f'")
    con.executescript((migrations / "083_project_files_hwpx.sql").read_text(encoding="utf-8"))
    assert con.execute("SELECT content_text,doc_kind,doc_version_of FROM project_files WHERE id='f'").fetchone() == ("hello","meeting","old")
    con.execute("INSERT INTO project_files (id,project_id,user_id,name,media_type,content_text,content_chars,created_at,updated_at) VALUES ('new','p','u','x.hwpx','extracted/hwpx','hi',2,'a','b')")
    indexes = {row[1] for row in con.execute("PRAGMA index_list(project_files)")}
    assert {"idx_project_files_owner_project","idx_project_files_project_updated","idx_project_files_kind"} <= indexes
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO project_files (id,project_id,user_id,name,media_type,content_text,content_chars,created_at,updated_at) VALUES ('bad','p','u','x','unknown','hi',2,'a','b')")
    con.close()
