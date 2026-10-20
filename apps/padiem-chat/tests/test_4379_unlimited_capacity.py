"""#4379: a product must not lose a model answer or a result by size.

Network-free. No provider call, no production mutation, no secret.
"""
from __future__ import annotations

import pytest

from app.b66_ai_conversation import (
    B66ConversationError,
    append_history,
    conversation_prompt,
    empty_state,
    normalize_conversation_state,
)
from app.b66_guided_draft import normalize_guided_transcript
from app.b66_b14_free_first_resolver import _dict_rows, _parse_bounded_response


def test_b66_conversation_keeps_a_long_model_answer():
    # #4379: a model answer longer than 2,000 characters used to fail the whole
    # turn with reply_too_long.
    state = empty_state()
    state = append_history(state, "긴 답변을 부탁해요", "가" * 9_000)
    normalized = normalize_conversation_state(state)
    assert normalized["history"][-1]["content"] == "가" * 9_000


def test_b66_conversation_prompt_is_not_cut():
    # #4379: the assembled system prompt used to be cut at 4,000 characters,
    # which silently removed the known facts and the earlier conversation.
    state = empty_state()
    state = append_history(state, "가" * 9_000, "나" * 9_000)
    prompt = conversation_prompt(state)
    assert "가" * 9_000 in prompt
    assert "나" * 9_000 in prompt
    assert len(prompt) > 4_000


def test_b66_conversation_keeps_every_turn():
    state = empty_state()
    for index in range(12):
        state = append_history(state, f"질문{index}", f"답변{index}")
    assert len(state["history"]) == 24


def test_guided_transcript_keeps_a_long_assistant_answer():
    # #4379: a transcript message longer than 9,000 characters was refused.
    long_text = "가" * 20_000
    rows = normalize_guided_transcript([{"role": "assistant", "content": long_text}])
    assert rows[0]["content"] == long_text


def test_b14_registry_is_not_capped_by_a_padiem_body_or_row_ceiling():
    # #4379: a registry body above 128 KB or more than 256 rows used to empty
    # B66's model list entirely.
    import json

    payload = {"registered_routes": [{"id": f"m{i}", "pad": "x" * 200} for i in range(1_000)]}
    raw = json.dumps(payload).encode("utf-8")
    assert len(raw) > 131_072
    parsed = _parse_bounded_response(200, raw)
    assert len(_dict_rows(parsed["registered_routes"])) == 1_000
