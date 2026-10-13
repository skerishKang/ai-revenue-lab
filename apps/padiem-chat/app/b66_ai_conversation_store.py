"""B66 #4466/#4412: private D1 slot for the server-owned conversation state.

One bounded slot per server-derived owner/workspace, modeled exactly on the
existing B66 guided-draft slot (#028). Only the canonical bounded state is
persisted: conversation mode, validated quote facts and the revision used for
duplicate/conflict handling. This store never holds QuoteCore computed totals,
provider payloads, raw message logs or CGI template data, and a malformed row
fails closed instead of reaching a client.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .b66_ai_conversation import (
    B66ConversationError,
    MAX_STATE_BYTES,
    empty_state,
    normalize_conversation_state,
)


class D1ConversationStore:
    """Owner/workspace-scoped conversation slot over the existing private D1."""

    def __init__(self, db: Any) -> None:
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def load(self, *, user_id: str, workspace_id: str) -> dict | None:
        row = await self.db.prepare(
            "SELECT state_json FROM b66_ai_conversation WHERE user_id=? AND workspace_id=?"
        ).bind(user_id, workspace_id).first()
        if row is None:
            return None
        if not isinstance(row, dict):
            row = row.to_py() if callable(getattr(row, "to_py", None)) else dict(row)
        raw = row.get("state_json")
        if not isinstance(raw, str) or len(raw) > MAX_STATE_BYTES:
            raise B66ConversationError("invalid_stored_conversation_state")
        try:
            return normalize_conversation_state(json.loads(raw))
        except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
            raise B66ConversationError("invalid_stored_conversation_state") from exc

    async def save(self, *, user_id: str, workspace_id: str, state: dict) -> None:
        payload = normalize_conversation_state(state)
        encoded = json.dumps(
            payload, ensure_ascii=False, allow_nan=False,
            separators=(",", ":"), sort_keys=True,
        )
        if len(encoded.encode("utf-8")) > MAX_STATE_BYTES:
            raise B66ConversationError("conversation_state_too_large")
        updated = datetime.now(timezone.utc).isoformat()
        await self.db.prepare(
            "INSERT INTO b66_ai_conversation (user_id,workspace_id,state_json,updated_at)"
            " VALUES (?,?,?,?) ON CONFLICT(user_id,workspace_id) DO UPDATE"
            " SET state_json=excluded.state_json,updated_at=excluded.updated_at"
        ).bind(user_id, workspace_id, encoded, updated).run()

    async def clear(self, *, user_id: str, workspace_id: str) -> None:
        await self.db.prepare(
            "DELETE FROM b66_ai_conversation WHERE user_id=? AND workspace_id=?"
        ).bind(user_id, workspace_id).run()


__all__ = ["D1ConversationStore", "empty_state"]
