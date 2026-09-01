from __future__ import annotations

import asyncio

import pytest

from padiem_ai_core.contracts import Evidence
from padiem_ai_core.grounding_runtime import (
    GroundedResearchRuntime,
    GroundingPolicy,
    GroundingRuntimeError,
)
from padiem_ai_core.source_quality import SourceQualityPolicy


def run(coro):
    return asyncio.run(coro)


def _ev(evidence_id: str, *, title: str, snippet: str, url: str) -> Evidence:
    return Evidence(
        id=evidence_id,
        title=title,
        snippet=snippet,
        retrieved_at="2026-09-01T00:00:00Z",
        provider="daum",
        source_type="search",
        url=url,
    )


class MixedSearchProvider:
    def __init__(self, items: list[Evidence]):
        self.items = items
        self.search_calls = 0
        self.fetch_calls = 0

    async def search(self, query: str, limit: int = 5) -> list[Evidence]:
        self.search_calls += 1
        return list(self.items[:limit])

    async def fetch(self, url: str) -> Evidence:
        self.fetch_calls += 1
        return _ev(
            "fetched",
            title="explicit fetched page",
            snippet="explicit fetched content",
            url=url,
        )


def test_simple_grounding_filters_irrelevant_result_before_synthesis() -> None:
    provider = MixedSearchProvider(
        [
            _ev(
                "dm-noise",
                title="모 딸님의 영어로 민주 디엠",
                snippet="가입하자마자 디엠이 왔어요",
                url="https://example.com/dm",
            ),
            _ev(
                "official",
                title="Padiem 파디엠 공식 안내",
                snippet="파디엠 제품의 공식 정보",
                url="https://padiem.net/about",
            ),
        ]
    )
    policy = GroundingPolicy(
        source_quality_policy=SourceQualityPolicy(
            authoritative_domains=("padiem.net",),
        )
    )
    runtime = GroundedResearchRuntime(provider, policy=policy)
    synthesis_contexts: list[str] = []

    async def synthesize(context: str) -> str:
        synthesis_contexts.append(context)
        return "ok"

    result = run(
        runtime.run_search(
            "파디엠",
            synthesizer=synthesize,
            additional_system_context=None,
            max_total_context_chars=14_000,
        )
    )

    assert provider.search_calls == 1
    assert provider.fetch_calls == 0
    assert [item.id for item in result.prepared.evidence] == ["official"]
    assert len(synthesis_contexts) == 1
    assert "Padiem 파디엠 공식 안내" in synthesis_contexts[0]
    assert "민주 디엠" not in synthesis_contexts[0]


def test_all_irrelevant_search_results_fail_before_synthesis() -> None:
    provider = MixedSearchProvider(
        [
            _ev(
                "food",
                title="오늘의 저녁 메뉴",
                snippet="간단한 음식 추천",
                url="https://example.com/food",
            )
        ]
    )
    runtime = GroundedResearchRuntime(provider)
    synthesis_calls = 0

    async def synthesize(context: str) -> str:
        nonlocal synthesis_calls
        synthesis_calls += 1
        return "must not run"

    with pytest.raises(GroundingRuntimeError) as info:
        run(
            runtime.run_search(
                "파디엠",
                synthesizer=synthesize,
                additional_system_context=None,
                max_total_context_chars=14_000,
            )
        )

    assert info.value.code == "no_evidence"
    assert synthesis_calls == 0


def test_explicit_fetch_is_not_blocked_by_domain_tier() -> None:
    provider = MixedSearchProvider([])
    runtime = GroundedResearchRuntime(provider)
    synthesis_contexts: list[str] = []

    async def synthesize(context: str) -> str:
        synthesis_contexts.append(context)
        return "ok"

    result = run(
        runtime.run_fetch(
            "https://www.reddit.com/r/example/comments/1",
            synthesizer=synthesize,
            additional_system_context=None,
            max_total_context_chars=14_000,
        )
    )

    assert provider.search_calls == 0
    assert provider.fetch_calls == 1
    assert [item.id for item in result.prepared.evidence] == ["fetched"]
    assert len(synthesis_contexts) == 1
