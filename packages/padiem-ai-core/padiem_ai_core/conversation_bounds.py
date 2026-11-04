"""Bounded conversation history for one model call (#6812 stage 2).

The browser sends the thread as it stands, the server decides how much of it
reaches the model. Only the oldest turns are dropped: the system instruction,
the newest turn (which carries the current user question) and any system entry
inside the history always survive. Nothing here changes the browser request
contract; a caller applies these bounds right before dispatch.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

#: Recent turns that may travel with a request.
DEFAULT_HISTORY_MAX_TURNS = 20
#: Characters of conversation content that may travel with a request.
DEFAULT_HISTORY_MAX_CHARS = 12_000

#: Turns that always survive, newest first: the turn holding the current
#: question and the turn before it, which holds the answer being continued.
#: #4379 sends both as the stored originals, so a bound never orphans a reply.
ALWAYS_KEPT_TURNS = 2

#: Short system-side disclosure. A trimmed history must not look complete.
HISTORY_TRUNCATION_NOTE = (
    "이전 대화의 오래된 부분은 길이 한도 때문에 생략되었습니다. "
    "남아 있는 대화와 이번 질문을 기준으로 답하세요."
)

NEVER_DROPPED_ROLES = frozenset({"system"})


@dataclass(frozen=True, slots=True)
class BoundedHistory:
    """The history a model call may carry, and what was left behind."""

    messages: tuple[dict[str, Any], ...]
    truncated: bool = False
    dropped_messages: int = 0
    dropped_turns: int = 0
    note: str | None = None


def _content_chars(message: Mapping[str, Any]) -> int:
    content = message.get("content")
    return len(content) if isinstance(content, str) else 0


def _turns(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group entries into turns; every user message begins a new turn."""
    turns: list[list[dict[str, Any]]] = []
    for message in messages:
        if not turns or message.get("role") == "user":
            turns.append([message])
        else:
            turns[-1].append(message)
    return turns


def bound_conversation_history(
    messages: Iterable[Mapping[str, Any]],
    *,
    max_turns: int = DEFAULT_HISTORY_MAX_TURNS,
    max_chars: int = DEFAULT_HISTORY_MAX_CHARS,
    note: str = HISTORY_TRUNCATION_NOTE,
) -> BoundedHistory:
    """Keep the newest turns that fit both the turn and the character cap.

    The newest two turns are kept whatever their size: the newest holds the
    question being answered and the one before it holds the answer it follows
    from. Older turns are dropped oldest-first until either cap would be
    exceeded. Dropped history is disclosed through ``note`` so the caller can
    place it in the system instruction.
    """

    if isinstance(max_turns, bool) or not isinstance(max_turns, int) or max_turns < 1:
        raise ValueError("max_turns must be a positive integer")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
        raise ValueError("max_chars must be a positive integer")

    entries = [dict(message) for message in messages if isinstance(message, Mapping)]
    kept_roles = [entry for entry in entries if entry.get("role") in NEVER_DROPPED_ROLES]
    turns = _turns(
        [entry for entry in entries if entry.get("role") not in NEVER_DROPPED_ROLES]
    )

    always_kept = min(ALWAYS_KEPT_TURNS, len(turns))
    kept_turns: set[int] = set()
    used_chars = 0
    for turn_index in range(len(turns) - 1, -1, -1):
        turn_chars = sum(_content_chars(message) for message in turns[turn_index])
        if len(kept_turns) >= always_kept:
            if len(kept_turns) >= max_turns:
                break
            if used_chars + turn_chars > max_chars:
                break
        kept_turns.add(turn_index)
        used_chars += turn_chars

    dropped_turns = len(turns) - len(kept_turns)
    retained: list[dict[str, Any]] = []
    dropped_messages = 0
    turn_cursor = -1
    for entry in entries:
        if entry.get("role") in NEVER_DROPPED_ROLES:
            retained.append(entry)
            continue
        if entry.get("role") == "user":
            turn_cursor += 1
        if turn_cursor in kept_turns:
            retained.append(entry)
        else:
            dropped_messages += 1

    truncated = dropped_messages > 0 or dropped_turns > 0
    return BoundedHistory(
        messages=tuple(retained),
        truncated=truncated,
        dropped_messages=dropped_messages,
        dropped_turns=dropped_turns,
        note=note if truncated else None,
    )
