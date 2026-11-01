"""Owner-scoped PC delegation settings on the existing Chat database binding."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any

from padiem_ai_core.pc_delegation import parse_pc_delegation

from .history import _row_to_dict


_UID = re.compile(r"^usr_[0-9a-f]{32}$")


class PcDelegationStoreError(ValueError):
    pass


def validate_stored_pc_delegation(value):
    if not isinstance(value, dict) or set(value) != {"version", "rules"}:
        raise PcDelegationStoreError("PC delegation settings are invalid")
    try:
        return parse_pc_delegation(value)
    except (TypeError, ValueError) as exc:
        raise PcDelegationStoreError("PC delegation settings are invalid") from exc


class D1PcDelegationStore:
    """One atomic settings document per authenticated product account.

    Uses PADIEM_CHAT_DB, including its existing local SQLite adapter on COM2.
    An unreadable row raises; it never silently removes an 'always ask' rule.
    """

    def __init__(self, db: Any):
        if db is None or not callable(getattr(db, "prepare", None)):
            raise ValueError("PC delegation database binding is missing")
        self._db = db

    @staticmethod
    def _account(user_id):
        if not isinstance(user_id, str) or _UID.fullmatch(user_id) is None:
            raise PcDelegationStoreError("Invalid account")
        return user_id

    async def load(self, user_id: str) -> dict[str, Any]:
        row = _row_to_dict(await self._db.prepare(
            "SELECT settings_json, updated_at FROM padiem_pc_delegations WHERE user_id=?"
        ).bind(self._account(user_id)).first())
        if row is None:
            return {"version": 1, "rules": [], "updated_at": None}
        try:
            settings = validate_stored_pc_delegation(json.loads(row["settings_json"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise PcDelegationStoreError("Stored PC delegation settings are unreadable") from exc
        return {**settings, "updated_at": row.get("updated_at")}

    async def save(self, user_id: str, value) -> dict[str, Any]:
        user_id = self._account(user_id)
        settings = validate_stored_pc_delegation(value)
        updated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        await self._db.prepare(
            "INSERT INTO padiem_pc_delegations (user_id,settings_json,updated_at) VALUES (?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET settings_json=excluded.settings_json, updated_at=excluded.updated_at"
        ).bind(user_id, json.dumps(settings, ensure_ascii=False, separators=(",", ":")), updated_at).run()
        return {**settings, "updated_at": updated_at}
