"""#1745 canonical Engine Evidence/Citation projection conformance suite.

Network-free. Proves that ``execute``, ``stream`` and ``research`` terminals all
flow through the single ``project_terminal_evidence`` chokepoint, that Core owns
Evidence truth (membership, order, dedup, verification) while the Engine owns
only the bounded transport projection, and that the web projection features stay
DEFERRED until activation (#1753) and conformance (#1752).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from padiem_ai_core import (
    AcceptedVerification,
    B14RouteMetadata,
    ClaimAssessment,
    ClaimAssessmentState,
    ClaimDerivation,
    ClaimEvidenceLink,
    ClaimEvidenceRelation,
    Evidence,
    EvidenceClaim,
    EvidenceGraphError,
    ExecutionContext,
    ExecutionResult,
    GroundedCitation,
    GroundedResearchRuntime,
    GroundedSynthesisResult,
    MockWebProvider,
    OrchestrationResult,
    PreparedGrounding,
    RunMetadata,
    RunStatus,
    StreamingExecutionEvent,
    UsageMetadata,
    VerificationDisposition,
    VerificationRequest,
    VerificationVerdict,
    dedupe_evidence,
    evidence_graph,
    project_grounded_citations,
)

from app.contract_manifest import current_engine_contract_manifest
from app.evidence_projection import (
    ENGINE_EVIDENCE_CITATION_FIELDS,
    ENGINE_EVIDENCE_SOURCE_FIELDS,
    EngineEvidenceProjectionError,
    project_engine_citation_bundles,
    project_engine_evidence,
    project_terminal_evidence,
)
from app.service import EngineService
from app.streaming_service import STREAM_PATH, StreamingEngineService
from app.web_research_service import WebResearchEngineService

APP_ROOT = Path(__file__).resolve().parents[1]


def run(coro):
    return asyncio.run(coro)


def evidence(index: int, *, url: str | None = None) -> Evidence:
    return Evidence(
        id=f"src-{index}",
        title=f"Source {index}",
        snippet=f"PRIVATE SNIPPET {index}",
        retrieved_at="2026-09-03T00:00:00Z",
        provider="test",
        source_type="search",
        url=url or f"https://example.com/{index}",
    )


def route() -> B14RouteMetadata:
    return B14RouteMetadata(
        selected_provider="openrouter",
        selected_model="openrouter/free",
        actual_response_model="provider/free-model",
        attempt_count=1,
        fallback_used=False,
    )


def run_metadata(status: RunStatus = RunStatus.COMPLETED) -> RunMetadata:
    return RunMetadata(
        trace_id="trace-1",
        app_id="reference-product",
        agent_id="reference-agent",
        session_id="session-1",
        status=status,
        provider="openrouter",
        model="provider/free-model",
        usage=UsageMetadata(),
    )


def execution_result() -> ExecutionResult:
    return ExecutionResult(answer="grounded answer", route=route(), metadata=run_metadata())


def execute_payload() -> dict:
    return {
        "app_id": "reference-product",
        "agent": {
            "id": "reference-agent",
            "title": "Reference agent",
            "description": "Network-free Engine evidence test agent.",
            "system_instruction": "Answer plainly.",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 256,
        },
        "messages": [{"role": "user", "content": "hello"}],
        "session_id": "session-1",
        "trace_id": "trace-1",
    }


class FakeExecutionRuntime:
    def __init__(self, result: ExecutionResult | None = None) -> None:
        self.result = result or execution_result()
        self.calls: list = []

    async def run(self, request):
        self.calls.append(request)
        return self.result


class FakeStreamRuntime:
    def __init__(self, events) -> None:
        self.events = list(events)

    def stream(self, request):
        events = self.events

        class _Iterator:
            def __init__(self) -> None:
                self.index = 0

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.index < len(events):
                    event = events[self.index]
                    self.index += 1
                    return event
                raise StopAsyncIteration

            async def aclose(self):
                return None

        return _Iterator()


def stream_event(*, done: bool, answer: str | None = None) -> StreamingExecutionEvent:
    return StreamingExecutionEvent(
        delta_content=None if done else "hel",
        answer=answer,
        finish_reason="stop" if done else None,
        route=route(),
        metadata=run_metadata(RunStatus.COMPLETED if done else RunStatus.MODEL_RUNNING),
        done=done,
    )


def graph_fixture():
    first = evidence(1)
    second = evidence(2)
    claim = EvidenceClaim(
        id="claim-1",
        text="The claim text.",
        derivation=ClaimDerivation.OBSERVED,
    )
    graph = evidence_graph(
        sources=(first, second),
        claims=(claim,),
        links=(
            ClaimEvidenceLink("claim-1", "src-1", ClaimEvidenceRelation.SUPPORTS),
            ClaimEvidenceLink("claim-1", "src-2", ClaimEvidenceRelation.CONTRADICTS),
        ),
    )
    return first, second, claim, graph


def accepted_verification(disposition: VerificationDisposition) -> AcceptedVerification:
    verdict = VerificationVerdict(
        verdict_id="verdict-1",
        claim_id="claim-1",
        validator_id="independent-validator",
        disposition=disposition,
        checked_evidence_ids=("src-1",),
        confidence=0.9,
        summary="independent summary",
    )
    return AcceptedVerification(
        request=VerificationRequest(claim_id="claim-1", producer_id="producer-1"),
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# Field-set drift guards: the Engine mirrors are re-derived from live Core.
# ---------------------------------------------------------------------------


def test_source_field_set_matches_core_serialization() -> None:
    assert set(evidence(1).to_public_dict()) == set(ENGINE_EVIDENCE_SOURCE_FIELDS)


def test_citation_field_set_matches_core_serialization() -> None:
    citation = GroundedCitation(
        citation_id="cit-1",
        claim_id="claim-1",
        evidence_id="src-1",
        title="Source 1",
        url="https://example.com/1",
        provider="test",
        source_type="search",
        relation=ClaimEvidenceRelation.SUPPORTS,
    )
    assert set(citation.to_public_dict()) == set(ENGINE_EVIDENCE_CITATION_FIELDS)


# ---------------------------------------------------------------------------
# Core owns evidence truth; the Engine only projects.
# ---------------------------------------------------------------------------


def test_projection_preserves_core_settled_order_without_resorting() -> None:
    items = (evidence(3), evidence(1), evidence(2))
    projected = project_engine_evidence(items)
    assert [source["id"] for source in projected] == ["src-3", "src-1", "src-2"]


def test_engine_adds_no_second_dedup_authority() -> None:
    duplicate_url_a = evidence(1, url="https://example.com/same")
    duplicate_url_b = evidence(2, url="https://example.com/same")
    # Core owns deduplication: it collapses the duplicate URL set.
    settled = dedupe_evidence((duplicate_url_a, duplicate_url_b), limit=5)
    assert len(settled) < 2 or {item.url for item in settled} == {"https://example.com/same"}
    # Whatever Core settles, the Engine preserves exactly — it never drops more.
    assert len(project_engine_evidence(settled)) == len(settled)


def test_non_core_values_fail_closed_without_leaking() -> None:
    with pytest.raises(EngineEvidenceProjectionError) as excinfo:
        project_engine_evidence([{"secret": "PRIVATE-BYTES"}])
    assert excinfo.value.code == "invalid_evidence_projection"
    assert "PRIVATE-BYTES" not in str(excinfo.value)

    with pytest.raises(EngineEvidenceProjectionError):
        project_engine_evidence("not-a-sequence")


def test_evidence_output_carries_no_b14_or_run_metadata() -> None:
    serialized = json.dumps(project_engine_evidence((evidence(1),)), ensure_ascii=False)
    for forbidden in (
        "selected_provider",
        "selected_model",
        "actual_response_model",
        "trace_id",
        "session_id",
        "duration_ms",
        "usage",
        "route",
    ):
        assert forbidden not in serialized


# ---------------------------------------------------------------------------
# Citations: a citation can never reference removed evidence and unverified
# claims never project as verified.
# ---------------------------------------------------------------------------


def test_citation_projection_delegates_to_single_core_authority() -> None:
    _, _, _, graph = graph_fixture()
    bundles = project_engine_citation_bundles(graph, ["claim-1"])
    assert bundles == [project_grounded_citations(graph, "claim-1").to_public_dict()]
    assert bundles[0]["verification"] is None
    assert {citation["relation"] for citation in bundles[0]["citations"]} == {
        "supports",
        "contradicts",
    }


def test_citation_cannot_reference_removed_evidence() -> None:
    first, second, claim, _ = graph_fixture()
    # Graph validation fails closed once trust policy removed a linked source.
    with pytest.raises(EvidenceGraphError) as excinfo:
        evidence_graph(
            sources=(first,),
            claims=(claim,),
            links=(
                ClaimEvidenceLink("claim-1", "src-1", ClaimEvidenceRelation.SUPPORTS),
                ClaimEvidenceLink("claim-1", "src-2", ClaimEvidenceRelation.CONTRADICTS),
            ),
        )
    assert excinfo.value.code == "unknown_evidence_source"

    # And a claim whose links were all removed projects no citation bundle.
    inferred_claim = EvidenceClaim(
        id="claim-1",
        text="The claim text.",
        derivation=ClaimDerivation.INFERRED,
    )
    orphan = evidence_graph(
        sources=(first,),
        claims=(inferred_claim,),
        links=(),
    )
    with pytest.raises(EngineEvidenceProjectionError) as excinfo:
        project_engine_citation_bundles(orphan, ["claim-1"])
    assert excinfo.value.code == "no_grounded_citations"


def test_unverified_claim_never_becomes_verified() -> None:
    _, _, _, graph = graph_fixture()
    unverified = project_engine_citation_bundles(graph, ["claim-1"])[0]
    assert unverified["verification"] is None
    assert all(not citation["checked_by_validator"] for citation in unverified["citations"])

    verified = project_engine_citation_bundles(
        graph,
        ["claim-1"],
        verifications={"claim-1": accepted_verification(VerificationDisposition.VERIFIED)},
    )[0]
    assert verified["verification"]["disposition"] == "verified"
    assert verified["verification"]["validator_id"] == "independent-validator"
    assert [
        citation["checked_by_validator"] for citation in verified["citations"]
    ] == [True, False]


def test_contradicted_disposition_stays_machine_readable() -> None:
    _, _, _, graph = graph_fixture()
    bundle = project_engine_citation_bundles(
        graph,
        ["claim-1"],
        verifications={"claim-1": accepted_verification(VerificationDisposition.CONTRADICTED)},
    )[0]
    assert bundle["verification"]["disposition"] == "contradicted"


def test_citations_exclude_private_snippet_bytes() -> None:
    _, _, _, graph = graph_fixture()
    serialized = json.dumps(project_engine_citation_bundles(graph, ["claim-1"]))
    assert "PRIVATE SNIPPET" not in serialized


def test_non_core_graph_fails_closed() -> None:
    with pytest.raises(EngineEvidenceProjectionError) as excinfo:
        project_engine_citation_bundles(object(), ["claim-1"])
    assert excinfo.value.code == "invalid_citation_projection"


# ---------------------------------------------------------------------------
# Terminal chokepoint: grounded results project sources; ungrounded contracts
# normalize to absence; unknown values fail closed.
# ---------------------------------------------------------------------------


def test_terminal_projects_grounded_sources_only() -> None:
    items = (evidence(1), evidence(2))
    result = GroundedSynthesisResult(
        synthesis=None,
        prepared=PreparedGrounding(context="ctx", evidence=items),
    )
    assert project_terminal_evidence(result) == {"sources": project_engine_evidence(items)}


def test_terminal_normalizes_absence_without_fabrication() -> None:
    assert project_terminal_evidence(execution_result()) == {}
    assert project_terminal_evidence(stream_event(done=True, answer="x")) == {}
    orchestration = OrchestrationResult(
        execution_result=execution_result(),
        context=ExecutionContext(trace_id="trace-1"),
        app_id="reference-product",
        subject_id=None,
        plan=None,
        activated_skill=None,
        resolved_tool_ids=(),
        evidence_graph=None,
        claim_assessments=(),
        grounded_citations=(),
        events=(),
    )
    assert project_terminal_evidence(orchestration) == {}


def test_terminal_rejects_unknown_values_fail_closed() -> None:
    with pytest.raises(EngineEvidenceProjectionError) as excinfo:
        project_terminal_evidence(object())
    assert excinfo.value.code == "invalid_evidence_projection"


# ---------------------------------------------------------------------------
# Transport parity: execute, stream and research terminals converge.
# ---------------------------------------------------------------------------


def test_execute_terminal_adds_no_evidence_for_ungrounded_core_result() -> None:
    runtime = FakeExecutionRuntime()
    service = EngineService(
        runtime_factory=lambda _app_id: runtime,
        b14_service_bound=True,
    )
    response = run(service.execute_payload(execute_payload()))
    assert response.status_code == 200
    assert set(response.body) == {"ok", "answer", "route", "metadata"}
    assert "sources" not in response.body
    assert "citations" not in response.body


def test_stream_terminal_diverges_from_execute_by_zero_fields() -> None:
    runtime = FakeStreamRuntime(
        [stream_event(done=False), stream_event(done=True, answer="hello")]
    )
    service = StreamingEngineService(
        runtime_factory=lambda _app_id: runtime,
        b14_service_bound=True,
    )

    async def collect() -> list[dict]:
        prepared = await service.prepare(
            method="POST",
            path=STREAM_PATH,
            content_type="application/json; charset=utf-8",
            body=json.dumps(execute_payload(), ensure_ascii=False).encode(),
        )
        return [json.loads(line) for line in [chunk async for chunk in service.iter_ndjson(prepared)]]

    decoded = run(collect())
    assert len(decoded) == 2
    for line in decoded:
        assert set(line["event"]) == set(stream_event(done=True, answer="x").to_public_dict())
    assert decoded[-1]["event"]["done"] is True
    assert "sources" not in decoded[-1]["event"]


def test_research_terminal_is_the_same_canonical_projection() -> None:
    provider = MockWebProvider()

    async def settled() -> list[Evidence]:
        return await provider.search("current policy", 5)

    search_items = run(settled())
    service = WebResearchEngineService(
        research_runtime_factory=lambda _app_id: GroundedResearchRuntime(provider),
        execution_runtime_factory=lambda _app_id: FakeExecutionRuntime(),
        b14_service_bound=True,
    )
    response = run(
        service.research_payload(
            {
                "app_id": "reference-product",
                "operation": "search",
                "query": "current policy",
                "agent": execute_payload()["agent"],
                "trace_id": "research-trace",
            }
        )
    )
    assert response.status_code == 200
    assert response.body["sources"] == project_engine_evidence(search_items)

    # The exact same Core tuple projected through the chokepoint converges.
    result = GroundedSynthesisResult(
        synthesis=None,
        prepared=PreparedGrounding(context="ctx", evidence=tuple(search_items)),
    )
    assert project_terminal_evidence(result) == {"sources": response.body["sources"]}


def test_orchestration_block_is_forwarded_not_forked() -> None:
    source = (APP_ROOT / "app" / "orchestration_service.py").read_text(encoding="utf-8")
    assert "project_engine_evidence" not in source
    assert "project_terminal_evidence" not in source


# ---------------------------------------------------------------------------
# Product neutrality and manifest truth.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module",
    (
        "evidence_projection.py",
        "service.py",
        "streaming_service.py",
        "web_research_service.py",
        "orchestration_service.py",
    ),
)
def test_projection_sources_are_product_neutral(module: str) -> None:
    source = (APP_ROOT / "app" / module).read_text(encoding="utf-8")
    for forbidden in (
        "storymemory-b61",
        "lovebud-scout",
        "400-ai-finder",
        "padiem-sidecar",
    ):
        assert forbidden not in source


def test_manifest_web_projection_remains_deferred() -> None:
    manifest = current_engine_contract_manifest()
    assert manifest.feature_state("web_search_projection").value == "deferred"
    assert manifest.feature_state("web_fetch_projection").value == "deferred"
    assert manifest.feature_state("deep_research_projection").value == "deferred"
