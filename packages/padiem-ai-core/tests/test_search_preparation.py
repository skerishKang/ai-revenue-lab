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
    def __init__(self, *, fail: bool = False, empty: bool = False):
        self.fail = fail
        self.empty = empty
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, limit: int = 5):
        self.calls.append((query, limit))
        if self.fail:
            raise WebRuntimeError("web_unavailable", "private detail", 502)
        if self.empty:
            return []
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


def test_prepare_search_grounding_translates_provider_failure_without_private_detail() -> None:
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
    assert "private detail" not in str(info.value)
