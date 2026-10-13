"""#4469: B66 dialogue retrieval stays on the shared #3385 route and never leaks.

Every scenario uses an in-memory provider, so no TinyFish/Daum credential, network
call or paid request happens here. The load-bearing claims are: a greeting pays
nothing, a private-particular turn is withheld before any provider io, and a
failure is disclosed instead of being claimed as a search.
"""
from __future__ import annotations

import asyncio

import pytest

from app.b66_search_boundary import (
    MAX_B66_QUERY_CHARS,
    _envelope,
    plan_b66_search,
    withheld_private_class,
)
from app.auto_grounding import AutoGroundingService
from app.grounding import GroundingError
from app.web_tools import WebToolError
from padiem_ai_core import Evidence as CoreEvidence


class StubProvider:
    """Stands in for the real TinyFish→Daum provider and records every query."""

    def __init__(self, results=(), error=None):
        self.queries: list[str] = []
        self._results = list(results)
        self._error = error
        # Production sets this from runtime_mode; preview/mock must stay zero-network.
        self._automatic_search_enabled = True

    async def search(self, query, limit=5):
        self.queries.append(query)
        if self._error is not None:
            raise self._error
        return self._results[:limit]

    async def fetch(self, url):
        raise AssertionError("B66 dialogue must not fetch pages in this slice")


def evidence(title="철근 시세", url="https://steel.example.co.kr/price"):
    return CoreEvidence(
        id="ev-1", title=title, snippet="철근 시세와 톤당 가격",
        retrieved_at="2026-10-13T02:00:00Z", provider="tinyfish",
        source_type="web", url=url,
    )


def plan(provider):
    return AutoGroundingService(provider)


def outcome(provider, text):
    return asyncio.run(plan_b66_search(plan(provider), text, allow_provider=True))


def test_unapproved_live_fact_search_stays_off_even_with_a_configured_provider():
    # #4465 approval is a separate trusted server-side release gate. A provider
    # being configured, even with credentials, is not permission to call it.
    provider = StubProvider([evidence()])
    result = asyncio.run(plan_b66_search(plan(provider), "최신 철근 시세 알려줘"))
    assert result.status == "unavailable"
    assert result.reason == "fact_search_authorization_required"
    assert result.sources == ()
    assert provider.queries == []
    # Non-search turns remain natural and cost no calls without authorization.
    greeting = asyncio.run(plan_b66_search(plan(provider), "안녕"))
    assert greeting.status == "not_needed"
    assert provider.queries == []


def test_a_greeting_and_quote_intent_cost_no_provider_call():
    provider = StubProvider([evidence()])
    for text in ("안녕", "견적 만들고 싶어", "지난 견적을 수정하고 싶어"):
        result = outcome(provider, text)
        assert result.status == "not_needed", text
    assert provider.queries == []


def test_a_public_freshness_question_retrieves_once_with_source_and_as_of():
    result = outcome(StubProvider([evidence()]), "최신 철근 시세 알려줘")
    assert result.status == "sourced"
    assert result.sources[0]["url"] == "https://steel.example.co.kr/price"
    assert result.sources[0]["retrieved_at"] == "2026-10-13T02:00:00Z"
    assert result.sources[0]["provider"] == "tinyfish"
    # Source date and retrieval time are separately labelled for the member.
    assert "retrieved_at" in result.context
    assert "수집" in _envelope(result)


def test_no_evidence_is_reported_as_empty_not_as_a_successful_search():
    result = outcome(StubProvider([]), "최신 철근 시세 알려줘")
    assert result.status == "empty"
    assert result.sources == ()
    assert "쓸 만한 근거를 얻지 못했습니다" in _envelope(result)
    assert "검색했다고 말하거나" not in _envelope(result)


def test_provider_failure_is_disclosed_and_never_replaced_by_an_invented_answer():
    provider = StubProvider(error=WebToolError("web_upstream_error", "provider down", 503))
    result = outcome(provider, "최신 철근 시세 알려줘")
    assert result.status == "failed"
    assert result.reason == "web_upstream_error"
    assert "실패했습니다" in _envelope(result)
    assert result.context is None


def test_an_unexpected_transport_fault_still_becomes_a_disclosed_failure():
    class Exploding:
        _automatic_search_enabled = True

        async def prepare(self, *a, **k):
            raise RuntimeError("PRIVATE PROVIDER TRACE")

    result = asyncio.run(plan_b66_search(Exploding(), "최신 철근 시세 알려줘", allow_provider=True))
    assert result.status == "failed" and result.reason == "web_transport_error"


@pytest.mark.parametrize(("question", "private_class"), [
    ("대한건설 주식회사 배관 시세 검색해줘", "corporation"),
    ("김철수님 연락처 검색해줘", "person"),
    ("010-1234-5678 예약 검색해줘", "phone"),
    ("buyer@example.test 주문 검색해줘", "email"),
    ("https://billing.example/x 검색해줘", "url"),
    ("123456-7654321 검색해줘", "registry"),
    ("발주서 양식 검색해줘", "quote_document"),
    ("거래처 단가 검색해줘", "counterparty"),
    ("18000원 단가 검색해줘", "amount"),
    ("계좌번호 검색해줘", "credential"),
])
def test_a_turn_carrying_private_particulars_reaches_no_provider(question, private_class):
    provider = StubProvider([evidence()])
    assert withheld_private_class(question) == private_class
    result = outcome(provider, question)
    assert result.status == "withheld_private"
    assert provider.queries == [], "a withheld turn must not contact a paid provider"
    assert "검색을 실행하지 않았습니다" in _envelope(result)


def test_the_retrieved_question_is_bounded_and_never_augmented_with_other_text():
    long_question = "최신 철근 시세 " + ("원" * 600)
    provider = StubProvider([evidence()])
    result = outcome(provider, long_question)
    assert result.status == "sourced"
    assert provider.queries == [long_question[:MAX_B66_QUERY_CHARS]]
    assert len(provider.queries[0]) == MAX_B66_QUERY_CHARS


def test_a_preview_or_absent_grounding_route_searches_nothing():
    provider = StubProvider([evidence()])
    provider._automatic_search_enabled = False
    result = outcome(provider, "최신 철근 시세 알려줘")
    assert result.status == "unavailable"
    assert provider.queries == []

    assert asyncio.run(plan_b66_search(None, "최신 철근 시세 알려줘")).status == "unavailable"


def test_public_dict_carries_the_status_the_member_can_see():
    result = outcome(StubProvider([evidence()]), "최신 철근 시세 알려줘")
    published = result.public_dict()
    assert published["status"] == "sourced"
    assert published["sources"][0]["title"] == "철근 시세"
    assert "snippet" not in published["sources"][0], "raw snippets are not a member-facing field"
