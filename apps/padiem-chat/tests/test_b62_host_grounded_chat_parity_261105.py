"""Chat grounding must execute through the dispatch-aware client on the CPython host.

The #6849 audit found the same ordering shape twice: the app factory builds a
subsystem FROM `app.state.b14_client`, and the host later replaces that client
without rebuilding the subsystem, which then keeps the placeholder client the
factory captured. B66 quote execution was one (a 502 before any B14 request);
`grounded_chat` is the other — a Chat web-search turn runs on the host without
the dispatch proof and without the reservation-refund rule the dispatch-aware
client carries. These tests pin the host rebuild and the general rule, so a new
factory capture cannot silently rot again.
"""
from __future__ import annotations

import re

from app.b66_registered_model_boundary import B66RegisteredModelCompletion
from app.dispatch_quota import DispatchAwareB14Client
from app.grounding import GroundedChatService
from app.local_cpython import build_app
from app.b66_quote_conversation import B66QuoteConversationInterpreter


def _host_env(monkeypatch, tmp_path):
    class _Transport:
        pass

    monkeypatch.setattr("app.local_cpython.compose_local_b14_transports",
                        lambda settings, proof: (_Transport(), _Transport()))
    monkeypatch.setenv("PADIEM_CHAT_CPYTHON_HOST", "1")
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "b14")
    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "off")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")
    monkeypatch.setenv("PADIEM_CHAT_PUBLIC_BASE_URL", "https://chat-com2-staging.padiem.net")
    monkeypatch.setenv("PADIEM_CHAT_B14_BASE_URL", "https://b14.example")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", "test-local-secret-0123456789abcdef")


def test_host_grounding_lane_holds_the_dispatch_aware_client(monkeypatch, tmp_path):
    _host_env(monkeypatch, tmp_path)
    app = build_app()

    grounded = app.state.grounded_chat
    assert isinstance(grounded, GroundedChatService)
    assert grounded._b14_client is app.state.b14_client
    assert isinstance(grounded._b14_client, DispatchAwareB14Client)
    assert grounded._web_provider is app.state.web_provider
    # The placeholder the factory captured must not be what serves the lane.
    assert type(grounded._b14_client).__name__ != "PadiemTierB14Client"


def test_host_rebuilds_every_subsystem_that_captured_the_factory_client(monkeypatch, tmp_path):
    """The general rule: no factory capture may survive the host's replacement."""
    factory = (__import__("pathlib").Path(__file__).resolve().parents[1] / "app" /
               "app_factory.py").read_text(encoding="utf8")
    lines = factory.splitlines()
    captured: list[str] = []
    for index, line in enumerate(lines):
        if "app.state.b14_client" not in line or line.strip().startswith(
            "app.state.b14_client ="
        ):
            continue
        for back in range(index, max(index - 8, -1), -1):
            owner = re.match(r"\s*app\.state\.([a-z_0-9]+) = ", lines[back])
            if owner:
                captured.append(owner.group(1))
                break
    assert captured, "the factory must still capture the client somewhere"
    assert set(captured) <= {"b66_quote_interpreter", "grounded_chat"}, captured

    host = (__import__("pathlib").Path(__file__).resolve().parents[1] / "app" /
            "local_cpython.py").read_text(encoding="utf8")
    replaced = host.index("app.state.b14_client = DispatchAwareB14Client(")
    tail = host[replaced:]
    for name in set(captured):
        assert f"app.state.{name} = " in tail, f"{name} keeps the factory client"

    _host_env(monkeypatch, tmp_path)
    app = build_app()
    assert isinstance(app.state.grounded_chat, GroundedChatService)
    assert isinstance(app.state.b66_quote_interpreter._client, B66RegisteredModelCompletion)
    assert isinstance(app.state.b66_quote_interpreter, B66QuoteConversationInterpreter)


def test_the_worker_and_the_host_compose_the_same_grounding_collaborators():
    """Parity with worker.py, which is the reference composition."""
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    worker = (root / "worker.py").read_text(encoding="utf8")
    host = (root / "app" / "local_cpython.py").read_text(encoding="utf8")
    assert "worker_app.state.grounded_chat = GroundedChatService(" in worker
    assert "app.state.grounded_chat = GroundedChatService(" in host
    for source in (worker, host):
        block = source[source.index("state.grounded_chat = GroundedChatService("):]
        block = block[:block.index(")") + 1]
        assert "state.b14_client," in block and "state.web_provider," in block
