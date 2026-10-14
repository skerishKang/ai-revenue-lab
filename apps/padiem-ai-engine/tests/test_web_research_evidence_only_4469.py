"""#4469: Engine/Core evidence-only search has no B14 dispatch."""
from __future__ import annotations

import asyncio

from padiem_ai_core import Evidence, GroundedResearchRuntime, MockWebProvider
from padiem_ai_core.web_runtime import WebRuntimeError
from app.web_research_service import WebResearchEngineService


def request():
    return {
        "app_id": "padiem-claw",
        "operation": "search_evidence",
        "query": "한국은행 기준금리",
        "agent": {
            "id": "claw-evidence-fixture",
            "title": "Claw public evidence fixture",
            "description": "Public only",
            "system_instruction": "Only public evidence is allowed.",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 240,
            "model_policy": {"model": "test/route"},
        },
    }


class ModelMustNotBeConstructed:
    def __call__(self, _app_id):
        raise AssertionError("evidence-only must never construct a B14 runtime")


class Timeout:
    async def search(self, query, limit=5):
        raise WebRuntimeError("web_timeout", "timeout", 504)


def service(provider):
    return WebResearchEngineService(
        research_runtime_factory=lambda _app_id: GroundedResearchRuntime(provider),
        execution_runtime_factory=ModelMustNotBeConstructed(),
        b14_service_bound=True,
    )


def test_search_evidence_projects_core_sources_and_context_without_model():
    result = asyncio.run(service(MockWebProvider()).research_payload(request()))
    assert result.status_code == 200
    body = result.body
    assert body["ok"] is True
    assert body["operation"] == "search_evidence"
    assert body["answer"] is None
    assert body["research"] is None
    assert 0 < len(body["sources"]) <= 5
    assert "웹 근거 사용 규칙" in body["grounding_context"]
    assert all(item["url"].startswith("https://") for item in body["sources"])
    assert "route" not in body and "metadata" not in body
    assert len(body["grounding_context"]) <= 32_768


def test_no_private_system_context_in_evidence_only():
    payload = request()
    payload["additional_system_context"] = "PRIVATE CUSTOMER DATA"
    result = asyncio.run(service(MockWebProvider()).research_payload(payload))
    assert result.status_code == 400
    assert result.body["error"]["code"] == "invalid_research_request"


def test_provider_failure_cannot_make_up_sources():
    result = asyncio.run(service(Timeout()).research_payload(request()))
    assert result.status_code == 504
    assert result.body["error"]["code"] == "web_timeout"
    assert "sources" not in result.body


def test_no_evidence_does_not_report_success():
    class Empty:
        async def search(self, query, limit=5):
            return []
    result = asyncio.run(service(Empty()).research_payload(request()))
    assert result.status_code == 404
    assert result.body["error"]["code"] == "no_evidence"
    assert "sources" not in result.body


def test_extra_browser_provider_authority_denied():
    payload = request()
    payload["provider"] = "firecrawl"
    result = asyncio.run(service(MockWebProvider()).research_payload(payload))
    assert result.status_code == 400
    assert result.body["error"]["code"] == "invalid_research_request"


def test_unlisted_operation_is_refused_not_defaulted():
    payload = request()
    payload["operation"] = "search_evidence_and_answer"
    result = asyncio.run(service(MockWebProvider()).research_payload(payload))
    assert result.status_code == 400
    assert result.body["error"]["code"] == "invalid_research_operation"


def test_research_operation_allowlist_is_exactly_the_reviewed_four():
    # Dispatch falls through to deep_research for anything the allowlist admits, so
    # widening this set by one entry would silently start a model call on a route
    # that is contractually model-free. Pinning the set is the only observable guard.
    from app.web_research_service import _OPERATIONS

    assert _OPERATIONS == frozenset({"search", "fetch", "deep_research", "search_evidence"})


class OversizedEvidenceProvider:
    """Search hits far larger than the reviewed grounding budget."""

    def __init__(self):
        self._snippet = "public market data" * 1_200

    async def search(self, query, limit=5):
        return [
            Evidence(
                id=f"oversized-{index}",
                title=f"Public source {index}",
                url="https://example.org/public/" + str(index),
                snippet=self._snippet,
                retrieved_at="2000-01-01T00:00:00Z",
                provider="mock",
                source_type="search",
            )
            for index in range(1, 5)
        ]


def test_grounding_context_stays_inside_the_reviewed_bound_when_hits_are_large():
    result = asyncio.run(service(OversizedEvidenceProvider()).research_payload(request()))
    assert result.status_code == 200
    body = result.body
    assert body["answer"] is None
    assert len(body["sources"]) > 0
    assert len(body["grounding_context"]) <= 32_768
