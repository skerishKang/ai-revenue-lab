"""Engine Gmail trusted binding entry + composition seam tests (WO-10 PR-B).

Network-free. Stubs the Core ``GmailReadPort`` boundary with a recording
fake so the Engine can be exercised end-to-end without a real Google OAuth
client. All non-Gmail Engine routes stay at the source seam (composition
fail-closed for everything else).
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types
from typing import Any

import pytest

from app.connector_bindings import (
    GMAIL_MAIL_READER_AGENT_ID,
    GMAIL_PORT_BOUND_IN_PRODUCTION,
    GMAIL_REFERENCE_APP_ID,
    GmailGrant,
    build_tool_binding_resolver,
    gmail_tool_binding,
)
from app.tool_execution_service import ToolExecutionEngineService
from app.tool_projection import (
    EngineToolProjectionError,
    TOOL_EXECUTE_PATH,
    TrustedToolAuthority,
)


# --- composition seam: load worker_identity with stubbed workers module ----


class _StubBindingResponse:
    def __init__(self, body: bytes = b"{}") -> None:
        self.status = 200
        self.headers = {"get": lambda _name: "application/json"}
        self.body = body


class _StubB14Binding:
    async def fetch(self, _js_object: Any) -> _StubBindingResponse:
        return _StubBindingResponse(body=b'{"sentinel": true}')


class _FakeResponse:
    def __init__(self, body: Any = None, status: int = 200, headers: Any = None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(self, ctx: Any = None, env: Any = None) -> None:
        self.ctx = ctx
        self.env = env


def _workers_stub() -> types.ModuleType:
    module = types.ModuleType("workers")
    module.Request = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    module.Response = _FakeResponse  # type: ignore[attr-defined]
    module.WorkerEntrypoint = _FakeWorkerEntrypoint  # type: ignore[attr-defined]
    return module


class _BoundEnv:
    def __init__(self) -> None:
        self.B14_SERVICE = _StubB14Binding()
        self.PADIEM_ENGINE_WEB_PROVIDER = "mock"


def _load_worker_identity(monkeypatch, fake_resolver):
    """Reload worker_identity with a stubbed ``workers`` module and a
    monkeypatched ``_tool_binding_resolver_for_env`` that returns
    ``fake_resolver`` (or None to simulate the unbound branch)."""
    saved = {
        name: sys.modules.get(name)
        for name in ("workers", "worker", "worker_identity")
    }
    sys.modules["workers"] = _workers_stub()
    for name in ("worker", "worker_identity"):
        sys.modules.pop(name, None)
    identity = importlib.import_module("worker_identity")
    monkeypatch.setattr(
        identity,
        "_tool_binding_resolver_for_env",
        lambda _env: fake_resolver,
    )
    return identity, saved


def _restore(saved: dict) -> None:
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


class FakeGmailPort:
    """Records each get_json call; returns a queued canned response."""

    def __init__(self, response: dict | None = None) -> None:
        self.calls: list[dict] = []
        self._response = response or {
            "messages": [
                {"id": "msg_1", "threadId": "thread_1"},
                {"id": "msg_2", "threadId": "thread_1"},
            ]
        }

    def get_json(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def _grant(**overrides) -> GmailGrant:
    values = {
        "app_id": GMAIL_REFERENCE_APP_ID,
        "canonical_agent_id": GMAIL_MAIL_READER_AGENT_ID,
        "binding_ref": "bind:gmail_engine",
        "actor_ref": "actor:gmail_engine",
        "granted_scopes": ("gmail.readonly",),
    }
    values.update(overrides)
    return GmailGrant(**values)


def run(coro):
    return asyncio.run(coro)


# --- assembly: EngineToolBinding invariants --------------------------------


def test_binding_assembles_with_canonical_authority_and_registry() -> None:
    binding = gmail_tool_binding(grant=_grant(), port=FakeGmailPort())
    assert binding.app_id == GMAIL_REFERENCE_APP_ID
    assert type(binding.tool_runtime).__name__ == "ToolRuntime"
    assert set(binding.registry.canonical_tool_ids) == {
        "tool:google:gmail.search_messages@1",
        "tool:google:gmail.get_message@1",
        "tool:google:gmail.get_thread@1",
    }
    assert set(binding.authorities) == {GMAIL_MAIL_READER_AGENT_ID}
    authority = binding.authorities[GMAIL_MAIL_READER_AGENT_ID]
    assert isinstance(authority, TrustedToolAuthority)
    assert authority.authorization.app_id == GMAIL_REFERENCE_APP_ID
    assert authority.authorization.granted_auth_scopes == ("gmail.readonly",)


def test_binding_resolves_authority_and_maps_canonical_to_runtime() -> None:
    binding = gmail_tool_binding(grant=_grant(), port=FakeGmailPort())
    authority = binding.resolve_authority(GMAIL_MAIL_READER_AGENT_ID)
    entry = binding.resolve_tool("tool:google:gmail.search_messages@1")
    assert entry.runtime_tool_id == "gmail.search_messages"
    assert authority.canonical_agent_id == GMAIL_MAIL_READER_AGENT_ID


def test_binding_unknown_agent_fails_closed() -> None:
    binding = gmail_tool_binding(grant=_grant(), port=FakeGmailPort())
    with pytest.raises(EngineToolProjectionError) as info:
        binding.resolve_authority("agent:other:nope@1")
    assert info.value.code == "tool_agent_not_bound"
    assert info.value.status_code == 403


def test_binding_rejects_wrong_app_id_or_agent_id() -> None:
    with pytest.raises(EngineToolProjectionError) as info:
        gmail_tool_binding(grant=_grant(app_id="b62"), port=FakeGmailPort())
    assert info.value.code == "invalid_tool_binding"
    with pytest.raises(EngineToolProjectionError) as info2:
        gmail_tool_binding(
            grant=_grant(canonical_agent_id="agent:padiem:other@1"),
            port=FakeGmailPort(),
        )
    assert info2.value.code == "invalid_tool_binding"


# --- runtime authority: granted scopes vs Core spec -----------------------


def test_runtime_blocks_without_granted_scope() -> None:
    port = FakeGmailPort()
    binding = gmail_tool_binding(grant=_grant(granted_scopes=()), port=port)
    authority = binding.resolve_authority(GMAIL_MAIL_READER_AGENT_ID)
    entry = binding.resolve_tool("tool:google:gmail.search_messages@1")
    from padiem_ai_core import ToolInvocation

    invocation = ToolInvocation(
        tool_id=entry.runtime_tool_id, arguments={"query": "x"}
    )
    with pytest.raises(Exception) as info:
        run(
            binding.tool_runtime.execute(
                invocation, authority.compiled.runtime_profile, authority.authorization
            )
        )
    assert info.value.code == "tool_auth_scope_missing"
    assert port.calls == []


def test_runtime_passes_provider_url_scope_to_port() -> None:
    port = FakeGmailPort()
    binding = gmail_tool_binding(grant=_grant(), port=port)
    authority = binding.resolve_authority(GMAIL_MAIL_READER_AGENT_ID)
    entry = binding.resolve_tool("tool:google:gmail.search_messages@1")
    from padiem_ai_core import ToolInvocation

    invocation = ToolInvocation(
        tool_id=entry.runtime_tool_id, arguments={"query": "x"}
    )
    run(
        binding.tool_runtime.execute(
            invocation, authority.compiled.runtime_profile, authority.authorization
        )
    )
    assert len(port.calls) == 1
    assert port.calls[0]["required_scopes"] == (
        "https://www.googleapis.com/auth/gmail.readonly",
    )
    assert port.calls[0]["binding_ref"] == "bind:gmail_engine"
    assert port.calls[0]["actor_ref"] == "actor:gmail_engine"


# --- resolver factory: composition seam shape -----------------------------


def test_resolver_returns_none_when_port_missing() -> None:
    assert (
        build_tool_binding_resolver(
            gmail_port=None, grants={GMAIL_REFERENCE_APP_ID: _grant()}
        )
        is None
    )


def test_resolver_returns_none_when_grants_empty() -> None:
    assert build_tool_binding_resolver(gmail_port=FakeGmailPort(), grants={}) is None


def test_resolver_returns_callable_for_populated_inputs() -> None:
    resolver = build_tool_binding_resolver(
        gmail_port=FakeGmailPort(), grants={GMAIL_REFERENCE_APP_ID: _grant()}
    )
    assert callable(resolver)
    assert resolver(GMAIL_REFERENCE_APP_ID).app_id == GMAIL_REFERENCE_APP_ID
    assert resolver("b62") is None


def test_resolver_caches_binding_per_app_id() -> None:
    resolver = build_tool_binding_resolver(
        gmail_port=FakeGmailPort(), grants={GMAIL_REFERENCE_APP_ID: _grant()}
    )
    first = resolver(GMAIL_REFERENCE_APP_ID)
    second = resolver(GMAIL_REFERENCE_APP_ID)
    assert first is second


def test_resolver_factory_failure_propagates_engine_error_safely() -> None:
    """A grant that fails the EngineToolBinding identity checks surfaces
    as ``EngineToolProjectionError``. ``gmail_tool_binding`` does not invoke
    the port (registration only), so a leaky port cannot propagate through
    this path; the test asserts the leaky port path either succeeds (port
    never called) or, if it ever does leak, the safe_message and the
    cause / context chain do NOT contain the grant values.
    """

    class LeakyPort:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def get_json(self, **kwargs):
            self.calls.append(kwargs)
            raise EngineToolProjectionError(
                "invalid_tool_binding",
                "leak bind:SECRET123 actor:XYZ",
                status_code=503,
            )

    leaky = LeakyPort()
    resolver = build_tool_binding_resolver(
        gmail_port=leaky, grants={GMAIL_REFERENCE_APP_ID: _grant()}
    )
    try:
        binding = resolver(GMAIL_REFERENCE_APP_ID)
    except EngineToolProjectionError as exc:
        rendered = f"{exc.code} {exc} {exc.__cause__} {exc.__context__}"
        assert "bind:SECRET123" not in rendered
        assert "actor:XYZ" not in rendered
    else:
        assert binding.app_id == GMAIL_REFERENCE_APP_ID
        assert leaky.calls == []


# --- tool execution service: resolver in, gmail out -----------------------


def _execute_payload(tool_id: str, arguments: dict, agent_id: str = GMAIL_MAIL_READER_AGENT_ID) -> bytes:
    return json.dumps(
        {
            "app_id": GMAIL_REFERENCE_APP_ID,
            "agent_id": agent_id,
            "tool_id": tool_id,
            "arguments": arguments,
        }
    ).encode("utf-8")


def test_execution_service_runs_gmail_via_resolver() -> None:
    port = FakeGmailPort()
    resolver = build_tool_binding_resolver(
        gmail_port=port, grants={GMAIL_REFERENCE_APP_ID: _grant()}
    )
    service = ToolExecutionEngineService(tool_binding_resolver=resolver)
    response = run(
        service.handle(
            method="POST",
            path=TOOL_EXECUTE_PATH,
            content_type="application/json",
            body=_execute_payload(
                "tool:google:gmail.search_messages@1", {"query": "x"}
            ),
        )
    )
    assert response.status_code == 200
    body = response.body
    assert body["ok"] is True
    assert body["tool"]["agent_id"] == GMAIL_MAIL_READER_AGENT_ID
    assert body["tool"]["canonical_tool_id"] == "tool:google:gmail.search_messages@1"
    output = body["tool"]["output"]
    assert output["result_status"] == "OK"
    assert output["result_count"] == 2
    rendered = json.dumps(body, ensure_ascii=False, sort_keys=True)
    assert "bind:gmail_engine" not in rendered
    assert "actor:gmail_engine" not in rendered
    assert len(port.calls) == 1


def test_execution_service_rejects_extra_argument_keys() -> None:
    resolver = build_tool_binding_resolver(
        gmail_port=FakeGmailPort(), grants={GMAIL_REFERENCE_APP_ID: _grant()}
    )
    service = ToolExecutionEngineService(tool_binding_resolver=resolver)
    response = run(
        service.handle(
            method="POST",
            path=TOOL_EXECUTE_PATH,
            content_type="application/json",
            body=_execute_payload(
                "tool:google:gmail.get_message@1",
                {"messageId": "msg_1", "forbidden": "x"},
            ),
        )
    )
    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_tool_arguments"
    assert "forbidden" not in json.dumps(response.body, sort_keys=True)


def test_execution_service_fails_closed_for_unknown_app() -> None:
    resolver = build_tool_binding_resolver(
        gmail_port=FakeGmailPort(), grants={GMAIL_REFERENCE_APP_ID: _grant()}
    )
    service = ToolExecutionEngineService(tool_binding_resolver=resolver)
    body = json.dumps(
        {
            "app_id": "b62",
            "agent_id": GMAIL_MAIL_READER_AGENT_ID,
            "tool_id": "tool:google:gmail.search_messages@1",
            "arguments": {"query": "x"},
        }
    ).encode("utf-8")
    response = run(
        service.handle(
            method="POST",
            path=TOOL_EXECUTE_PATH,
            content_type="application/json",
            body=body,
        )
    )
    assert response.status_code == 503
    assert response.body["error"]["code"] == "tool_runtime_unavailable"
    rendered = json.dumps(response.body, ensure_ascii=False, sort_keys=True)
    assert "bind:gmail_engine" not in rendered


def test_execution_service_fails_closed_when_resolver_is_none() -> None:
    service = ToolExecutionEngineService(tool_binding_resolver=None)
    response = run(
        service.handle(
            method="POST",
            path=TOOL_EXECUTE_PATH,
            content_type="application/json",
            body=_execute_payload(
                "tool:google:gmail.search_messages@1", {"query": "x"}
            ),
        )
    )
    assert response.status_code == 503
    assert response.body["error"]["code"] == "tool_runtime_unavailable"


# --- truth flag for downstream activation gates ----------------------------


def test_port_bound_in_production_is_false_until_pr_c() -> None:
    assert GMAIL_PORT_BOUND_IN_PRODUCTION is False


# --- production composition seam: injected resolver runs gmail -------------


def test_composition_seam_runs_gmail_when_resolver_is_injected(monkeypatch) -> None:
    """With a real Gmail port + grant resolver monkeypatched into
    ``_tool_binding_resolver_for_env``, the canonical Production composition
    must drive a 200 gmail response through ``services.tool_execution``. With
    the resolver returning None (the PR-B default), every request still
    fails closed at the same seam — never auto-activating.
    """
    port = FakeGmailPort(
        response={
            "messages": [
                {"id": "msg_1", "threadId": "thread_1"},
            ]
        }
    )
    grant = _grant(binding_ref="bind:seam", actor_ref="actor:seam")
    resolver = build_tool_binding_resolver(
        gmail_port=port, grants={GMAIL_REFERENCE_APP_ID: grant}
    )
    identity, saved = _load_worker_identity(monkeypatch, fake_resolver=resolver)
    try:
        services = identity._engine_services_for_env(_BoundEnv())
        # Resolver must have been wired into both the tool execution service
        # AND the canonical orchestration service.
        assert services.tool_execution is not None
        assert (
            services.tool_execution._tool_binding_resolver is resolver  # type: ignore[attr-defined]
        )
        assert (
            services.orchestration._tool_binding_resolver is resolver  # type: ignore[attr-defined]
        )
        response = run(
            services.tool_execution.handle(
                method="POST",
                path=TOOL_EXECUTE_PATH,
                content_type="application/json",
                body=_execute_payload(
                    "tool:google:gmail.search_messages@1", {"query": "seam"}
                ),
            )
        )
        assert response.status_code == 200
        body = response.body
        assert body["ok"] is True
        assert body["tool"]["agent_id"] == GMAIL_MAIL_READER_AGENT_ID
        assert body["tool"]["canonical_tool_id"] == "tool:google:gmail.search_messages@1"
        output = body["tool"]["output"]
        assert output["result_count"] == 1
        rendered = json.dumps(body, ensure_ascii=False, sort_keys=True)
        assert "bind:seam" not in rendered
        assert "actor:seam" not in rendered
        assert len(port.calls) == 1
    finally:
        _restore(saved)


def test_composition_seam_fails_closed_when_resolver_returns_none(
    monkeypatch,
) -> None:
    identity, saved = _load_worker_identity(monkeypatch, fake_resolver=None)
    try:
        services = identity._engine_services_for_env(_BoundEnv())
        response = run(
            services.tool_execution.handle(
                method="POST",
                path=TOOL_EXECUTE_PATH,
                content_type="application/json",
                body=_execute_payload(
                    "tool:google:gmail.search_messages@1", {"query": "seam"}
                ),
            )
        )
        assert response.status_code == 503
        assert response.body["error"]["code"] == "tool_runtime_unavailable"
    finally:
        _restore(saved)
