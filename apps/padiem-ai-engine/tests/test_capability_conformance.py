"""E8 capability manifest conformance suite (#1752).

The Engine exposes one truthful, versioned capability manifest that every
first-party product integration (B30, B53, B54, B61, B62, LoveBud Scout and any
future consumer) can require before routing work to the Engine.  This suite
keeps that manifest honest by cross-checking every declaration against the
*routed* service truth:

* ``AVAILABLE`` capabilities are actually served end-to-end by the same service
  composition ``worker.py`` dispatches to, with the B14 binding present.
* ``DEFERRED`` capabilities are reached through a real source seam that fails
  closed (503) when the trusted authority is not wired -- the exact Production
  posture before activation.
* ``UNAVAILABLE`` capabilities offer no route at all.

The suite is product-neutral: it carries a synthetic fixture identity, imports
no product package, and scans its own sources (and the manifest source) for
product tokens.  It never imports ``worker.py``/``worker_identity.py``
composition roots (no pydoit worker dependency), never inspects provider
inventory, and never makes a network call.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from padiem_ai_core import (
    B14RouteMetadata,
    Evidence,
    ExecutionResult,
    GroundedSynthesisResult,
    PreparedGrounding,
    RunMetadata,
    RunStatus,
    StreamingExecutionEvent,
)

from app.agent_skill_service import (
    AGENT_SKILL_CANCEL_PATH,
    AGENT_SKILL_RESUME_PATH,
    AGENT_SKILL_RUN_PATH,
    AgentSkillEngineService,
)
from app.capability_manifest import (
    CAPABILITY_MAJOR,
    CAPABILITY_VERSION,
    REQUIRED_CAPABILITY_IDS,
    CapabilityManifestError,
    CapabilityState,
    current_capability_manifest,
    require_compatible_capability,
)
from app.contract_manifest import current_engine_contract_manifest
from app.document_context_service import (
    DOCUMENT_CONTEXT_PATH,
    DocumentContextEngineService,
)
from app.evidence_projection import project_engine_evidence, project_terminal_evidence
from app.memory_service import (
    MEMORY_PATH,
    MEMORY_WRITE_PATH,
    MemoryRetrievalEngineService,
)
from app.multimodal_attachment_service import (
    MULTIMODAL_EXECUTE_PATH,
    MultimodalAttachmentEngineService,
)
from app.orchestration_service import (
    ORCHESTRATE_CANCEL_PATH,
    ORCHESTRATE_PATH,
    ORCHESTRATE_RESUME_PATH,
    ORCHESTRATION_STREAM_PATH,
    OrchestrationEngineService,
)
from app.service import EXECUTE_PATH, EngineService, ServiceResponse
from app.streaming_service import (
    STREAM_PATH,
    PreparedStream,
    StreamingEngineService,
)
from app.tool_execution_service import ToolExecutionEngineService
from app.tool_projection import (
    TOOL_CANCEL_PATH,
    TOOL_EXECUTE_PATH,
    TOOL_RESUME_PATH,
)
from app.web_research_service import RESEARCH_PATH, WebResearchEngineService

APP_ROOT = Path(__file__).resolve().parents[1]

# Synthetic fixture identity: no real product is named anywhere in this suite.
APP_ID = "engine-fixture-app"
AGENT_ID = "agent:padiem:fixture"
ATTACHMENT_REF = "att_" + "e5a" * 5 + "01"

# Canonical versioned identities required by the bounded tool contract.
TOOL_AGENT_ID = "agent:engine:fixture@1"
TOOL_ID = "tool:engine:search@1"

# Concatenated so the joined product tokens never appear verbatim in this
# suite's own source (the product-neutrality scan reads this file).
FORBIDDEN_PRODUCT_TOKENS = (
    "story" + "memory-b61",
    "lovebud-" + "scout",
    "400-ai-" + "finder",
    "padiem-" + "sidecar",
)


# --- shared fixtures --------------------------------------------------------


def _route() -> B14RouteMetadata:
    return B14RouteMetadata(
        selected_provider="fixture-provider",
        selected_model="fixture-model",
    )


def _execution_result(answer: str = "conformance answer") -> ExecutionResult:
    return ExecutionResult(
        answer=answer,
        route=_route(),
        metadata=RunMetadata(
            trace_id="tr_conformance",
            app_id=APP_ID,
            agent_id=AGENT_ID,
            status=RunStatus.COMPLETED,
        ),
    )


def _evidence(index: int) -> Evidence:
    return Evidence(
        id=f"src-{index}",
        title=f"Source {index}",
        snippet=f"PRIVATE SNIPPET {index}",
        retrieved_at="2026-09-03T00:00:00Z",
        provider="fixture",
        source_type="search",
        url=f"https://example.com/{index}",
    )


def _agent() -> dict[str, object]:
    return {
        "id": AGENT_ID,
        "title": "Conformance fixture agent",
        "description": "Network-free E8 capability conformance agent.",
        "system_instruction": "Answer plainly.",
        "task_type": "general",
        "optimize_for": "balanced",
        "max_tokens": 256,
        "model_policy": {
            "model": "b14/auto",
            "allow_external_fallback": False,
            "max_attempts": 1,
        },
    }


def _execute_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "app_id": APP_ID,
        "agent": _agent(),
        "messages": [{"role": "user", "content": "hello"}],
        "trace_id": "tr_conformance",
    }
    payload.update(overrides)
    return payload


class _UnreachableRuntimeFactory:
    def __call__(self, app_id: str) -> object:
        raise AssertionError(
            f"runtime factory must not be called in a fail-closed seam (app_id={app_id})"
        )


class _FixtureRunRuntime:
    def __init__(self, result: ExecutionResult | None = None) -> None:
        self.result = result or _execution_result()
        self.calls: list[object] = []

    async def run(self, request: object) -> ExecutionResult:
        self.calls.append(request)
        return self.result


class _FixtureStreamRuntime:
    def __init__(self, events: list[StreamingExecutionEvent]) -> None:
        self.events = list(events)
        self.calls: list[object] = []

    def stream(self, request: object):
        self.calls.append(request)

        async def generate():
            for event in self.events:
                yield event

        return generate()


def _stream_progress() -> StreamingExecutionEvent:
    return StreamingExecutionEvent(
        delta_content="반가",
        answer=None,
        finish_reason=None,
        route=_route(),
        metadata=RunMetadata(
            trace_id="tr_conformance",
            app_id=APP_ID,
            agent_id=AGENT_ID,
            session_id="session-conformance",
            status=RunStatus.MODEL_RUNNING,
        ),
        done=False,
    )


def _stream_terminal() -> StreamingExecutionEvent:
    return StreamingExecutionEvent(
        delta_content=None,
        answer="반가워요.",
        finish_reason="stop",
        route=_route(),
        metadata=RunMetadata(
            trace_id="tr_conformance",
            app_id=APP_ID,
            agent_id=AGENT_ID,
            session_id="session-conformance",
            status=RunStatus.COMPLETED,
        ),
        done=True,
    )


def _error_code(response: ServiceResponse) -> str:
    return response.body["error"]["code"]


# --- manifest identity and coverage -----------------------------------------


def test_manifest_identity_is_pinned() -> None:
    manifest = current_capability_manifest()
    assert manifest.family == "padiem-ai-engine"
    assert manifest.major == CAPABILITY_MAJOR == 1
    assert manifest.version == CAPABILITY_VERSION == "1.0"


def test_manifest_declares_required_set_plus_unavailable_pair() -> None:
    manifest = current_capability_manifest()
    ids = {declaration.id for declaration in manifest.capabilities}
    assert REQUIRED_CAPABILITY_IDS.issubset(ids)
    assert len(ids) == 17
    assert {"public_browser_api", "provider_selection"}.issubset(ids)


def test_capability_states_match_routed_truth() -> None:
    manifest = current_capability_manifest()
    state_of = {
        declaration.id: declaration.state for declaration in manifest.capabilities
    }
    for capability_id in (
        "completed_execution",
        "streaming_execution",
        "orchestration",
        "multi_caller_identity",
        "evidence_citations",
    ):
        assert state_of[capability_id] is CapabilityState.AVAILABLE
    for capability_id in (
        "continuation/approval",
        "memory_rag",
        "agent_skill_runtime",
        "file_document_multimodal",
        "tenant_entitlement_usage_admission",
        "idempotency",
        # E9 A3: reverted to DEFERRED per CTO audit 2026-09-06 — the Production
        # composition injects no tool binding resolver, so the AVAILABLE claim
        # was not production truth (WO-2 gate must pass before re-activation).
        "tool_runtime",
        # E9 A1: reverted to DEFERRED per owner decision D2 (WO-7) — wrangler.toml
        # has no [vars]/keep_vars, so the web provider var cannot survive a deploy
        # and the composition fails closed 503 web_tools_off (not production truth).
        "web_search",
        "web_fetch",
        "deep_research",
    ):
        assert state_of[capability_id] is CapabilityState.DEFERRED
    for capability_id in ("public_browser_api", "provider_selection"):
        assert state_of[capability_id] is CapabilityState.UNAVAILABLE


def test_manifest_routes_match_route_constants() -> None:
    manifest = current_capability_manifest()
    expected = {
        "completed_execution": (EXECUTE_PATH,),
        "streaming_execution": (STREAM_PATH,),
        "orchestration": (
            ORCHESTRATE_PATH,
            ORCHESTRATE_RESUME_PATH,
            ORCHESTRATE_CANCEL_PATH,
            ORCHESTRATION_STREAM_PATH,
        ),
        "continuation/approval": (ORCHESTRATE_RESUME_PATH,),
        "multi_caller_identity": (),
        "web_search": (RESEARCH_PATH,),
        "web_fetch": (RESEARCH_PATH,),
        "deep_research": (RESEARCH_PATH,),
        "evidence_citations": (EXECUTE_PATH, STREAM_PATH, RESEARCH_PATH),
        "tool_runtime": (TOOL_EXECUTE_PATH, TOOL_RESUME_PATH, TOOL_CANCEL_PATH),
        "memory_rag": (MEMORY_PATH, MEMORY_WRITE_PATH),
        "agent_skill_runtime": (
            AGENT_SKILL_RUN_PATH,
            AGENT_SKILL_RESUME_PATH,
            AGENT_SKILL_CANCEL_PATH,
        ),
        "file_document_multimodal": (MULTIMODAL_EXECUTE_PATH, DOCUMENT_CONTEXT_PATH),
        "tenant_entitlement_usage_admission": (),
        "idempotency": (ORCHESTRATE_PATH,),
        "public_browser_api": (),
        "provider_selection": (),
    }
    by_id = {
        declaration.id: declaration.routes for declaration in manifest.capabilities
    }
    assert by_id == expected


def test_declared_routes_are_internal_engine_paths() -> None:
    manifest = current_capability_manifest()
    for declaration in manifest.capabilities:
        for path in declaration.routes:
            assert path.startswith("/internal/v1/")
        assert len(set(declaration.routes)) == len(declaration.routes)


def test_declared_routes_are_wired_in_worker_dispatch() -> None:
    dispatcher_sources = "\n".join(
        (APP_ROOT / name).read_text(encoding="utf-8")
        for name in ("worker.py", "worker_identity.py")
    )
    constant_names: dict[str, list[str]] = {}
    for module in (APP_ROOT / "app").glob("*.py"):
        for match in re.finditer(
            r'^([A-Z][A-Z0-9_]*_PATH)\s*=\s*"([^"]+)"',
            module.read_text(encoding="utf-8"),
            re.MULTILINE,
        ):
            constant_names.setdefault(match.group(2), []).append(match.group(1))
    declared = {
        path
        for declaration in current_capability_manifest().capabilities
        for path in declaration.routes
    }
    for path in sorted(declared):
        names = constant_names.get(path, ())
        assert path in dispatcher_sources or any(
            name in dispatcher_sources for name in names
        )


# --- AVAILABLE capabilities are actually served ------------------------------


@pytest.mark.asyncio
async def test_available_execute_is_served_when_b14_bound() -> None:
    runtime = _FixtureRunRuntime()
    service = EngineService(
        runtime_factory=lambda _app_id: runtime,
        b14_service_bound=True,
    )

    response = await service.execute_payload(_execute_payload())

    assert response.status_code == 200
    assert response.body["ok"] is True
    assert len(runtime.calls) == 1


@pytest.mark.asyncio
async def test_execute_fails_closed_when_b14_unbound() -> None:
    service = EngineService(
        runtime_factory=_UnreachableRuntimeFactory(),
        b14_service_bound=False,
    )

    response = await service.execute_payload(_execute_payload())

    assert response.status_code == 503
    assert _error_code(response) == "b14_service_unavailable"


@pytest.mark.asyncio
async def test_streaming_served_when_bound_and_fail_closed_when_unbound() -> None:
    runtime = _FixtureStreamRuntime([_stream_progress(), _stream_terminal()])
    bound = StreamingEngineService(
        runtime_factory=lambda _app_id: runtime,
        b14_service_bound=True,
    )
    raw = json.dumps(_execute_payload(), ensure_ascii=False).encode()

    prepared = await bound.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json; charset=utf-8",
        body=raw,
    )

    assert isinstance(prepared, PreparedStream)
    lines = [line async for line in bound.iter_ndjson(prepared)]
    assert len(lines) == 2
    assert json.loads(lines[-1])["event"]["done"] is True
    assert len(runtime.calls) == 1

    unbound = StreamingEngineService(
        runtime_factory=_UnreachableRuntimeFactory(),
        b14_service_bound=False,
    )
    failed = await unbound.prepare(
        method="POST",
        path=STREAM_PATH,
        content_type="application/json; charset=utf-8",
        body=raw,
    )
    assert failed.status_code == 503
    assert _error_code(failed) == "b14_service_unavailable"


# --- DEFERRED capabilities fail closed through their real seam ----------------


@pytest.mark.asyncio
async def test_web_research_fail_closed_when_unbound() -> None:
    service = WebResearchEngineService(
        research_runtime_factory=_UnreachableRuntimeFactory(),
        execution_runtime_factory=_UnreachableRuntimeFactory(),
        b14_service_bound=False,
    )

    response = await service.research_payload(
        {
            "app_id": APP_ID,
            "operation": "search",
            "query": "conformance query",
            "agent": _agent(),
            "trace_id": "tr_conformance",
        }
    )

    assert response.status_code == 503
    assert _error_code(response) == "b14_service_unavailable"


@pytest.mark.asyncio
async def test_tool_runtime_fail_closed_without_binding() -> None:
    service = ToolExecutionEngineService(tool_binding_resolver=lambda _app_id: None)

    response = await service.execute_payload(
        {
            "app_id": APP_ID,
            "agent_id": TOOL_AGENT_ID,
            "tool_id": TOOL_ID,
            "arguments": {"query": "conformance"},
        }
    )

    assert response.status_code == 503
    assert _error_code(response) == "tool_runtime_unavailable"


@pytest.mark.asyncio
async def test_memory_rag_fail_closed_without_bindings() -> None:
    service = MemoryRetrievalEngineService(bindings={}, write_bindings={})

    retrieve = await service.handle(
        method="POST",
        path=MEMORY_PATH,
        content_type="application/json",
        body=json.dumps(
            {
                "app_id": APP_ID,
                "query": "conformance query",
                "namespaces": [{"scope": "user", "subject_id": "u-1"}],
            }
        ).encode(),
    )
    assert retrieve.status_code == 503
    assert _error_code(retrieve) == "memory_binding_unavailable"

    write = await service.handle(
        method="POST",
        path=MEMORY_WRITE_PATH,
        content_type="application/json",
        body=json.dumps(
            {
                "app_id": APP_ID,
                "memory_id": "mem-conformance",
                "namespace": {"scope": "user", "subject_id": "u-1"},
                "content": "remember this",
            }
        ).encode(),
    )
    assert write.status_code == 503
    assert _error_code(write) == "memory_write_binding_unavailable"


@pytest.mark.asyncio
async def test_agent_skill_fail_closed_without_binding_resolver() -> None:
    service = AgentSkillEngineService(
        runtime_factory=_UnreachableRuntimeFactory(),
        binding_resolver=None,
    )

    response = await service.run_payload(
        {
            "app_id": APP_ID,
            "agent_id": AGENT_ID,
            "messages": [{"role": "user", "content": "hello"}],
        }
    )

    assert response.status_code == 503
    assert _error_code(response) == "agent_skill_runtime_unavailable"


@pytest.mark.asyncio
async def test_multimodal_fail_closed_without_attachment_resolver() -> None:
    service = MultimodalAttachmentEngineService(
        runtime_factory=_UnreachableRuntimeFactory(),
        attachment_resolver=None,
    )

    response = await service.execute_payload(
        _execute_payload(
            attachment_ref=ATTACHMENT_REF, session_id="session-conformance"
        )
    )

    assert response.status_code == 503
    assert _error_code(response) == "attachment_resolver_unavailable"


@pytest.mark.asyncio
async def test_document_context_fail_closed_without_authority() -> None:
    service = DocumentContextEngineService()

    response = await service.handle(
        method="POST",
        path=DOCUMENT_CONTEXT_PATH,
        content_type="application/json",
        body=json.dumps({"document_ref": "doc-conformance"}).encode(),
        caller_id="engine-fixture-caller",
        credential="fixture-credential-value",
    )

    assert response.status_code == 503
    assert _error_code(response) == "document_authority_unavailable"


@pytest.mark.asyncio
async def test_orchestration_fail_closed_when_b14_unbound() -> None:
    service = OrchestrationEngineService(
        runtime_factory=_UnreachableRuntimeFactory(),
        b14_service_bound=False,
    )

    response = await service.orchestrate_payload(_execute_payload())

    assert response.status_code == 503
    assert _error_code(response) == "b14_service_unavailable"


@pytest.mark.asyncio
async def test_continuation_approval_fail_closed_without_explicit_store() -> None:
    service = OrchestrationEngineService(
        runtime_factory=_UnreachableRuntimeFactory(),
        b14_service_bound=True,
    )

    response = await service.resume_payload(
        {"app_id": APP_ID, "continuation_ref": "cont-conformance"}
    )

    assert response.status_code == 503
    assert _error_code(response) == "continuation_store_unavailable"


# --- evidence citations chokepoint ------------------------------------------


def test_evidence_citations_is_single_canonical_projection() -> None:
    manifest = current_capability_manifest()
    assert manifest.capability_state("evidence_citations") is CapabilityState.AVAILABLE
    assert {
        declaration.id
        for declaration in manifest.capabilities
        if "evidence" in declaration.id
    } == {"evidence_citations"}

    items = (_evidence(1), _evidence(2))
    grounded = GroundedSynthesisResult(
        synthesis=None,
        prepared=PreparedGrounding(context="ctx", evidence=items),
    )
    assert project_terminal_evidence(grounded) == {
        "sources": project_engine_evidence(items)
    }
    assert project_terminal_evidence(_execution_result()) == {}


# --- fail-closed require gates ------------------------------------------------


def test_require_available_capability_returns_declaration() -> None:
    declaration = require_compatible_capability("completed_execution")
    assert declaration.id == "completed_execution"
    assert declaration.state is CapabilityState.AVAILABLE


def test_require_deferred_capability_fails_closed() -> None:
    with pytest.raises(CapabilityManifestError) as excinfo:
        require_compatible_capability("memory_rag")
    assert excinfo.value.code == "capability_unavailable"


def test_require_unknown_capability_fails_closed() -> None:
    with pytest.raises(CapabilityManifestError) as excinfo:
        require_compatible_capability("brand_new_capability")
    assert excinfo.value.code == "unknown_capability"


def test_require_incompatible_major_fails_closed() -> None:
    with pytest.raises(CapabilityManifestError) as excinfo:
        require_compatible_capability("completed_execution", requested_major=2)
    assert excinfo.value.code == "incompatible_capability"


# --- scope matrix and alignment -----------------------------------------------


def test_scope_matrix_makes_no_widening_claim() -> None:
    manifest = current_capability_manifest()
    for declaration in manifest.capabilities:
        row = declaration.scope
        assert row.caller_identity == "bounded"
        assert row.app_scope == "bounded"
        assert row.input_bounds == "enforced"
        assert row.authority_widening == 0
        assert row.core_semantics_reused == "yes"
        assert row.error_taxonomy == "normalized"
        assert row.private_data_leakage == 0
        assert row.product_specific_engine_branch == 0


def test_manifest_pins_stream_and_orchestration_parity_claims() -> None:
    manifest = current_capability_manifest()
    by_id = {declaration.id: declaration.scope for declaration in manifest.capabilities}
    assert by_id["streaming_execution"].stream_final_parity == "pass"
    assert by_id["evidence_citations"].stream_final_parity == "pass"
    assert by_id["orchestration"].tenant_scope == "bounded"
    assert by_id["orchestration"].cancellation_timeout == "preserved"
    assert by_id["orchestration"].b14_provider_authority == "preserved"


def test_manifest_agrees_with_existing_contract_manifest() -> None:
    manifest = current_capability_manifest()
    existing = current_engine_contract_manifest()
    aligned = {
        "completed_execution": "completed_run",
        "streaming_execution": "provider_streaming_run",
        "orchestration": "orchestration_run",
        "continuation/approval": "approval_continuation",
        "web_search": "web_search_projection",
        "web_fetch": "web_fetch_projection",
        "deep_research": "deep_research_projection",
        "tool_runtime": "tool_runtime_projection",
        "file_document_multimodal": "multimodal_completed_run",
        "idempotency": "idempotency_replay",
    }
    for capability_id, feature_id in aligned.items():
        assert (
            manifest.capability_state(capability_id).value
            == existing.feature_state(feature_id).value
        )


# --- no leak, product neutrality ----------------------------------------------


def test_public_dict_leaks_no_identity_or_secrets() -> None:
    serialized = json.dumps(current_capability_manifest().to_public_dict()).lower()
    for forbidden in (
        "api_key",
        "authorization",
        "credential",
        "secret",
        "account_id",
        "token",
    ):
        assert forbidden not in serialized
    for product in FORBIDDEN_PRODUCT_TOKENS:
        assert product not in serialized


@pytest.mark.parametrize(
    "path",
    (
        "app/capability_manifest.py",
        "tests/test_capability_conformance.py",
    ),
)
def test_conformance_sources_are_product_neutral(path: str) -> None:
    source = (APP_ROOT / path).read_text(encoding="utf-8")
    for forbidden in FORBIDDEN_PRODUCT_TOKENS:
        assert forbidden not in source
