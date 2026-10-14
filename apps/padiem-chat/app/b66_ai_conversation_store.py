"""B66 #4466/#4412: private D1 slot for the server-owned conversation state.

One bounded slot per server-derived owner/workspace, modeled exactly on the
existing B66 guided-draft slot (#028). Only the canonical bounded state is
persisted: conversation mode, validated quote facts and the revision used for
duplicate/conflict handling. This store never holds QuoteCore computed totals,
provider payloads, raw message logs or CGI template data, and a malformed row
fails closed instead of reaching a client.

Writes are revision-atomic. ``save`` is a single compare-and-swap statement
against the slot's persisted ``revision`` column: an insert is accepted only for
the first commit, and an update only when the stored revision is still exactly
the one the caller read. Two requests that shared a revision can therefore never
both report success — the loser's statement affects zero rows and it raises
``revision_conflict`` while the winner's state stays durable. The affected-row
count comes from the database result itself; if it is unavailable or not a
plausible single-row count the write fails closed instead of being assumed.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .b66_ai_conversation import (
    B66ConversationError,
    ConversationRevisionConflict,
    MAX_STATE_BYTES,
    empty_state,
    normalize_conversation_state,
)

# The single CAS statement. The conflict branch is guarded by the *stored*
# revision, so a write built on a revision another request already replaced
# matches no row and reports zero changes.
_SAVE_SQL = (
    "INSERT INTO b66_ai_conversation (user_id,workspace_id,state_json,revision,updated_at)"
    " VALUES (?,?,?,?,?) ON CONFLICT(user_id,workspace_id) DO UPDATE"
    " SET state_json=excluded.state_json,revision=excluded.revision,updated_at=excluded.updated_at"
    " WHERE b66_ai_conversation.revision=?"
)


def _affected_rows(result: Any) -> int | None:
    """The D1 affected-row count, or ``None`` when the result cannot prove one.

    Cloudflare D1 exposes ``meta.changes`` on the result object; a bound adapter
    may hand back the same mapping directly. Anything else (including a missing
    or non-integer count) is reported as unknown so the caller can fail closed
    rather than treat an unverifiable write as a success.
    """
    meta: Any = None
    if isinstance(result, dict):
        meta = result.get("meta") if "meta" in result else result
    elif result is not None:
        meta = getattr(result, "meta", None)
    changes = meta.get("changes") if isinstance(meta, dict) else getattr(meta, "changes", None)
    if isinstance(changes, bool) or not isinstance(changes, int) or changes < 0:
        return None
    return changes


class D1ConversationStore:
    """Owner/workspace-scoped conversation slot over the existing private D1."""

    def __init__(self, db: Any) -> None:
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def load(self, *, user_id: str, workspace_id: str) -> dict | None:
        row = await self.db.prepare(
            "SELECT state_json,revision FROM b66_ai_conversation"
            " WHERE user_id=? AND workspace_id=?"
        ).bind(user_id, workspace_id).first()
        if row is None:
            return None
        if not isinstance(row, dict):
            row = row.to_py() if callable(getattr(row, "to_py", None)) else dict(row)
        raw = row.get("state_json")
        if not isinstance(raw, str) or len(raw) > MAX_STATE_BYTES:
            raise B66ConversationError("invalid_stored_conversation_state")
        try:
            state = normalize_conversation_state(json.loads(raw))
        except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
            raise B66ConversationError("invalid_stored_conversation_state") from exc
        stored_revision = row.get("revision")
        if isinstance(stored_revision, bool) or not isinstance(stored_revision, int):
            raise B66ConversationError("invalid_stored_conversation_state")
        if stored_revision != state["revision"]:
            # The compare-and-swap guard and the state itself disagree, so the
            # slot cannot be trusted to reject a stale writer.
            raise B66ConversationError("invalid_stored_conversation_state")
        return state

    async def save(
        self, *, user_id: str, workspace_id: str, state: dict, expected_revision: int
    ) -> None:
        """Commit ``state`` only if the slot is still at ``expected_revision``.

        ``expected_revision`` is the revision this caller read; it must be 0 for
        the first commit of a slot. A state that does not advance exactly one
        revision is refused before any statement runs.
        """
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise B66ConversationError("invalid_revision", path="revision", observed_type="number")
        payload = normalize_conversation_state(state)
        if payload["revision"] != expected_revision + 1:
            raise B66ConversationError("revision_advance_required", path="revision")
        encoded = json.dumps(
            payload, ensure_ascii=False, allow_nan=False,
            separators=(",", ":"), sort_keys=True,
        )
        if len(encoded.encode("utf-8")) > MAX_STATE_BYTES:
            raise B66ConversationError("conversation_state_too_large")
        updated = datetime.now(timezone.utc).isoformat()
        result = await self.db.prepare(_SAVE_SQL).bind(
            user_id, workspace_id, encoded, payload["revision"], updated, expected_revision
        ).run()
        changes = _affected_rows(result)
        if changes is None:
            # Unverifiable write: fail closed rather than report a success the
            # database never confirmed.
            raise B66ConversationError("conversation_state_write_unverifiable")
        if changes == 0:
            raise ConversationRevisionConflict()
        if changes != 1:
            raise B66ConversationError("conversation_state_write_unverifiable")

    async def clear(self, *, user_id: str, workspace_id: str) -> None:
        await self.db.prepare(
            "DELETE FROM b66_ai_conversation WHERE user_id=? AND workspace_id=?"
        ).bind(user_id, workspace_id).run()


__all__ = ["ConversationRevisionConflict", "D1ConversationStore", "empty_state"]
