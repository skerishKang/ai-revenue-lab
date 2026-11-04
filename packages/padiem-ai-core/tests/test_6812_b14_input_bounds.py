"""#6812 stage 2: evidence and history input bounds for one B14 call.

Two input lanes made a web-search turn large: the grounded evidence set had a
per-source preview cap and no total, and the browser thread travelled whole.
These tests pin the bounds, the configuration, and what must never be cut — the
source-quality selection, the citation numbering, the system instruction and the
current question.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from padiem_ai_core import Evidence
from padiem_ai_core.conversation_bounds import (
    DEFAULT_HISTORY_MAX_CHARS,
    DEFAULT_HISTORY_MAX_TURNS,
    HISTORY_TRUNCATION_NOTE,
    bound_conversation_history,
)
from padiem_ai_core.grounding_runtime import (
    EVIDENCE_SNIPPET_ENV,
    EVIDENCE_TOTAL_ENV,
    MAX_EVIDENCE_SNIPPET_CHARS,
    MAX_EVIDENCE_TOTAL_CHARS,
    GroundingPolicy,
    prepare_grounding_context,
)
from padiem_ai_core.search_preparation import prepare_search_grounding


def run(coro):
    return asyncio.run(coro)


def evidence(index: int, *, snippet: str | None = None) -> Evidence:
    return Evidence(
        id=f"ev-{index}",
        title=f"Source {index}",
        url=f"https://example.com/source/{index}",
        snippet=snippet if snippet is not None else f"Evidence text {index}",
        retrieved_at="2026-11-04T00:00:00Z",
        provider="mock",
        source_type="search",
    )


def blocks(context: str) -> list[dict]:
    """Parse the JSON source blocks out of a prepared evidence context."""
    parsed = []
    for line in context.splitlines():
        if not line.startswith("["):
            continue
        marker, _, payload = line.partition("] ")
        parsed.append((marker, json.loads(payload)))
    return parsed


class _StubProvider:
    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    async def search(self, query, limit=5):
        self.calls += 1
        return self._results[:limit]


# ---------------------------------------------------------------------------
# Evidence: per-preview and total caps
# ---------------------------------------------------------------------------


def test_default_preview_cap_bounds_each_source() -> None:
    items = [evidence(index, snippet="가" * 2_000) for index in range(1, 6)]

    prepared = prepare_grounding_context(items)

    parsed = blocks(prepared.context)
    assert len(parsed) == 5
    for _, payload in parsed:
        assert len(payload["snippet"]) <= MAX_EVIDENCE_SNIPPET_CHARS
    # Citation numbering stays the selection order, one number per source.
    assert [marker for marker, _ in parsed] == [
        "[1", "[2", "[3", "[4", "[5",
    ]


def test_default_total_cap_bounds_the_whole_evidence_set() -> None:
    # Ten sources of a full preview each would be 6,000 characters unbounded.
    items = [evidence(index, snippet="나" * 2_000) for index in range(1, 11)]

    prepared = prepare_grounding_context(items)

    assert len(prepared.context) <= MAX_EVIDENCE_TOTAL_CHARS
    parsed = blocks(prepared.context)
    assert parsed, "the bounded set must still carry evidence"
    markers = [marker for marker, _ in parsed]
    assert markers == [f"[{index}" for index in range(1, len(parsed) + 1)]
    assert len(prepared.evidence) == len(parsed)


def test_total_cap_applies_when_the_caller_declares_no_budget() -> None:
    # #4379 leaves the total to the caller; #6812 stage 2 gives it a default.
    items = [evidence(index, snippet="다" * 2_000) for index in range(1, 11)]

    prepared = prepare_grounding_context(items, max_context_chars=None)

    assert len(prepared.context) <= MAX_EVIDENCE_TOTAL_CHARS


def test_caller_budget_still_wins_when_it_is_smaller() -> None:
    items = [evidence(index, snippet="라" * 600) for index in range(1, 6)]

    prepared = prepare_grounding_context(items, max_context_chars=1_500)

    assert len(prepared.context) <= 1_500


def test_budgets_are_configurable_through_the_environment(monkeypatch) -> None:
    monkeypatch.setenv(EVIDENCE_SNIPPET_ENV, "300")
    monkeypatch.setenv(EVIDENCE_TOTAL_ENV, "1000")

    policy = GroundingPolicy()

    assert policy.max_evidence_snippet_chars == 300
    assert policy.max_evidence_total_chars == 1_000

    prepared = prepare_grounding_context(
        [evidence(index, snippet="마" * 2_000) for index in range(1, 6)],
        policy=policy,
    )
    assert len(prepared.context) <= 1_000
    for _, payload in blocks(prepared.context):
        assert len(payload["snippet"]) <= 300


def test_unusable_environment_value_keeps_the_default(monkeypatch) -> None:
    monkeypatch.setenv(EVIDENCE_SNIPPET_ENV, "not-a-number")

    policy = GroundingPolicy()

    assert policy.max_evidence_snippet_chars == MAX_EVIDENCE_SNIPPET_CHARS


@pytest.mark.parametrize(
    "field, value",
    [
        ("max_evidence_snippet_chars", 10),
        ("max_evidence_snippet_chars", 5_000),
        ("max_evidence_total_chars", 10),
        ("max_evidence_total_chars", 50_000),
        ("max_evidence_snippet_chars", True),
    ],
)
def test_policy_refuses_out_of_range_preview_budgets(field: str, value) -> None:
    with pytest.raises(ValueError):
        GroundingPolicy(**{field: value})


def test_quality_selection_marker_and_citation_flow_are_unchanged() -> None:
    results = [evidence(index, snippet="바" * 2_000) for index in range(1, 6)]
    provider = _StubProvider(results)

    prepared = run(
        prepare_search_grounding(
            provider,
            "오늘 환율",
            additional_system_context=None,
            max_total_context_chars=10_000,
        )
    )

    assert provider.calls == 1
    # Selection keeps every accepted source, in provider order.
    assert [item.id for item in prepared.evidence] == [
        f"ev-{index}" for index in range(1, 6)
    ]
    parsed = blocks(prepared.context)
    assert [marker for marker, _ in parsed] == [
        "[1", "[2", "[3", "[4", "[5",
    ]
    assert prepared.context.splitlines()[0].startswith("웹 근거 사용 규칙")


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


def thread(turns: int, *, chars_per_message: int = 10) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for turn in range(1, turns + 1):
        messages.append(
            {"role": "user", "content": f"Q{turn}:" + "x" * chars_per_message}
        )
        messages.append(
            {"role": "assistant", "content": f"A{turn}:" + "y" * chars_per_message}
        )
    return messages


def test_turn_cap_keeps_the_newest_turns() -> None:
    messages = thread(30)

    bounded = bound_conversation_history(messages)

    assert bounded.truncated is True
    assert len(bounded.messages) == DEFAULT_HISTORY_MAX_TURNS * 2
    assert bounded.dropped_turns == 10
    # The current question is the newest user entry and it always survives.
    assert bounded.messages[-2]["content"].startswith("Q30:")
    assert bounded.note == HISTORY_TRUNCATION_NOTE


def test_character_cap_drops_the_oldest_turns_first() -> None:
    messages = thread(5, chars_per_message=400)

    bounded = bound_conversation_history(messages, max_chars=1_000)

    kept_chars = sum(len(message["content"]) for message in bounded.messages)
    assert kept_chars <= 1_000
    assert bounded.truncated is True
    # newest turn kept, and it is still the tail of the conversation
    assert bounded.messages[-1]["content"].startswith("A5:")
    assert not any(
        message["content"].startswith("Q1:") for message in bounded.messages
    )


def test_the_newest_turn_survives_even_over_the_character_cap() -> None:
    messages = [
        {"role": "user", "content": "old " * 100},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "지금 질문 " * 400},
    ]

    bounded = bound_conversation_history(messages, max_chars=100)

    assert bounded.messages[-1] == messages[-1]
    assert bounded.truncated is True


def test_system_entries_always_survive() -> None:
    messages = [
        {"role": "system", "content": "시스템 지침"},
        *thread(40, chars_per_message=50),
    ]

    bounded = bound_conversation_history(messages, max_turns=2, max_chars=200)

    assert bounded.messages[0] == {"role": "system", "content": "시스템 지침"}
    content = [message["content"] for message in bounded.messages]
    assert "시스템 지침" in content


def test_small_history_is_not_trimmed_and_carries_no_note() -> None:
    messages = thread(3)

    bounded = bound_conversation_history(messages)

    assert bounded.truncated is False
    assert bounded.note is None
    assert list(bounded.messages) == messages
    assert DEFAULT_HISTORY_MAX_TURNS == 20
    assert DEFAULT_HISTORY_MAX_CHARS == 12_000


def test_bounds_reject_a_useless_limit() -> None:
    with pytest.raises(ValueError):
        bound_conversation_history(thread(1), max_turns=0)
    with pytest.raises(ValueError):
        bound_conversation_history(thread(1), max_chars=True)
