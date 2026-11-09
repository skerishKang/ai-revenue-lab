"""#7306: the Claw live SSE switch must exist on the COM2 host too.

``worker.py`` composes ``claw_live_sse_enabled`` from the deployment flag
``PADIEM_CLAW_P01_LIVE_SSE_ENABLED`` with the rule: B14 runtime, the flag is
exactly ``"true"``, and the composed P01 adapter has a verified canonical
subject lane. The CPython host hardcoded ``False``, so the lane stayed off here
even when the deployment armed it, and the Claw capabilities endpoint answered
``live_events_available=false`` on COM2 only.

These tests pin the host composition to the Worker's flag and judgment, pin the
off-state to today's behaviour, and prove the switch turns on only with a real
subject lane. No Engine, B14 or network call is made.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.local_cpython import build_app

ROOT = Path(__file__).resolve().parents[1]
FLAG = "PADIEM_CLAW_P01_LIVE_SSE_ENABLED"
CREDENTIAL = "host-claw-live-test-credential-0123456789"
QUOTA_SALT = "host-claw-live-quota-salt-0123456789"


def _host_env(monkeypatch, tmp_path, *, flag=None, p01=True, identity=True, search=True):
    class _Transport:
        pass

    monkeypatch.setattr(
        "app.local_cpython.compose_local_b14_transports",
        lambda settings, proof: (_Transport(), _Transport()),
    )
    monkeypatch.setenv("PADIEM_CHAT_CPYTHON_HOST", "1")
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "b14")
    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "off")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")
    monkeypatch.setenv("PADIEM_CHAT_PUBLIC_BASE_URL", "https://chat-com2-staging.padiem.net")
    monkeypatch.setenv("PADIEM_CHAT_B14_BASE_URL", "https://b14.example")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", "test-local-secret-0123456789abcdef")
    monkeypatch.setenv("PADIEM_CHAT_QUOTA_SALT", QUOTA_SALT)
    monkeypatch.delenv(FLAG, raising=False)
    if flag is not None:
        monkeypatch.setenv(FLAG, flag)
    for name in (
        "PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN",
        "PADIEM_CHAT_LOCAL_P01_CALLER_ID",
        "PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL",
        "PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN",
        "PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET",
        "PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    if search:
        # The 컴2 production env arms the Claw lane; the adapter must exist for
        # the live SSE judgment to be exercised at all.
        monkeypatch.setenv("PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED", "true")
    if p01:
        monkeypatch.setenv("PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN", "http://127.0.0.1:8811")
        monkeypatch.setenv("PADIEM_CHAT_LOCAL_P01_CALLER_ID", "b62-chat-host")
        monkeypatch.setenv("PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL", CREDENTIAL)
    if identity:
        monkeypatch.setenv("PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN", "https://127.0.0.1:8810")
        monkeypatch.setenv("PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET", "identity-rpc-secret-0123456789abcdef")


def _fake_adapter(*, subject_lane):
    runner = SimpleNamespace(_client=object())
    return SimpleNamespace(
        subject_identity_lane=subject_lane,
        _runner=runner,
        enable_subject_identity=lambda value: None,
    )


def test_an_absent_switch_leaves_the_host_exactly_as_it_is_today(monkeypatch, tmp_path):
    _host_env(monkeypatch, tmp_path)
    app = build_app()

    assert app.state.claw_live_sse_enabled is False


def test_an_explicit_false_switch_keeps_the_lane_off(monkeypatch, tmp_path):
    _host_env(monkeypatch, tmp_path, flag="false")
    app = build_app()

    assert app.state.claw_live_sse_enabled is False


def test_true_without_a_p01_surface_fails_closed(monkeypatch, tmp_path):
    _host_env(monkeypatch, tmp_path, flag="true", p01=False)
    app = build_app()

    assert app.state.claw_live_sse_enabled is False


def test_true_without_a_verified_identity_lane_stays_off(monkeypatch, tmp_path):
    _host_env(monkeypatch, tmp_path, flag="true", identity=False)
    app = build_app()

    assert app.state.claw_live_sse_enabled is False


def test_true_with_a_verified_subject_lane_arms_the_switch(monkeypatch, tmp_path):
    _host_env(monkeypatch, tmp_path, flag="true")
    monkeypatch.setattr(
        "app.local_cpython.build_local_p01_lanes",
        lambda env, **kwargs: (_fake_adapter(subject_lane=True), None, None),
    )
    app = build_app()

    assert app.state.claw_live_sse_enabled is True


def test_worker_and_host_read_the_same_flag_with_the_same_judgment():
    worker = (ROOT / "worker.py").read_text(encoding="utf8")
    host = (ROOT / "app" / "local_cpython.py").read_text(encoding="utf8")

    assert 'getattr(self.env, "PADIEM_CLAW_P01_LIVE_SSE_ENABLED", None) == "true"' in worker
    assert 'binding_value(\n                os.environ, "PADIEM_CLAW_P01_LIVE_SSE_ENABLED"\n            ) == "true"' in host
    for source in (worker, host):
        assert 'settings.runtime_mode == "b14"' in source
        assert 'subject_identity_lane' in source
