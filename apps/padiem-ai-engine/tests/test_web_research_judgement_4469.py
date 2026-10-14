"""#4469: the Engine judges whether a conversation needs public web evidence.

The judgement is one model call with zero retrieval and zero answer, on the Router-owned
fixed chain, so the caller's selected answer model stays untouched and nothing private is
allowed to be promoted into a public search query.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from padiem_ai_core import GroundedResearchRuntime, MockWebProvider
from app.web_research_service import WebResearchEngineService


class NoProvider:
    """Any retrieval during judgement is a contract violation."""

    async def search(self, query, limit=5):
        raise AssertionError("search judgement must never retrieve")

    async def fetch(self, url):
        raise AssertionError("search judgement must never fetch")


class JudgeRuntime:
    def __init__(self, answer):
        self.answer = answer
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        return SimpleNamespace(answer=self.answer, usage=SimpleNamespace(), status="completed")


def request(operation="search_judgement", query="그럼 올해도 신청할 수 있어?", **overrides):
    payload = {
        "app_id": "padiem-claw",
        "operation": operation,
        "query": query,
        "agent": {
            "id": "claw-answer-agent",
            "title": "Claw answer agent",
            "description": "Answers with the user's selected model.",
            "system_instruction": "Answer the user.",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 480,
            "model_policy": {"model": "vendor/selected-route"},
        },
    }
    payload.update(overrides)
    return payload


def service(answer, *, provider=None):
    runtime = JudgeRuntime(answer)
    return (
        WebResearchEngineService(
            research_runtime_factory=lambda _app_id: _ResearchRuntime(provider or NoProvider()),
            execution_runtime_factory=lambda _app_id: runtime,
            b14_service_bound=True,
        ),
        runtime,
    )


class _ResearchRuntime:
    """Only the evidence/search paths would use this; judgement must not."""

    def __init__(self, provider):
        self._provider = provider

    async def prepare_search(self, query, **kwargs):
        raise AssertionError("judgement must not prepare grounding")


def verdict(needs_search, query=None, reason="fresh_public_fact"):
    return json.dumps({"needs_search": needs_search, "query": query, "reason": reason})


# --- one model call, no retrieval, no answer ---------------------------------


def test_judgement_runs_one_model_call_and_never_retrieves():
    answer = verdict(True, "2026 광주 청년창업 지원사업 신청기간 모집 공고")
    engine, runtime = service(answer)
    result = asyncio.run(engine.research_payload(request()))
    assert result.status_code == 200
    body = result.body
    assert body["ok"] is True
    assert body["operation"] == "search_judgement"
    assert body["needs_search"] is True
    assert body["query"] == "2026 광주 청년창업 지원사업 신청기간 모집 공고"
    assert body["answer"] is None
    assert body["sources"] == []
    assert len(runtime.requests) == 1, "judgement must not answer as well"


def test_judgement_uses_the_engine_owned_profile_on_the_fixed_chain():
    engine, runtime = service(verdict(False, None, "stable_knowledge"))
    asyncio.run(engine.research_payload(request()))
    agent = runtime.requests[0].agent
    assert agent.id == "engine-search-judgement"
    assert agent.model_policy["model"] == "b14/auto"
    assert agent.allowed_tools == ()
    assert agent.max_steps == 1
    assert "vendor/selected-route" not in str(agent.model_policy), "the caller's answer route must not be reused"


# --- the three outcomes the product needs -----------------------------------


def test_no_search_verdict_is_reported_without_invention():
    engine, _ = service(verdict(False, None, "user_supplied_text"))
    body = asyncio.run(engine.research_payload(request())).body
    assert body["needs_search"] is False
    assert body["query"] is None
    assert body["reason"] == "user_supplied_text"


def test_clarify_context_is_distinguishable_from_no_search():
    engine, _ = service(verdict(False, None, "clarify_context"))
    body = asyncio.run(engine.research_payload(request(query="그럼 올해도 신청할 수 있어?"))).body
    assert body["needs_search"] is False
    assert body["reason"] == "clarify_context"


# --- unparseable or unsafe model output fails closed -------------------------


@pytest.mark.parametrize("answer", [
    "I would probably search for that",
    "{not json at all",
    json.dumps({"needs_search": True}),
    json.dumps({"needs_search": "yes", "query": "공고"}),
    json.dumps({"needs_search": True, "query": " "}),
    "",
])
def test_unusable_model_output_never_becomes_a_search(answer):
    engine, _ = service(answer)
    body = asyncio.run(engine.research_payload(request())).body
    assert body["needs_search"] is False
    assert body["query"] is None


def test_a_fenced_json_answer_is_still_parsed():
    answer = "```json\n" + verdict(True, "2026 기준금리") + "\n```"
    engine, _ = service(answer)
    body = asyncio.run(engine.research_payload(request())).body
    assert body["needs_search"] is True
    assert body["query"] == "2026 기준금리"


@pytest.mark.parametrize("private", [
    "고객 홍길동 견적 단가",
    "kim@company.co.kr 정책 현황",
    "고객 010-1234-5678 문의 현황",
    "attached quote.xlsx 가격",
    "bearer abcdef 토큰 정책",
])
def test_a_private_proposed_query_is_never_approved(private):
    engine, _ = service(verdict(True, private))
    body = asyncio.run(engine.research_payload(request())).body
    assert body["needs_search"] is False, "the model may propose, never authorise egress"
    assert body["query"] is None


def test_judgement_query_is_bounded_even_when_the_model_is_verbose():
    engine, _ = service(verdict(True, "최신 정책 " * 300))
    body = asyncio.run(engine.research_payload(request())).body
    assert body["needs_search"] is True
    assert len(body["query"]) <= 200


# --- the same privacy and authority boundaries as the evidence path ---------


def test_judgement_refuses_injected_system_context():
    engine, _ = service(verdict(True, "2026 공고"))
    result = asyncio.run(engine.research_payload(
        request(additional_system_context="PRIVATE CUSTOMER DATA")
    ))
    assert result.status_code == 400
    assert result.body["error"]["code"] == "invalid_research_request"


def test_judgement_requires_the_reviewed_operation_name():
    engine, _ = service(verdict(True, "2026 공고"))
    result = asyncio.run(engine.research_payload(request(operation="search_judgement_and_answer")))
    assert result.status_code == 400
    assert result.body["error"]["code"] == "invalid_research_operation"


def test_evidence_path_still_makes_no_model_call_after_judgement_was_added():
    runtime = JudgeRuntime("unused")
    engine = WebResearchEngineService(
        research_runtime_factory=lambda _app_id: GroundedResearchRuntime(MockWebProvider()),
        execution_runtime_factory=lambda _app_id: runtime,
        b14_service_bound=True,
    )
    payload = request(operation="search_evidence", query="2026 광주 청년창업 지원사업")
    result = asyncio.run(engine.research_payload(payload))
    assert result.status_code == 200
    assert result.body["answer"] is None
    assert runtime.requests == [], "evidence-only must still construct no model call"
