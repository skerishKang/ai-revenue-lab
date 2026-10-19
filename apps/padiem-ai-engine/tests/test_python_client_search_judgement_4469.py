"""#4469: the P01 Engine client gains one authenticated judgement call.

One fixed private path, one bounded request, and a response that cannot be mistaken for an
answer — the client must keep refusing anything the Engine did not actually judge.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "clients" / "python"
sys.path.insert(0, str(ROOT))
from padiem_ai_engine_client import (
    ENGINE_RESEARCH_PATH,
    EngineTransportResponse,
    PadiemAiEngineClient,
    PadiemAiEngineClientError,
)

AGENT = {
    "id": "claw-public-search-judgement",
    "title": "Claw public search judgement",
    "description": "Read-only decision on whether public evidence is needed.",
    "system_instruction": "Judge public evidence need only.",
    "task_type": "general",
    "optimize_for": "balanced",
    "max_tokens": 256,
    "model_policy": {"model": "none/disabled", "max_retries": 0},
}


class Transport:
    def __init__(self, body, *, status=200):
        self.body = body
        self.status = status
        self.calls = []

    async def request(self, **request):
        self.calls.append(request)
        return EngineTransportResponse(status=self.status, body=json.dumps(self.body).encode())


def client(transport):
    return PadiemAiEngineClient(
        transport=transport,
        app_id="b54-padiem-claw",
        caller_id="padiem-claw-service",
        credential="c" * 48,
    )


def judgement_body(**overrides):
    body = {
        "ok": True,
        "operation": "search_judgement",
        "needs_search": True,
        "query": "2026 광주 청년창업 지원사업 신청기간",
        "reason": "volatile_business_fact",
        "answer": None,
        "sources": [],
    }
    body.update(overrides)
    return body


def run(coro):
    return asyncio.run(coro)


def test_uses_the_existing_authenticated_research_path_and_judgement_operation():
    transport = Transport(judgement_body())
    verdict = run(client(transport).search_judgement(conversation="user: 그럼 올해도 신청할 수 있어?", agent=AGENT))
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith(ENGINE_RESEARCH_PATH)
    sent = json.loads(call["body"].decode("utf-8"))
    assert sent["operation"] == "search_judgement"
    assert sent["app_id"] == "b54-padiem-claw"
    assert verdict["needs_search"] is True
    assert verdict["query"] == "2026 광주 청년창업 지원사업 신청기간"


def test_a_negative_verdict_carries_no_query_to_send():
    transport = Transport(judgement_body(needs_search=False, query=None, reason="stable_knowledge"))
    verdict = run(client(transport).search_judgement(conversation="user: 파이썬이 뭐야?", agent=AGENT))
    assert verdict == {"needs_search": False, "query": None, "reason": "stable_knowledge"}


@pytest.mark.parametrize("body", [
    judgement_body(answer="the model answered instead"),
    judgement_body(operation="search_evidence"),
    judgement_body(ok=False),
    judgement_body(needs_search="true"),
    judgement_body(reason="i_think_so"),
    judgement_body(query=None),
    {"unexpected": True},
])
def test_a_response_that_was_not_a_clean_verdict_is_refused(body):
    transport = Transport(body)
    with pytest.raises(PadiemAiEngineClientError):
        run(client(transport).search_judgement(conversation="user: 최신 정책이 어떻게 돼?", agent=AGENT))


def test_unbounded_or_empty_conversation_never_reaches_the_engine():
    for conversation in ("", "   ", "질문 " * 2_000, None, 7):
        transport = Transport(judgement_body())
        with pytest.raises(PadiemAiEngineClientError):
            run(client(transport).search_judgement(conversation=conversation, agent=AGENT))
        assert transport.calls == []


def test_the_judgement_call_never_carries_a_private_system_context_field():
    transport = Transport(judgement_body())
    run(client(transport).search_judgement(conversation="user: 공고", agent=AGENT))
    call = transport.calls[0]
    assert "additional_system_context" not in call["body"].decode("utf-8")
