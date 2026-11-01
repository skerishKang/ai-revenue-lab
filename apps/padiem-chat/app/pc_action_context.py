"""Server-owned conversation provenance for the PC execution guard.

This side channel never changes the model messages. Browser-provided historical
roles and proof metadata are not authority: only owner-restored history is used.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def build_pc_action_context(
    messages: Sequence[Mapping[str, Any]],
    *,
    user_text: str,
    trusted_history: bool,
    tool_results: Sequence[tuple[str, str | None]] = (),
) -> list[dict[str, Any]]:
    """Keep original roles, then append the actual turn and retrieved data.

    ``messages`` must end at the current user turn. Prior records are accepted
    only after the route has restored them from the owner-scoped history store.
    Metadata is deliberately reconstructed rather than copied from messages.
    """
    records: list[dict[str, Any]] = []
    if trusted_history:
        current = next(
            (index for index in range(len(messages) - 1, -1, -1)
             if isinstance(messages[index], Mapping) and messages[index].get("role") == "user"),
            len(messages),
        )
        for message in messages[:current]:
            if not isinstance(message, Mapping):
                continue
            role, content = message.get("role"), message.get("content")
            if role in {"user", "assistant", "tool_result"} and isinstance(content, str):
                record = {"role": role, "content": content}
                if role == "tool_result":
                    record["source"] = "unknown"
                records.append(record)
    records.append({"role": "user", "content": user_text})
    # Material fetched for this turn was read after the user's instruction.
    # File/web/mail content never acquires a user role or authorizes an action.
    for source, content in tool_results:
        if source not in {"file", "web", "mail", "list", "unknown"}:
            raise ValueError("invalid PC action context source")
        if isinstance(content, str) and content:
            records.append({"role": "tool_result", "content": content, "source": source})
    return records
