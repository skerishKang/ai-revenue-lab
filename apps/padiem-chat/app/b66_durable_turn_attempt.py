"""#4672: D1-owned B66 model attempt claim, before any paid provider dispatch.

This table is NOT a conversation, quote fact, model grant or reusable lease.
Only the signed-in server owner and the fixed B66 product scope address it.
A claim is never expired or automatically released: uncertainty after a timeout
must not be mistaken for proof that the provider was never charged.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

PRODUCT = "b66-quote"


def attempt_request_digest(
    *, model_id: str, conversation_id: str | None,
    messages: list[dict[str, str]], model_parameters: Any,
) -> str:
    """Persist only a fixed-size digest, never the user's words or provider data."""
    canonical = json.dumps(
        [PRODUCT, model_id, conversation_id, messages, model_parameters],
        ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _changed(result: Any) -> int:
    meta = result.get("meta") if isinstance(result, dict) else getattr(result, "meta", None)
    changes = meta.get("changes") if isinstance(meta, dict) else getattr(meta, "changes", None)
    if isinstance(changes, bool) or not isinstance(changes, int) or changes not in (0, 1):
        raise RuntimeError("b66_attempt_write_unverifiable")
    return changes


class D1B66TurnAttemptStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def claim(
        self, owner: str, token: str, model_id: str, digest: str,
    ) -> dict[str, str | None]:
        if not owner or not token or len(token) != 32 or not digest or len(digest) != 64:
            raise ValueError("invalid_attempt_identity")
        now = datetime.now(timezone.utc).isoformat()
        result = await self._db.prepare(
            "INSERT INTO b66_ai_turn_attempt "
            "(user_id, product_scope, turn_token, model_id, request_digest, state, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'claimed', ?) "
            "ON CONFLICT(user_id, product_scope, turn_token) DO NOTHING"
        ).bind(owner, PRODUCT, token, model_id, digest, now).run()
        if _changed(result) == 1:
            return {"status": "claimed", "conversation_id": None}
        row = await self._db.prepare(
            "SELECT model_id, request_digest, state, conversation_id "
            "FROM b66_ai_turn_attempt WHERE user_id=? AND product_scope=? AND turn_token=?"
        ).bind(owner, PRODUCT, token).first()
        if not isinstance(row, dict):
            raise RuntimeError("b66_attempt_row_unavailable")
        if row.get("model_id") != model_id or row.get("request_digest") != digest:
            return {"status": "conflict", "conversation_id": None}
        cid = row.get("conversation_id")
        if row.get("state") == "completed" and isinstance(cid, str) and cid:
            return {"status": "completed", "conversation_id": cid}
        return {"status": "in_progress", "conversation_id": None}

    async def complete(self, owner: str, token: str, conversation_id: str) -> None:
        if not owner or not token or not conversation_id:
            raise ValueError("invalid_attempt_completion")
        result = await self._db.prepare(
            "UPDATE b66_ai_turn_attempt SET state='completed', conversation_id=? "
            "WHERE user_id=? AND product_scope=? AND turn_token=? AND state='claimed'"
        ).bind(conversation_id, owner, PRODUCT, token).run()
        if _changed(result) != 1:
            raise RuntimeError("b66_attempt_completion_unverifiable")
