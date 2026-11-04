"""#5034 Web Push has to be composable on the CPython host, not only on the Worker.

The push sender needs VAPID material AND a transport. The Worker built both;
the host passed neither, and the adapter class itself lived inside ``worker.py``
so the host had no way to compose one. The factory therefore left
``claw_push_sender`` unset on comp2 and the capability route answered
``not_configured`` forever. These tests pin the shared adapter, the env names,
and the fail-closed behaviour when material is missing or partial.
"""
from __future__ import annotations

import base64
from pathlib import Path

from app.claw_web_push_sender import WebPushSender
from app.local_cpython import build_app
from app.push_http_transport import PushHttpTransport, build_host_push_transport

ENV_NAMES = (
    "PADIEM_PUSH_VAPID_PRIVATE_KEY",
    "PADIEM_PUSH_VAPID_PUBLIC_KEY",
    "PADIEM_PUSH_VAPID_SUBJECT",
)
# Fixture material only: raw bytes encoded the way the Web Push ecosystem
# exchanges them. These are not credentials and never leave the test.
SYNTHETIC_PRIVATE = base64.urlsafe_b64encode(b"\x11" * 32).decode().rstrip("=")
SYNTHETIC_PUBLIC = base64.urlsafe_b64encode(b"\x04" + b"\x22" * 64).decode().rstrip("=")
SYNTHETIC_SUBJECT = "mailto:synthetic-fixture@example.invalid"


def _app_source_root():
    return Path(__file__).resolve().parents[1]


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


def test_one_adapter_serves_both_runtimes():
    """The host parity must not be paid for with a second implementation."""
    worker = (_app_source_root() / "worker.py").read_text(encoding="utf8")
    host = (_app_source_root() / "app" / "local_cpython.py").read_text(encoding="utf8")
    assert "class _PushHttpTransport" not in worker
    assert "from app.push_http_transport import PushHttpTransport" in worker
    assert "PushHttpTransport(CloudflareExternalHttpTransport())" in worker
    assert "from .push_http_transport import build_host_push_transport" in host
    assert "claw_push_transport=build_host_push_transport()," in host


def test_the_host_reads_the_same_env_names_the_worker_uses():
    worker = (_app_source_root() / "worker.py").read_text(encoding="utf8")
    host = (_app_source_root() / "app" / "local_cpython.py").read_text(encoding="utf8")
    for name in ENV_NAMES:
        assert f'"{name}"' in worker
        assert f'"{name}"' in host
    for kwarg in ("claw_push_vapid_private_key=", "claw_push_vapid_public_key=",
                  "claw_push_vapid_subject=", "claw_push_transport="):
        assert kwarg in worker and kwarg in host


def test_host_transport_is_the_shared_adapter(monkeypatch):
    monkeypatch.delenv("PADIEM_LOCAL_DEV", raising=False)
    transport = build_host_push_transport()
    assert isinstance(transport, PushHttpTransport)


def test_complete_material_composes_a_configured_sender(monkeypatch, tmp_path):
    _host_env(monkeypatch, tmp_path)
    for name, value in zip(ENV_NAMES, (SYNTHETIC_PRIVATE, SYNTHETIC_PUBLIC, SYNTHETIC_SUBJECT)):
        monkeypatch.setenv(name, value)
    app = build_app()

    sender = app.state.claw_push_sender
    assert isinstance(sender, WebPushSender)
    assert sender.configured is True
    assert isinstance(sender._transport, PushHttpTransport)
    assert sender._authority.subject == SYNTHETIC_SUBJECT
    # The browser-visible half is the public key only.
    assert app.state.claw_push_public_key == SYNTHETIC_PUBLIC


def test_missing_or_partial_material_stays_unconfigured(monkeypatch, tmp_path):
    # The factory publishes the browser-visible public half independently, so an
    # incomplete pair must still never yield a sender: delivery is impossible and
    # the capability route keeps answering not_configured.
    for partial in (
        {},
        {ENV_NAMES[1]: SYNTHETIC_PUBLIC},
        {ENV_NAMES[0]: SYNTHETIC_PRIVATE, ENV_NAMES[1]: SYNTHETIC_PUBLIC},
    ):
        _host_env(monkeypatch, tmp_path)
        for name in ENV_NAMES:
            monkeypatch.delenv(name, raising=False)
        for name, value in partial.items():
            monkeypatch.setenv(name, value)
        app = build_app()
        assert app.state.claw_push_sender is None, partial
        expected_public = partial.get(ENV_NAMES[1])
        assert app.state.claw_push_public_key == expected_public, partial
