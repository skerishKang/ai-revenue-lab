"""#4379/#6842: Chat adds no turn or character total of its own.

The browser keeps sending the whole thread and the request contract is
untouched. #6812 stage 2 had the server cut that thread to 20 turns / 12,000
characters; #4379 makes the model's registered context window the only bound, and
B14 applies it where the registry is read. Chat forwards what it received.
"""

from __future__ import annotations

from app.b14_client import _execution_request, _multimodal_execution_request
from app.config import Settings
from app.task_modes import get_task_mode

MODEL_ID = "bounds/test-model"


def thread(turns: int, *, chars: int = 40) -> list[dict[str, str]]:
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


def test_a_long_thread_travels_whole() -> None:
    messages = thread(30)

    request = request_for(messages)

    assert list(request.messages) == messages
    assert request.messages[-2]["content"].startswith("Q30:")


def test_no_truncation_wording_is_added() -> None:
    request = request_for(thread(60))

    assert "생략되었습니다" not in (request.additional_system_context or "")


def test_a_single_huge_turn_is_not_cut() -> None:
    # No trailing whitespace: the request contract trims edges, and the point
    # here is that the body of a huge turn is never shortened (#4379).
    messages = thread(3) + [{"role": "user", "content": "긴 질문" * 20_000}]

    request = request_for(messages)

    assert len(request.messages) == len(messages)
    assert request.messages[-1]["content"] == messages[-1]["content"]
    assert len(request.messages[-1]["content"]) == len(messages[-1]["content"])


def test_the_multimodal_lane_forwards_the_thread_too() -> None:
    parts = [
        {"type": "text", "text": "이 사진을 설명해 주세요"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="}},
    ]
    messages = thread(25) + [{"role": "user", "content": parts}]

    request = _multimodal_execution_request(
        messages,
        skill=get_task_mode(),
        model=MODEL_ID,
        additional_system_context=None,
    )

    # The lane normalizes parts into immutable mappings; what matters is that
    # both parts of the newest turn and every earlier turn are still there.
    assert len(request.messages) == len(messages)
    last = request.messages[-1]
    assert last["role"] == "user"
    assert last["content"][0]["text"] == parts[0]["text"]
    assert last["content"][1]["image_url"]["url"] == parts[1]["image_url"]["url"]
    assert request.messages[0]["content"] == messages[0]["content"]


def test_the_settings_carry_no_history_total() -> None:
    settings = Settings()

    assert not hasattr(settings, "history_max_turns")
    assert not hasattr(settings, "history_max_chars")
