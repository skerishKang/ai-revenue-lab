from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping


class D1ByokUsageStore:
    def __init__(self, db: Any):
        self.db = db

    async def record(
        self,
        *,
        user_id: str,
        conversation_id: str | None,
        turn_id: str,
        provider_id: str,
        model_id: str,
        credential_slot: str,
        success: bool,
        error_code: str | None,
        duration_ms: int,
        input_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
        char_count: int,
        cap_decision: str,
    ) -> None:
        db = self.db
        if db is None:
            return
        created_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        statement = db.prepare(
            "INSERT INTO byok_call_usage "
            "(created_at, user_id, conversation_id, turn_id, provider_id, model_id, "
            "credential_slot, is_byok, success, error_code, duration_ms, "
            "input_tokens, output_tokens, total_tokens, char_count, cap_decision) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)"
        ).bind(
            created_at, user_id, conversation_id, turn_id, provider_id, model_id,
            credential_slot, 1 if success else 0, error_code, max(0, int(duration_ms)),
            input_tokens, output_tokens, total_tokens, max(0, int(char_count)), cap_decision,
        )
        await statement.run()


def new_turn_id() -> str:
    return "byok_" + uuid.uuid4().hex


def usage_numbers(result: Any) -> tuple[int | None, int | None, int | None, int]:
    usage: Mapping[str, Any] = {}
    if isinstance(result, Mapping) and isinstance(result.get("usage"), Mapping):
        usage = result["usage"]
    answer = result.get("answer") if isinstance(result, Mapping) else None
    char_count = len(answer) if isinstance(answer, str) else 0
    values = []
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(key)
        values.append(value if isinstance(value, int) and not isinstance(value, bool) else None)
    return values[0], values[1], values[2], char_count
