"""B66 model-native length boundaries: no product-owned text ceilings.

Quote semantic validity and HTTP transport memory defenses are separate gates.
"""
import json
import pytest

from app.b66_quote_conversation import (
    B66QuoteConversationInterpreter,
    MAX_CONVERSATION_CHARS,
    MAX_RESULT_CHARS,
    normalize_conversation_output,
)

_SKILL = {
    "variableSchema": {"recipient": True, "items": True, "taxMode": True},
    "fixedDefaults": {"taxMode": "EXCLUSIVE"},
}
_ANSWER = {
    "recipient": {"company": "Fictional QA"},
    "items": [{"name": "Pipe", "qty": 2, "unitPrice": 1000}],
    "taxMode": "EXCLUSIVE",
    "missing": [],
}


def test_b66_model_output_can_exceed_former_24000_character_limit():
    assert MAX_RESULT_CHARS is None
    # Long harmless JSON whitespace, not oversized quote facts.
    output = json.dumps(_ANSWER, ensure_ascii=False) + (" " * 30_000)
    candidate = normalize_conversation_output(output, server_derives_missing=True)
    assert len(candidate.items) == 1
    assert candidate.items[0]["unitPrice"] == 1000


@pytest.mark.asyncio
async def test_b66_model_input_longer_than_former_4000_chars_is_not_truncated():
    assert MAX_CONVERSATION_CHARS is None

    class Recorder:
        calls = 0
        seen_length = 0

        async def complete(self, messages, **kwargs):
            self.calls += 1
            self.seen_length = len(messages[0]["content"])
            assert isinstance(kwargs.get("additional_system_context"), str)
            return {"answer": json.dumps(_ANSWER)}

    client = Recorder()
    raw = ("This is a fictional QA quote " * 200) + "Pipe 2 units at 1000"
    assert len(raw) > 4000
    interpreter = B66QuoteConversationInterpreter(client)
    result = await interpreter.interpret(
        message=raw, skill=_SKILL, model_id="google/gemini-3.5-flash-lite",
    )
    assert client.calls == 1
    assert client.seen_length == len(raw)
    assert len(result.items) == 1
