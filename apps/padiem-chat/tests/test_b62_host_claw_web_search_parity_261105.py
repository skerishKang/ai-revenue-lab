"""#4469: the Claw public web search switch must exist on the COM2 host too.

worker.py composes ``claw_web_search_enabled``; the CPython host never did, so
after the 10-31 COM2 move the deployment flag was read nowhere and the lane
stayed off. These tests pin the host composition to the Worker's class and
arguments, pin the off-state to today's host behaviour, and prove that a turn
reaches the search client once the switch is on.

No Engine, provider, D1 or network call is made here: the lane composition is
either the real loopback wiring (construction only) or a recording fake.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

from app.claw_general_routes import _claw_public_search_grounding
from app.claw_search_decision import trusted_claw_search_activation
from app.local_cpython import build_app
from kagent.p01_adapter import P01CoreOrchestrationAdapter

ROOT = Path(__file__).resolve().parents[1]
FLAG = "PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED"
CREDENTIAL = "host-claw-web-search-test-credential-0123456789"
QUOTA_SALT = "host-claw-web-search-quota-salt-0123456789"
FENCED = "웹 근거 사용 규칙:\n[1] {\"title\": \"공고\", \"snippet\": \"2026년 신청 기간\"}"
GOOD_SOURCE = {
    "url": "https://example.org/notice",
    "title": "2026년 공고",
    "retrieved_at": "2026-10-15T00:00:00Z",
}
NEEDS_SEARCH = {
    "needs_search": True,
    "query": "2026 광주 청년창업 지원사업 신청기간 모집 공고",
    "reason": "volatile_business_fact",
}


def _host_env(monkeypatch, tmp_path, *, flag=None, p01=True, identity=True):
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
    # UsageGate.ready needs a durable counter store AND the salt it hashes with.
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
    ):
        monkeypatch.delenv(name, raising=False)
    if p01:
        # Constructing the loopback transport is offline; nothing is called.
        monkeypatch.setenv("PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN", "http://127.0.0.1:8811")
        monkeypatch.setenv("PADIEM_CHAT_LOCAL_P01_CALLER_ID", "b62-chat-host")
        monkeypatch.setenv("PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL", CREDENTIAL)
    if identity:
        # The local service bridge accepts bare https origins only; no call is made.
        monkeypatch.setenv("PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN", "https://127.0.0.1:8810")
        monkeypatch.setenv("PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET", "identity-rpc-secret-0123456789abcdef")


# --- the switch is off unless the deployment asks for it --------------------


def test_an_absent_switch_leaves_the_host_exactly_as_it_is_today(monkeypatch, tmp_path):
    _host_env(monkeypatch, tmp_path)
    app = build_app()

    assert app.state.claw_web_search_enabled is False
    # Today's host composes no Claw lane at all; the off-state must not change.
    assert getattr(app.state, "claw_p01_adapter", None) is None


def test_an_explicit_false_switch_composes_nothing(monkeypatch, tmp_path):
    _host_env(monkeypatch, tmp_path, flag="false")
    app = build_app()

    assert app.state.claw_web_search_enabled is False
    assert getattr(app.state, "claw_p01_adapter", None) is None


def test_true_without_a_p01_surface_fails_closed(monkeypatch, tmp_path):
    _host_env(monkeypatch, tmp_path, flag="true", p01=False)
    app = build_app()

    assert app.state.claw_web_search_enabled is False
    assert getattr(app.state, "claw_p01_adapter", None) is None


def test_true_without_a_verified_identity_lane_stays_off(monkeypatch, tmp_path):
    _host_env(monkeypatch, tmp_path, flag="true", identity=False)
    app = build_app()

    # The lane is composed, but the canonical subject cannot be revalidated, so
    # the trusted activation (same rule as the Worker) refuses to arm it.
    assert app.state.claw_p01_adapter is not None
    assert app.state.claw_p01_adapter.subject_identity_lane is False
    assert app.state.claw_web_search_enabled is False


# --- true composes the Worker's class and arguments -------------------------


def test_true_composes_the_worker_lane_and_arms_the_switch(monkeypatch, tmp_path):
    _host_env(monkeypatch, tmp_path, flag="true")
    app = build_app()

    adapter = app.state.claw_p01_adapter
    assert isinstance(adapter, P01CoreOrchestrationAdapter)
    assert adapter.subject_identity_lane is True
    assert app.state.claw_p01_continuation_client is not None
    client = adapter._runner._client
    assert callable(getattr(client, "search_judgement", None))
    assert callable(getattr(client, "search_evidence", None))
    assert app.state.claw_web_search_enabled is True
    # The one web provider Chat already composed is still the only provider;
    # the host never builds a second one for this lane.
    assert app.state.grounded_chat._web_provider is app.state.web_provider


# --- the armed lane reaches the search client on a real turn ----------------


class _FakeSearchClient:
    """Stands in for the two Engine operations and records every call."""

    def __init__(self):
        self.judge_calls = []
        self.evidence_calls = []

    async def search_judgement(self, *, conversation, agent):
        self.judge_calls.append({"conversation": conversation, "agent": agent})
        return NEEDS_SEARCH

    async def search_evidence(self, *, query, agent):
        self.evidence_calls.append({"query": query, "agent": agent})
        return {"sources": [GOOD_SOURCE], "grounding_context": FENCED}


def _fake_adapter(client):
    runner = SimpleNamespace(_client=client)
    return SimpleNamespace(
        subject_identity_lane=True,
        _runner=runner,
        enable_subject_identity=lambda value: None,
    )


def test_a_true_turn_reaches_the_composed_search_client(monkeypatch, tmp_path):
    _host_env(monkeypatch, tmp_path, flag="true")
    client = _FakeSearchClient()
    monkeypatch.setattr(
        "app.local_cpython.build_local_p01_lanes",
        lambda env, **kwargs: (_fake_adapter(client), None, None),
    )
    app = build_app()
    assert app.state.claw_web_search_enabled is True

    request = SimpleNamespace(app=SimpleNamespace(state=app.state))
    messages = [{"role": "user", "content": "올해도 신청할 수 있어?"}]
    context, sources = asyncio.run(
        _claw_public_search_grounding(
            request, app.state.claw_p01_adapter, messages,
            model_id="test/selected-model",
        )
    )

    assert len(client.judge_calls) == 1
    assert len(client.evidence_calls) == 1
    assert client.evidence_calls[0]["query"] == NEEDS_SEARCH["query"]
    assert context == FENCED
    assert sources == (
        {
            "url": GOOD_SOURCE["url"],
            "title": GOOD_SOURCE["title"],
            "retrieved_at": GOOD_SOURCE["retrieved_at"],
        },
    )


# --- parity with the Worker composition ------------------------------------


def test_worker_and_host_call_the_same_activation_with_the_same_arguments():
    worker = (ROOT / "worker.py").read_text(encoding="utf8")
    host = (ROOT / "app" / "local_cpython.py").read_text(encoding="utf8")

    for source in (worker, host):
        start = source.index("trusted_claw_search_activation(")
        block = source[start:start + 600]
        assert "flag=" in block
        assert "runtime_mode=" in block
        assert "adapter=" in block
        assert "usage_gate=" in block
        assert '"PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED"' in block

    assert "build_local_p01_lanes(" in host
    assert "compose_p01_lanes(" not in host, "the host must reuse the shared lane wiring"


def test_the_activation_rule_is_the_one_shared_function():
    assert trusted_claw_search_activation(
        flag="true",
        runtime_mode="b14",
        adapter=_fake_adapter(_FakeSearchClient()),
        usage_gate=SimpleNamespace(ready=True),
    ) is True
    assert trusted_claw_search_activation(
        flag="false",
        runtime_mode="b14",
        adapter=_fake_adapter(_FakeSearchClient()),
        usage_gate=SimpleNamespace(ready=True),
    ) is False
