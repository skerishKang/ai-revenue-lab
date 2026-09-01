from __future__ import annotations

import asyncio

import pytest

from padiem_ai_core import Evidence
from padiem_ai_core.grounding_runtime import GroundingRuntimeError
from padiem_ai_core.search_preparation import prepare_search_grounding
from padiem_ai_core.web_runtime import WebRuntimeError


def run(coro):
    return asyncio.run(coro)


class RecordingProvider:
    def __init__(
        self,
        *,
        fail: bool = False,
        empty: bool = False,
        results: list[Evidence] | None = None,
    ):
        self.fail = fail
        self.empty = empty
        self.results = results
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int = 5):
        self.calls.append((query, limit))
        if self.fail:
            raise WebRuntimeError("web_unavailable", "safe provider unavailable", 502)
        if self.empty:
            return []
        if self.results is not None:
            return list(self.results)
        return [
            Evidence(
                id="ev-1",
                title="Source",
                url="https://example.com/source",
                snippet="Verified current fact",
                retrieved_at="2026-09-01T00:00:00Z",
                provider="mock",
                source_type="search",
            )
        ]

    async def fetch(self, url: str):
        raise AssertionError("search preparation must not fetch pages")


def test_prepare_search_grounding_retrieves_and_combines_context_without_synthesis() -> None:
    provider = RecordingProvider()
    prepared = run(
        prepare_search_grounding(
            provider,
            " current fact ",
            additional_system_context="PRODUCT CONTEXT",
            max_total_context_chars=14_000,
        )
    )
    assert provider.calls == [("current fact", 5)]
    assert prepared.context.startswith("PRODUCT CONTEXT\n\n웹 근거 사용 규칙")
    assert "Verified current fact" in prepared.context
    assert len(prepared.evidence) == 1


def test_prepare_search_grounding_filters_irrelevant_results_before_model_context() -> None:
    relevant = Evidence(
        id="ev-relevant",
        title="한국은행 기준금리",
        url="https://www.bok.or.kr/portal/singl/baseRate/list.do",
        snippet="한국은행 기준금리는 현재 연 3.00%입니다.",
        retrieved_at="2026-09-01T00:00:00Z",
        provider="daum",
        source_type="search",
    )
    irrelevant = Evidence(
        id="ev-irrelevant",
        title="아이돌 디엠 보내는 방법",
        url="https://example.com/unrelated",
        snippet="팬 커뮤니티에서 메시지를 보내는 방법을 설명합니다.",
        retrieved_at="2026-09-01T00:00:00Z",
        provider="daum",
        source_type="search",
    )
    provider = RecordingProvider(results=[irrelevant, relevant])

    prepared = run(
        prepare_search_grounding(
            provider,
            "현재 한국은행 기준금리",
            additional_system_context=None,
            max_total_context_chars=14_000,
        )
    )

    assert tuple(item.id for item in prepared.evidence) == ("ev-relevant",)
    assert "한국은행 기준금리는 현재 연 3.00%입니다." in prepared.context
    assert "아이돌 디엠 보내는 방법" not in prepared.context
    assert "팬 커뮤니티" not in prepared.context


def test_prepare_search_grounding_fails_closed_when_quality_gate_rejects_every_result() -> None:
    provider = RecordingProvider(
        results=[
            Evidence(
                id="ev-irrelevant",
                title="아이돌 디엠 보내는 방법",
                url="https://example.com/unrelated",
                snippet="팬 커뮤니티에서 메시지를 보내는 방법을 설명합니다.",
                retrieved_at="2026-09-01T00:00:00Z",
                provider="daum",
                source_type="search",
            )
        ]
    )

    with pytest.raises(GroundingRuntimeError) as info:
        run(
            prepare_search_grounding(
                provider,
                "현재 한국은행 기준금리",
                additional_system_context=None,
                max_total_context_chars=14_000,
            )
        )

    assert info.value.code == "no_evidence"


def test_prepare_search_grounding_fails_closed_on_empty_evidence() -> None:
    provider = RecordingProvider(empty=True)
    with pytest.raises(GroundingRuntimeError) as info:
        run(
            prepare_search_grounding(
                provider,
                "current fact",
                additional_system_context=None,
                max_total_context_chars=14_000,
            )
        )
    assert info.value.code == "no_evidence"


def test_prepare_search_grounding_translates_provider_failure() -> None:
    provider = RecordingProvider(fail=True)
    with pytest.raises(GroundingRuntimeError) as info:
        run(
            prepare_search_grounding(
                provider,
                "current fact",
                additional_system_context=None,
                max_total_context_chars=14_000,
            )
        )
    assert info.value.code == "web_unavailable"
    assert info.value.status_code == 502
