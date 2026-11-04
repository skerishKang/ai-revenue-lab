"""#4379/#6842: what one B14 call may carry is the model's limit, not PADIEM's.

#6812 stage 2 first answered a slow web-search first byte with fixed caps (600
characters per preview, 4,000 in total, 20 turns, 12,000 characters). #4379 is
the standing principle: PADIEM owns no artificial total, the model's own input
limit is the real one. These tests pin the model-native rule — nothing is cut
while the request fits, the oldest turns go first when it does not, an
undeclared window cuts nothing — while the source-quality selection, the
citation numbering and the system instruction stay exactly as they were.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from padiem_ai_core import Evidence
from padiem_ai_core.conversation_bounds import (
    ALWAYS_KEPT_TURNS,
    HISTORY_TRUNCATION_NOTE,
    bound_conversation_history,
    estimate_input_tokens,
    model_input_budget,
)
from padiem_ai_core.evidence_blocks import trim_evidence_text
from padiem_ai_core.grounding_runtime import (
    MAX_EVIDENCE_SNIPPET_CHARS,
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
# Evidence: no PADIEM total, only a declared model budget ends a set
# ---------------------------------------------------------------------------


def test_a_full_evidence_set_travels_with_no_padiem_total() -> None:
    # Five provider-sized previews are ~10,000 characters. Nothing in PADIEM may
    # end that set early; the model's own window does that (#4379).
    items = [evidence(index, snippet="가" * 2_000) for index in range(1, 6)]

    prepared = prepare_grounding_context(items)

    assert len(prepared.evidence) == len(items)
    assert len(prepared.context) > 9_000
    parsed = blocks(prepared.context)
    # Citation numbering stays the selection order, one number per source.
    assert [marker for marker, _ in parsed] == [
        "[1", "[2", "[3", "[4", "[5",
    ]


def test_the_preview_cap_is_the_provider_size_again() -> None:
    # #6842 removed #6812 stage 2's 600/4,000 PADIEM caps.
    assert MAX_EVIDENCE_SNIPPET_CHARS == 2_000
    assert GroundingPolicy().max_evidence_snippet_chars == 2_000
    assert GroundingPolicy().max_evidence_total_chars is None


def test_a_declared_model_budget_ends_the_set_at_its_lowest_rank() -> None:
    items = [evidence(index, snippet="나" * 2_000) for index in range(1, 6)]

    prepared = prepare_grounding_context(items, max_context_chars=5_000)

    assert len(prepared.context) <= 5_000
    parsed = blocks(prepared.context)
    assert parsed, "the bounded set must still carry evidence"
    # The highest-ranked sources survive, and numbering stays 1..k.
    assert [marker for marker, _ in parsed] == [
        f"[{index}" for index in range(1, len(parsed) + 1)
    ]
    assert len(prepared.evidence) == len(parsed)
    assert prepared.evidence[0].id == "ev-1"


def test_a_policy_total_is_only_what_a_caller_declares() -> None:
    items = [evidence(index, snippet="다" * 2_000) for index in range(1, 6)]

    prepared = prepare_grounding_context(
        items, policy=GroundingPolicy(max_evidence_total_chars=4_000)
    )

    assert len(prepared.context) <= 4_000
    assert len(prepared.evidence) < len(items)


def test_trim_evidence_text_drops_the_highest_number_first() -> None:
    prepared = prepare_grounding_context(
        [evidence(index, snippet="라" * 400) for index in range(1, 6)]
    )
    context = prepared.context
    block_lines = [
        line for line in context.splitlines() if line.startswith("[")
    ]

    cut, dropped = trim_evidence_text(
        context, max_chars=len(context) - (len(block_lines[-1]) + 1)
    )

    assert dropped == 1
    assert "[4]" in cut and "[5]" not in cut
    # The surviving numbering is untouched, so citations still resolve.
    assert [marker for marker, _ in blocks(cut)] == ["[1", "[2", "[3", "[4"]


@pytest.mark.parametrize(
    "field, value",
    [
        ("max_evidence_snippet_chars", 0),
        ("max_evidence_snippet_chars", 5_000),
        ("max_evidence_snippet_chars", True),
        ("max_evidence_total_chars", 10),
        ("max_evidence_total_chars", True),
    ],
)
def test_policy_refuses_an_unusable_evidence_budget(field: str, value) -> None:
    with pytest.raises(ValueError):
        GroundingPolicy(**{field: value})


def test_quality_selection_marker_and_citation_flow_are_unchanged() -> None:
    results = [evidence(index, snippet="마" * 2_000) for index in range(1, 6)]
    provider = _StubProvider(results)

    prepared = run(
        prepare_search_grounding(
            provider,
            "오늘 환율",
            additional_system_context=None,
            max_total_context_chars=None,
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
# History: the registered window decides, nothing else
# ---------------------------------------------------------------------------


def thread(turns: int, *, chars_per_message: int = 40) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for turn in range(1, turns + 1):
        messages.append(
            {"role": "user", "content": f"Q{turn}:" + "x" * chars_per_message}
        )
        messages.append(
            {"role": "assistant", "content": f"A{turn}:" + "y" * chars_per_message}
        )
    return messages


def test_a_large_window_keeps_thirty_turns_whole() -> None:
    messages = thread(30)

    bounded = bound_conversation_history(messages, model_context_window=128_000)

    assert bounded.truncated is False
    assert bounded.note is None
    assert list(bounded.messages) == messages


def test_a_small_window_drops_the_oldest_turns_first() -> None:
    messages = thread(30)

    bounded = bound_conversation_history(messages, model_context_window=1_000)

    assert bounded.truncated is True
    assert bounded.note == HISTORY_TRUNCATION_NOTE
    assert len(bounded.messages) < len(messages)
    # The current question is the newest user entry and it always survives.
    assert bounded.messages[-2]["content"].startswith("Q30:")
    assert bounded.messages[-1]["content"].startswith("A30:")
    # Whatever survived is the newest tail of the thread, never a gap.
    assert bounded.messages == tuple(messages[len(messages) - len(bounded.messages):])


@pytest.mark.parametrize("window", [None, 0, -1, True, "128000"])
def test_an_undeclared_window_cuts_nothing(window) -> None:
    messages = thread(30)

    bounded = bound_conversation_history(messages, model_context_window=window)

    assert bounded.truncated is False
    assert list(bounded.messages) == messages


def test_the_newest_exchange_survives_even_over_the_budget() -> None:
    messages = [
        {"role": "user", "content": "old " * 100},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "Q2 " * 100},
        {"role": "assistant", "content": "A2 " * 100},
        {"role": "user", "content": "지금 질문 " * 400},
    ]

    bounded = bound_conversation_history(messages, model_context_window=200)

    # The newest two turns stay whatever their size; only the older one is cut.
    assert bounded.messages[-1] == messages[-1]
    assert bounded.messages[0] == messages[2]
    assert bounded.truncated is True
    assert bounded.dropped_turns == 1
    assert ALWAYS_KEPT_TURNS == 2


def test_system_entries_always_survive() -> None:
    messages = [
        {"role": "system", "content": "시스템 지침"},
        *thread(40, chars_per_message=200),
    ]

    bounded = bound_conversation_history(messages, model_context_window=400)

    assert bounded.messages[0] == {"role": "system", "content": "시스템 지침"}
    assert bounded.truncated is True


def test_the_budget_holds_back_the_answer_share() -> None:
    assert model_input_budget(1_000) == 750
    assert model_input_budget(1_000, reserved_output_tokens=100) == 900
    assert model_input_budget(None) is None
    assert model_input_budget(0) is None
    with pytest.raises(ValueError):
        model_input_budget(1_000, reserved_output_tokens=-1)


def test_the_estimate_counts_bytes_not_characters() -> None:
    # Four UTF-8 bytes per token, so Korean text is not undercounted and the
    # comparison against a token window never inflates a PADIEM cut.
    assert estimate_input_tokens("가나다라") == 3
    assert estimate_input_tokens("abcd") == 1


def test_a_small_history_is_not_trimmed_and_carries_no_note() -> None:
    messages = thread(3)

    bounded = bound_conversation_history(messages, model_context_window=128_000)

    assert bounded.truncated is False
    assert bounded.note is None
    assert list(bounded.messages) == messages
