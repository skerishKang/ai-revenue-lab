"""Model-native conversation history for one model call (#4379, #6842).

The browser sends the thread as it stands, the server decides how much of it
reaches the model. PADIEM owns no turn total and no character total: the bound
is the context window the model registry declares for the model this request
actually reaches. The history is trimmed only when its estimated input exceeds
that window minus the answer's reservation, oldest turns first. A model whose
window the registry does not declare is never trimmed; the provider's own limit
is the truth then (#4379).

Only the oldest turns are dropped: the system instruction, the newest turn
(which carries the current user question), the turn before it (whose reply is
being continued, so a bound never orphans an answer) and any system entry inside
the history always survive. Nothing here changes the browser request contract; a
caller applies these bounds right before dispatch.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

#: The share of a declared context window held back for the answer. The reserve
#: scales with the model: it is not a PADIEM output total, only the room an
#: answer needs before the input may use the rest of the window.
DEFAULT_OUTPUT_RESERVE_DIVISOR = 4

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
    #: Estimated input tokens of ``messages`` plus the note, and the budget the
    #: estimate was compared against (None when the model's window is unknown).
    input_tokens: int = 0
    input_budget_tokens: int | None = None


def estimate_input_tokens(value: Any) -> int:
    """The low-side input estimate: four UTF-8 bytes per token.

    ``compaction.estimate_tokens`` takes the larger of characters and bytes/4 so
    a Korean prompt is never undercounted for a compaction decision. A window
    comparison needs the opposite bias: history may only be dropped when the
    input certainly does not fit, because removing content that fits would be a
    PADIEM cap in disguise. The byte term is therefore used alone.
    """
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return (len(text.encode("utf-8")) + 3) // 4


def model_input_budget(
    context_window: int | None, *, reserved_output_tokens: int | None = None
) -> int | None:
    """Tokens this model may receive, or None when its window is unknown.

    Unknown covers an absent value and the registry's own ``0`` for "not
    published": the registry validates ``context_window`` as a non-negative
    integer, so 0 is its "unknown" marker and never a real window.
    """
    if (
        context_window is None
        or isinstance(context_window, bool)
        or not isinstance(context_window, int)
        or context_window <= 0
    ):
        return None
    if reserved_output_tokens is None:
        reserve = context_window // DEFAULT_OUTPUT_RESERVE_DIVISOR
    else:
        if (
            isinstance(reserved_output_tokens, bool)
            or not isinstance(reserved_output_tokens, int)
            or reserved_output_tokens < 0
        ):
            raise ValueError("reserved_output_tokens must be a non-negative integer")
        reserve = reserved_output_tokens
    return max(1, context_window - reserve)


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
    model_context_window: int | None = None,
    reserved_output_tokens: int | None = None,
    note: str = HISTORY_TRUNCATION_NOTE,
) -> BoundedHistory:
    """Keep the history that fits the model's registered input budget.

    ``model_context_window`` is the value the model registry declares for the
    model this request reaches. None, 0 or any non-positive value means the
    window is not declared, and the history travels untouched (#4379). When it
    is declared, the newest turns are kept while the estimated input fits the
    window minus the answer's reservation; older turns are dropped oldest-first.
    The newest two turns are kept whatever their size. Dropped history is
    disclosed through ``note`` so the caller can place it in the system
    instruction.
    """

    entries = [dict(message) for message in messages if isinstance(message, Mapping)]
    budget = model_input_budget(
        model_context_window, reserved_output_tokens=reserved_output_tokens
    )
    if budget is None:
        return BoundedHistory(messages=tuple(entries))

    turns = _turns(
        [entry for entry in entries if entry.get("role") not in NEVER_DROPPED_ROLES]
    )
    always_kept = min(ALWAYS_KEPT_TURNS, len(turns))
    kept_turns: set[int] = set(range(len(turns)))

    def retained(kept: set[int]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        turn_cursor = -1
        for entry in entries:
            if entry.get("role") in NEVER_DROPPED_ROLES:
                out.append(entry)
                continue
            if entry.get("role") == "user":
                turn_cursor += 1
            if turn_cursor in kept:
                out.append(entry)
        return out

    def measured(kept: set[int]) -> int:
        total = estimate_input_tokens(retained(kept))
        if len(kept) < len(turns):
            total += estimate_input_tokens(note)
        return total

    input_tokens = measured(kept_turns)
    while len(kept_turns) > always_kept and input_tokens > budget:
        kept_turns.discard(min(kept_turns))
        input_tokens = measured(kept_turns)

    kept = retained(kept_turns)
    dropped_turns = len(turns) - len(kept_turns)
    truncated = dropped_turns > 0
    return BoundedHistory(
        messages=tuple(kept),
        truncated=truncated,
        dropped_messages=len(entries) - len(kept),
        dropped_turns=dropped_turns,
        note=note if truncated else None,
        input_tokens=input_tokens,
        input_budget_tokens=budget,
    )
