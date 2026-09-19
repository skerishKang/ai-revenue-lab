"""Worker-runtime composition tests for the Claw P01/Engine adapter (#2229).

These exercise the trusted-binding composition path with plain env objects only.
They deliberately never monkeypatch ``os.environ``: the deployed Python Worker
has no process environment carrying ``P01_ENGINE_*`` values, so any test that
needed setenv to pass would prove the dead path still exists.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from padiem_ai_core.b14_execution import B14RouteMetadata
from padiem_ai_core.contracts import RunMetadata, RunStatus
from padiem_ai_core.execution_context import ExecutionContext
from padiem_ai_core.execution_runtime import ExecutionResult
from padiem_ai_core.orchestration import OrchestrationResult
from padiem_ai_core.orchestration_events import (
    OrchestrationEventKind,
    public_orchestration_event,
)
from padiem_control_plane.product_tier_routes import ProductTierLabel

from app.claw_p01_composition import (
    build_claw_p01_adapter,
    build_claw_p01_adapter_with_diagnostic,
)
from app.worker_config import (
    P01_DIAG_CALLER_ID_SHAPE_INVALID,
    P01_DIAG_CLIENT_CONSTRUCTOR_ERROR,
    P01_DIAG_COMPOSITION_UNAVAILABLE,
    P01_DIAG_CREDENTIAL_LENGTH_INVALID,
    P01_DIAG_ENGINE_SERVICE_MISSING,
    P01_COMPOSITION_DIAGNOSTICS,
    P01_ENGINE_SERVICE_BINDING_NAME,
    p01_engine_binding_diagnostic,
    p01_engine_config_from_worker_bindings,
)
from kagent.contracts import ClawTaskIntent, ExecutionMode
from kagent.p01_adapter import P01_AGENT_ID, P01_APP_ID, P01CoreOrchestrationAdapter
from kagent.runs import ClawRun

VALID_CALLER = "b54-p01-overlay-20260914-a1"
VALID_CREDENTIAL = "c" * 48


def _env(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        P01_ENGINE_SERVICE_BINDING_NAME: SimpleNamespace(name="engine-service"),
        "P01_ENGINE_CALLER_ID": VALID_CALLER,
        "P01_ENGINE_CREDENTIAL": VALID_CREDENTIAL,
    }
    values.update(overrides)
    return values


def _request_factory(url: str, **kwargs: object) -> object:  # pragma: no cover - never called
    raise AssertionError("composition must not perform network transport")


def test_full_binding_surface_composes_the_existing_p01_adapter() -> None:
    env = _env()
    binding = env[P01_ENGINE_SERVICE_BINDING_NAME]
    adapter = build_claw_p01_adapter(env, request_factory=_request_factory)

    assert isinstance(adapter, P01CoreOrchestrationAdapter)
    runner = adapter._runner
    client = runner._client
    assert client.app_id == P01_APP_ID
    assert client.caller_id == VALID_CALLER
    assert client._transport._binding is binding




class _FakeWorkerRequest:
    created: list["_FakeWorkerRequest"] = []

    def __init__(self, url: str, **options: object) -> None:
        self.url = url
        self.options = options
        self.js_object = self
        self.__class__.created.append(self)


class _FakeEngineResponse:
    def __init__(self, body: str) -> None:
        self.status = 200
        self.headers = {"content-type": "application/json"}
        self._body = body

    async def text(self) -> str:
        return self._body


class _FakeEngineServiceBinding:
    def __init__(self) -> None:
        self.calls: list[_FakeWorkerRequest] = []

    async def fetch(self, request: _FakeWorkerRequest) -> _FakeEngineResponse:
        self.calls.append(request)
        payload = json.loads(str(request.options["body"]))
        execution_context = payload["execution_context"]
        context = ExecutionContext(
            trace_id=execution_context["trace_id"],
            timeout_seconds=execution_context["timeout_seconds"],
        )
        events = tuple(
            public_orchestration_event(
                event_id=f"evt_{sequence:03d}",
                run_id="orch_prod_composition_001",
                trace_id=context.trace_id,
                app_id=payload["app_id"],
                kind=kind,
                sequence=sequence,
                message=None,
                timestamp_iso="2026-09-17T00:00:00+00:00",
            )
            for sequence, kind in enumerate(
                (
                    OrchestrationEventKind.RUN_STARTED,
                    OrchestrationEventKind.CONTEXT_PREPARED,
                    OrchestrationEventKind.RUN_COMPLETED,
                ),
                start=1,
            )
        )
        result = OrchestrationResult(
            execution_result=ExecutionResult(
                answer="production composition seam pass",
                route=B14RouteMetadata(),
                metadata=RunMetadata(
                    trace_id=context.trace_id,
                    app_id=payload["app_id"],
                    agent_id=payload["agent"]["id"],
                    session_id=payload.get("session_id"),
                    status=RunStatus.COMPLETED,
                ),
            ),
            context=context,
            app_id=payload["app_id"],
            subject_id=None,
            plan=None,
            activated_skill=None,
            resolved_tool_ids=(),
            evidence_graph=None,
            claim_assessments=(),
            grounded_citations=(),
            events=events,
        )
        return _FakeEngineResponse(
            json.dumps(
                {"ok": True, "orchestration": result.to_public_dict()},
                ensure_ascii=False,
            )
        )


def test_plus_production_composition_reaches_engine_service_binding_once() -> None:
    """Regression for #2617's pre-Engine boundary using the real production composition stack."""
    binding = _FakeEngineServiceBinding()
    env = _env(**{P01_ENGINE_SERVICE_BINDING_NAME: binding})
    _FakeWorkerRequest.created.clear()
    adapter = build_claw_p01_adapter(env, request_factory=_FakeWorkerRequest)
    assert isinstance(adapter, P01CoreOrchestrationAdapter)

    run = ClawRun.create(
        "run_prod_composition",
        ClawTaskIntent(
            task_id="task_prod_composition",
            task="견적서 초안을 작성하세요.",
            repository_ref="skerishKang/example",
            execution_mode=ExecutionMode.LOCAL,
        ),
    )
    outcome = asyncio.run(adapter.execute(run, product_tier=ProductTierLabel.PLUS))

    assert outcome.answer == "production composition seam pass"
    assert len(binding.calls) == 1
    assert len(_FakeWorkerRequest.created) == 1

    request = binding.calls[0]
    assert request.url == "https://padiem-ai-engine.internal/internal/v1/orchestrate"
    assert request.options["method"] == "POST"
    headers = request.options["headers"]
    assert headers["X-Padiem-Engine-Caller"] == VALID_CALLER
    assert headers["X-Padiem-Engine-Credential"] == VALID_CREDENTIAL

    payload = json.loads(str(request.options["body"]))
    assert payload["app_id"] == P01_APP_ID
    assert payload["agent"]["id"] == P01_AGENT_ID
    assert payload["agent"]["model_policy"] == {
        "model": "agnes-ai/agnes-3.0-flash"
    }
    assert payload["agent"]["task_type"] == "coding"
    assert payload["agent"]["required_capabilities"] == []
    assert payload["agent"]["max_tokens"] is None
    assert payload["execution_context"]["timeout_seconds"] == 20.0
    serialized = json.dumps(payload, ensure_ascii=False)
    assert VALID_CREDENTIAL not in serialized
    assert "provider" not in payload["agent"]


def test_binding_env_may_be_an_object_with_attributes() -> None:
    env = SimpleNamespace(
        **{
            P01_ENGINE_SERVICE_BINDING_NAME: SimpleNamespace(name="engine-service"),
            "P01_ENGINE_CALLER_ID": VALID_CALLER,
            "P01_ENGINE_CREDENTIAL": VALID_CREDENTIAL,
        }
    )
    assert build_claw_p01_adapter(env, request_factory=_request_factory) is not None


def test_empty_worker_env_fails_closed_without_any_transport() -> None:
    assert build_claw_p01_adapter({}, request_factory=_request_factory) is None
    assert p01_engine_config_from_worker_bindings({}) is None


def test_vars_without_engine_service_binding_fail_closed() -> None:
    env = {
        "P01_ENGINE_CALLER_ID": VALID_CALLER,
        "P01_ENGINE_CREDENTIAL": VALID_CREDENTIAL,
    }
    assert p01_engine_config_from_worker_bindings(env) is None
    assert build_claw_p01_adapter(env, request_factory=_request_factory) is None


def test_service_binding_without_caller_or_credential_fails_closed() -> None:
    assert p01_engine_config_from_worker_bindings(
        _env(**{"P01_ENGINE_CALLER_ID": None})
    ) is None
    assert p01_engine_config_from_worker_bindings(
        _env(**{"P01_ENGINE_CREDENTIAL": None})
    ) is None
    assert p01_engine_config_from_worker_bindings(
        _env(**{"P01_ENGINE_CALLER_ID": "   "})
    ) is None


def test_malformed_caller_identity_fails_closed() -> None:
    for bad in ("attacker/id;rm", "x" * 65, "lead space", "tab\tcaller", "!!!"):
        assert p01_engine_config_from_worker_bindings(
            _env(**{"P01_ENGINE_CALLER_ID": bad})
        ) is None, bad


def test_non_string_or_out_of_bounds_credential_fails_closed() -> None:
    assert p01_engine_config_from_worker_bindings(
        _env(**{"P01_ENGINE_CREDENTIAL": 12345})
    ) is None
    assert p01_engine_config_from_worker_bindings(
        _env(**{"P01_ENGINE_CREDENTIAL": "short" * 4})
    ) is None
    assert p01_engine_config_from_worker_bindings(
        _env(**{"P01_ENGINE_CREDENTIAL": "d" * 513})
    ) is None


def test_unusable_request_factory_fails_closed_before_transport() -> None:
    assert build_claw_p01_adapter(_env(), request_factory=None) is None


# ── #2413 bounded composition diagnostics ──────────────────────────────────


def test_missing_engine_service_binding_is_classified() -> None:
    adapter, diagnostic = build_claw_p01_adapter_with_diagnostic(
        {}, request_factory=_request_factory
    )
    assert adapter is None
    assert diagnostic == P01_DIAG_ENGINE_SERVICE_MISSING
    assert p01_engine_binding_diagnostic({}) == P01_DIAG_ENGINE_SERVICE_MISSING
    env = _env(**{P01_ENGINE_SERVICE_BINDING_NAME: None})
    assert p01_engine_binding_diagnostic(env) == P01_DIAG_ENGINE_SERVICE_MISSING


def test_malformed_caller_id_is_classified() -> None:
    for bad in ("attacker/id;rm", "x" * 65, "   ", None, 12345):
        env = _env(**{"P01_ENGINE_CALLER_ID": bad})
        adapter, diagnostic = build_claw_p01_adapter_with_diagnostic(
            env, request_factory=_request_factory
        )
        assert adapter is None, bad
        assert diagnostic == P01_DIAG_CALLER_ID_SHAPE_INVALID, bad


def test_out_of_bounds_credential_length_is_classified() -> None:
    for bad in ("short" * 4, "d" * 513, None, 999999):
        env = _env(**{"P01_ENGINE_CREDENTIAL": bad})
        adapter, diagnostic = build_claw_p01_adapter_with_diagnostic(
            env, request_factory=_request_factory
        )
        assert adapter is None, repr(bad)
        assert diagnostic == P01_DIAG_CREDENTIAL_LENGTH_INVALID, repr(bad)


def test_valid_bindings_compose_adapter_with_no_diagnostic() -> None:
    adapter, diagnostic = build_claw_p01_adapter_with_diagnostic(
        _env(), request_factory=_request_factory
    )
    assert isinstance(adapter, P01CoreOrchestrationAdapter)
    assert diagnostic is None


def test_constructor_value_error_is_classified_as_client_constructor_error() -> None:
    adapter, diagnostic = build_claw_p01_adapter_with_diagnostic(
        _env(), request_factory=None
    )
    assert adapter is None
    assert diagnostic == P01_DIAG_CLIENT_CONSTRUCTOR_ERROR


def test_unexpected_constructor_failure_is_classified_as_composition_unavailable(
    monkeypatch,
) -> None:
    import app.claw_p01_composition as composition

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError(f"secret-ish failure text {VALID_CREDENTIAL}")

    monkeypatch.setattr(composition, "PadiemAiEngineClient", _boom)
    adapter, diagnostic = build_claw_p01_adapter_with_diagnostic(
        _env(), request_factory=_request_factory
    )
    assert adapter is None
    assert diagnostic == P01_DIAG_COMPOSITION_UNAVAILABLE
    assert VALID_CREDENTIAL not in str(diagnostic)


def test_diagnostics_are_bounded_allowlist_and_never_carry_the_credential() -> None:
    for env in (
        {},
        _env(**{P01_ENGINE_SERVICE_BINDING_NAME: None}),
        _env(**{"P01_ENGINE_CALLER_ID": "bad/id"}),
        _env(**{"P01_ENGINE_CREDENTIAL": "short"}),
        _env(**{"P01_ENGINE_CREDENTIAL": "d" * 513}),
    ):
        _, diagnostic = build_claw_p01_adapter_with_diagnostic(
            env, request_factory=_request_factory
        )
        assert diagnostic in P01_COMPOSITION_DIAGNOSTICS
        assert VALID_CREDENTIAL not in diagnostic
        assert VALID_CALLER not in diagnostic
        assert not any(ch.isdigit() for ch in diagnostic)


def test_success_path_plain_builder_is_unchanged() -> None:
    assert build_claw_p01_adapter(_env(), request_factory=_request_factory) is not None


def test_config_repr_and_error_paths_never_carry_the_credential() -> None:
    config = p01_engine_config_from_worker_bindings(_env())
    assert config is not None
    assert VALID_CREDENTIAL not in repr(config)
    assert VALID_CREDENTIAL not in str(config)
    adapter = build_claw_p01_adapter(_env(), request_factory=_request_factory)
    assert VALID_CREDENTIAL not in repr(adapter)


def test_composition_modules_never_read_os_environ() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in ("app/claw_p01_composition.py", "app/worker_config.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert "import os" not in source
        assert "os.environ[" not in source
        assert "os.environ.get" not in source
