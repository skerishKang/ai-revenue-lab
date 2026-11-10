"""PC terminal command confirmation gate (2026-11-11).

The explicit backtick lane (`#4139`) used to execute every matched command in
the owner's turn without a second step. A pasted document or a multi-line body
carries backtick spans just as well as a typed one-liner, so "the owner's own
words" alone could turn an accidental paste into a remote execution.

The no-confirmation case is now narrow: one line the owner typed, one short
command. Everything else that matches the command grammar shows a one-line
confirmation card first, and the owner's next bare affirmative turn confirms
exactly the shown command — the same shown-question + next-affirmative pattern
the PC delegation lane uses. The command that runs is re-derived SERVER-SIDE
from the staged turn (the pending ``pc_command`` run row written by
``HistoryStore.record_txt_pending_run``), never from a browser-provided card.

Reads are untouched: this gate only widens the confirmation step, it never
narrows an authority check. Every dispatch still re-verifies the owner
session, canonical account scope and the deployment's command grant on the
existing Mesh command lane.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

#: A hand-typed one-liner is short. A command longer than this, or any command
#: with a line break, travels through the confirmation card instead. There is
#: no transport-level paste flag today, so the line count and this length cap
#: are the paste evidence; a composer paste marker is the follow-up design.
DIRECT_COMMAND_MAX_CHARS = 200

#: One pending command stays confirmable for this long. After that the owner
#: re-sends the request (and answers the card again) instead of an old "네"
#: firing an aged command.
PENDING_PC_COMMAND_MAX_AGE_SECONDS = 600

ACTION_PC_COMMAND = "pc_command"
STATUS_CANCELLED = "cancelled"

_AFFIRMATIVE = re.compile(
    r"^\s*(?:네|예|응|그래|맞아|진행해|실행해|확인|yes|ok|okay|go ahead)[.!。]?\s*$",
    re.I,
)


def direct_command_eligible(user_text: str, command: str) -> bool:
    """Whether this exact turn may run without the confirmation card."""
    if not isinstance(user_text, str) or not isinstance(command, str):
        return False
    if not command or len(command) > DIRECT_COMMAND_MAX_CHARS:
        return False
    # A line break in the turn or in the span is paste evidence: multi-line
    # bodies and pasted scripts confirm first.
    return "\n" not in user_text and "\n" not in command


def confirmation_card(command: str) -> str:
    """The one-line card. The command rides in the single backtick span."""
    return (
        "PC 명령 확인: 다음 명령을 실행할까요? 실행하려면 '네'라고 답해 주세요. `"
        + command + "`"
    )


def is_affirmative_reply(user_text: str) -> bool:
    """A bare yes: any other wording falls through to the normal answer path."""
    return isinstance(user_text, str) and bool(_AFFIRMATIVE.fullmatch(user_text))


def _parsed_row_time(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def select_pending_command_row(rows, *, conversation_id: str | None, now: datetime):
    """The one pending ``pc_command`` row this conversation may still confirm.

    Rows arrive newest-first (the store orders by created_at DESC). The row
    must sit in the SAME conversation the confirm turn came from and be young
    enough; anything else keeps the answer path.
    """
    if conversation_id is None:
        return None
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        if row.get("action") != ACTION_PC_COMMAND or row.get("status") != "pending":
            continue
        if row.get("conversation_id") != conversation_id:
            continue
        created = _parsed_row_time(row.get("created_at"))
        if created is None or (now - created) > timedelta(
            seconds=PENDING_PC_COMMAND_MAX_AGE_SECONDS
        ):
            continue
        return row
    return None


def command_from_staged_turn(match_command, staged_content: str) -> str | None:
    """Re-derive the command from the server-staged turn text.

    ``match_command`` is the lane's own matcher (``_requested_local_command``).
    The staged text is the owner's exact stored turn; the browser never hands
    this function its own card.
    """
    if not isinstance(staged_content, str) or not staged_content.strip():
        return None
    requested, command = match_command(staged_content)
    if not requested or not isinstance(command, str) or not command:
        return None
    return command


def binds_row_to_turn(row, staged_content: str) -> bool:
    """The pending row was written for exactly this staged turn.

    Both staging paths store ``title = <product prefix> + <bounded turn>`` and
    the model-context read returns the same turn stripped and full, so the
    stored title minus its product prefix must be a prefix of it. A later
    unrelated turn in the same conversation fails this check and is never
    confirmed.
    """
    title = row.get("title") if isinstance(row, dict) else None
    staged = None
    if isinstance(title, str):
        for prefix in ("Claw: ", "Chat: "):
            if title.startswith(prefix):
                staged = title[len(prefix):]
                break
    return (
        staged is not None
        and isinstance(staged_content, str)
        and staged_content.strip().startswith(staged)
        and bool(staged)
    )
