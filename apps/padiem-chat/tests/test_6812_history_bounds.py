"""#6812 stage 2: the server bounds the conversation history it sends to B14.

The browser keeps sending the whole thread and the request contract is
untouched; only what the server hands the model is bounded. The system
instruction and the current question always survive, and a trimmed history is
disclosed in the system wording instead of looking complete.
"""

from __future__ import annotations

from app.b14_client import _execution_request, _multimodal_execution_request
from app.config import Settings
from app.request_contract import _validate_payload_parts
from app.task_modes import get_task_mode
from padiem_ai_core.conversation_bounds import (
    DEFAULT_HISTORY_MAX_CHARS,
    DEFAULT_HISTORY_MAX_TURNS,
    HISTORY_TRUNCATION_NOTE,
)

MODEL_ID = "bounds/test-model"


def thread(turns: int, *, chars: int = 10) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for turn in range(1, turns + 1):
        messages.append({"role": "user", "content": f"Q{turn}:" + "x" * chars})
        messages.append({"role": "assistant", "content": f"A{turn}:" + "y" * chars})
    return messages


def request_for(messages, **kwargs):
    return _execution_request(
        messages,
        skill=get_task_mode(),
        model=MODEL_ID,
        required_capabilities=("chat",),
        additional_system_context=None,
        **kwargs,
    )


def test_long_thread_is_trimmed_before_dispatch() -> None:
    messages = thread(30)

    request = request_for(messages)

    assert len(request.messages) == DEFAULT_HISTORY_MAX_TURNS * 2
    # The current question is the newest user entry and it is still there.
    assert request.messages[-2]["content"].startswith("Q30:")
    assert request.messages[-1]["content"].startswith("A30:")


def test_trimming_is_disclosed_in_the_system_wording() -> None:
    request = request_for(thread(30))

    context = request.additional_system_context or ""
    assert HISTORY_TRUNCATION_NOTE in context


def test_system_instruction_and_question_survive_trimming() -> None:
    request = request_for(thread(40))

    assert request.agent.system_instruction
    context = request.additional_system_context or ""
    # The server-sampled clock preinstruction keeps its place ahead of the note.
    assert context.index(HISTORY_TRUNCATION_NOTE) > 0
    assert request.messages[-2]["role"] == "user"


def test_short_thread_is_sent_unchanged_and_undisclosed() -> None:
    messages = thread(3)

    request = request_for(messages)

    assert list(request.messages) == messages
    assert HISTORY_TRUNCATION_NOTE not in (request.additional_system_context or "")


def test_character_cap_bounds_the_history_it_sends() -> None:
    messages = thread(30, chars=900)

    request = request_for(messages, history_max_chars=3_000)

    kept_chars = sum(len(message["content"]) for message in request.messages)
    # Only the newest turn may exceed the cap; it carries the question.
    assert len(request.messages) == 2
    assert kept_chars <= 3_000
    assert request.messages[-1]["content"].startswith("A30:")


def test_multimodal_history_uses_the_same_bounds() -> None:
    messages = thread(30)
    # Multimodal content belongs to a user turn; this one is the current turn.
    messages[-2] = {
        "role": "user",
        "content": [
            {"type": "text", "text": "Q30:"},
            {"type": "image_url", "image_url": {"url": (
                "data:image/png;base64,"
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
            )}},
        ],
    }

    request = _multimodal_execution_request(
        messages,
        skill=get_task_mode(),
        model=MODEL_ID,
        additional_system_context=None,
    )

    assert len(request.messages) == DEFAULT_HISTORY_MAX_TURNS * 2
    assert HISTORY_TRUNCATION_NOTE in (request.additional_system_context or "")


def test_browser_request_contract_still_accepts_the_whole_thread() -> None:
    messages = thread(30)

    parsed, skill, tool_request = _validate_payload_parts({"messages": messages})

    # The browser contract is unchanged: nothing is trimmed at the door.
    assert len(parsed) == 60
    assert parsed == messages
    assert skill is not None
    assert tool_request is None


def test_settings_defaults_match_the_shared_bounds() -> None:
    settings = Settings()

    assert settings.history_max_turns == DEFAULT_HISTORY_MAX_TURNS
    assert settings.history_max_chars == DEFAULT_HISTORY_MAX_CHARS


def test_history_bounds_are_configurable() -> None:
    settings = Settings.from_values(history_max_turns="5", history_max_chars="4000")

    assert settings.history_max_turns == 5
    assert settings.history_max_chars == 4_000
    # And the configured bound is the one that reaches the request.
    request = request_for(thread(30), history_max_turns=5, history_max_chars=4_000)
    assert len(request.messages) == 10
