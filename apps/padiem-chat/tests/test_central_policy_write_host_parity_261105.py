"""Central model-route writes must be composable on the CPython host, not only on the Worker.

#6835-era dashboards sign central policy receipts with a server-only key. The
Worker read it from a secret binding and the host never passed it, so every
central write on comp2 answered 503 `central_model_route_write_unavailable`
while the route ledger itself (migration 050) was already present. These tests
pin the env name, the derivation the factory performs, and the fail-closed
behaviour when the key is absent. No key value ever appears in a test name or
assertion beyond a clearly synthetic fixture.
"""
from __future__ import annotations

from app.central_model_route_routes import route_ready
from app.local_cpython import build_app


SYNTHETIC_KEY = "ab" * 32          # 64 hex characters, fixture material only
ENV_NAME = "PADIEM_CENTRAL_MODEL_POLICY_SIGNING_KEY"


def _host_env(monkeypatch, tmp_path):
    monkeypatch.setattr("app.local_cpython.compose_local_b14_transports",
                        lambda settings, proof: (None, None))
    monkeypatch.delenv("PADIEM_LOCAL_DEV", raising=False)
    monkeypatch.setenv("PADIEM_CHAT_CPYTHON_HOST", "1")
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "mock")
    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "off")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")
    monkeypatch.setenv("PADIEM_CHAT_PUBLIC_BASE_URL", "https://chat-com2-staging.padiem.net")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", "test-local-secret-0123456789abcdef")


def test_the_host_reads_the_same_key_name_the_worker_uses():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    worker = (root / "worker.py").read_text(encoding="utf8")
    host = (root / "app" / "local_cpython.py").read_text(encoding="utf8")
    assert f'"{ENV_NAME}"' in worker
    assert f'"{ENV_NAME}"' in host
    # Both feed the ONE factory parameter; the host defines no second path.
    assert "central_model_policy_signing_key=" in worker
    assert "central_model_policy_signing_key=" in host


def test_configured_key_composes_a_writable_central_lane(monkeypatch, tmp_path):
    _host_env(monkeypatch, tmp_path)
    monkeypatch.setenv(ENV_NAME, SYNTHETIC_KEY)
    app = build_app()

    key = app.state.central_model_policy_write_key
    assert isinstance(key, bytes) and len(key) == 32
    store = app.state.central_model_route_store
    assert store is not None and callable(store.commit) and callable(store.snapshot)

    request = type("Request", (), {"app": type("App", (), {"state": app.state})})()
    assert route_ready(request) is True


def test_a_malformed_key_stays_fail_closed(monkeypatch, tmp_path):
    _host_env(monkeypatch, tmp_path)
    monkeypatch.setenv(ENV_NAME, "not-a-256-bit-key")
    app = build_app()
    assert app.state.central_model_policy_write_key is None


def test_absent_key_keeps_central_writes_refused(monkeypatch, tmp_path):
    _host_env(monkeypatch, tmp_path)
    monkeypatch.delenv(ENV_NAME, raising=False)
    app = build_app()
    assert app.state.central_model_policy_write_key is None
    request = type("Request", (), {"app": type("App", (), {"state": app.state})})()
    assert route_ready(request) is False
