"""#4379/#6842: B14 trims one attempt to the window its registry declares.

B14 is the place that reads the model registry, so it is the place that knows
the context window of the model a physical attempt reaches — a fallback
candidate included. PADIEM adds no turn, character or evidence total here: a
request that fits travels untouched, an undeclared window cuts nothing, and only
an over-window request loses its oldest turns (then its lowest-ranked evidence
blocks).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.pilot import catalog, platform
from padiem_ai_core import Evidence
from padiem_ai_core.grounding_runtime import prepare_grounding_context

MODEL = "bounds/test-model"


def install_window(monkeypatch, window) -> None:
    monkeypatch.setitem(
        catalog.CATALOG_BY_ID, MODEL, SimpleNamespace(context_window=window)
    )


def thread(turns: int, *, chars: int = 400) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for turn in range(1, turns + 1):
        messages.append({"role": "user", "content": f"Q{turn}:" + "x" * chars})
        messages.append({"role": "assistant", "content": f"A{turn}:" + "y" * chars})
    return messages


def test_a_large_window_forwards_the_request_untouched(monkeypatch) -> None:
    install_window(monkeypatch, 1_000_000)
    messages = thread(30)

    assert platform._messages_for_model(messages, MODEL) == messages


def test_a_small_window_drops_only_the_oldest_turns(monkeypatch) -> None:
    install_window(monkeypatch, 4_000)
    messages = thread(30)

    trimmed = platform._messages_for_model(messages, MODEL)

    assert len(trimmed) < len(messages)
    # The disclosure travels as the first system entry, never as a silent cut.
    assert trimmed[0]["role"] == "system"
    assert "생략되었습니다" in trimmed[0]["content"]
    # The current question and the answer it continues stay.
    assert trimmed[-2]["content"].startswith("Q30:")
    assert trimmed[-1]["content"].startswith("A30:")


@pytest.mark.parametrize("window", [0, -1, None, True])
def test_an_undeclared_window_keeps_the_request(monkeypatch, window) -> None:
    install_window(monkeypatch, window)
    messages = thread(30)

    assert platform._messages_for_model(messages, MODEL) is messages


def test_a_model_outside_the_registry_is_not_trimmed() -> None:
    messages = thread(30)

    assert platform._messages_for_model(messages, "bounds/unregistered") is messages


def test_the_system_instruction_is_never_dropped(monkeypatch) -> None:
    install_window(monkeypatch, 4_000)
    messages = [
        {"role": "system", "content": "시스템 지침"},
        *thread(20),
    ]

    trimmed = platform._messages_for_model(messages, MODEL)

    assert {"role": "system", "content": "시스템 지침"} in trimmed


def test_evidence_is_dropped_from_its_lowest_rank_not_whole(monkeypatch) -> None:
    install_window(monkeypatch, 2_000)
    items = [
        Evidence(
            id=f"ev-{index}",
            title=f"Source {index}",
            url=f"https://example.com/{index}",
            snippet="근거 " * 500,
            retrieved_at="2026-11-04T00:00:00Z",
            provider="mock",
            source_type="search",
        )
        for index in range(1, 6)
    ]
    context = prepare_grounding_context(items).context
    messages = [
        {"role": "system", "content": context},
        {"role": "user", "content": "지금 질문"},
    ]

    trimmed = platform._messages_for_model(messages, MODEL)

    system = next(
        message for message in trimmed if message.get("role") == "system"
    )
    content = system["content"]
    assert "[1]" in content
    assert "[5]" not in content
    # The instruction beside the evidence survives; only blocks were removed.
    assert content.splitlines()[0].startswith("웹 근거 사용 규칙")
