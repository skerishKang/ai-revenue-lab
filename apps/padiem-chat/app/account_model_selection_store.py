"""#5222 account-scoped "last selected AI tier" (a UI preference, never authority).

The browser may only say "this is the tier I picked". It can never say *which
account* that preference belongs to: the row is always keyed by the canonical
product user id that the signed session already resolved, so an account switch
can never inherit or forge another account's selection.

The stored value is a preference only. Model access stays with the server-side
member grade and the verified administrator gate, which are re-checked on every
read here and again on every model request.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .history import _row_to_dict

# The canonical product account id (see app.history._user_id /
# app.history._password_user_id). A value outside this shape is never a
# product account, so it can never own a stored preference.
_UID = re.compile(r"^usr_[0-9a-f]{32}$")

# The selectable tiers. "admin" is the verified administrator lane; it is not a
# member grade and never widens the grade ladder.
SELECTABLE_TIERS = ("free", "plus", "pro", "max", "admin")


class AccountModelSelectionError(Exception):
    """The requested account or tier is not a storable account preference."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class D1AccountModelSelectionStore:
    """One account's last selected tier over the existing PADIEM_CHAT_DB D1."""

    def __init__(self, db: Any):
        if db is None or not callable(getattr(db, "prepare", None)):
            raise ValueError("account model selection binding missing")
        self._db = db

    @staticmethod
    def _valid_account(user_id: object) -> bool:
        return isinstance(user_id, str) and _UID.fullmatch(user_id) is not None

    async def load(self, user_id: str) -> dict[str, str] | None:
        """The stored preference of exactly this account, or None.

        A row whose tier is not a currently selectable tier is treated as
        absent: a corrupted or hand-edited row never becomes a usable tier.
        """
        if not self._valid_account(user_id):
            return None
        row = _row_to_dict(
            await self._db.prepare(
                "SELECT tier, updated_at FROM padiem_account_model_selections "
                "WHERE user_id=?"
            ).bind(user_id).first()
        )
        if row is None:
            return None
        tier = row.get("tier")
        if not isinstance(tier, str) or tier not in SELECTABLE_TIERS:
            return None
        updated_at = row.get("updated_at")
        return {
            "tier": tier,
            "updated_at": updated_at if isinstance(updated_at, str) else "",
        }

    async def save(self, user_id: str, tier: str) -> dict[str, str]:
        """Replace exactly this account's stored preference."""
        if not self._valid_account(user_id):
            raise AccountModelSelectionError("invalid account")
        if not isinstance(tier, str) or tier not in SELECTABLE_TIERS:
            raise AccountModelSelectionError("invalid tier")
        updated_at = _now()
        await self._db.prepare(
            "INSERT INTO padiem_account_model_selections "
            "(user_id, tier, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "tier=excluded.tier, updated_at=excluded.updated_at"
        ).bind(user_id, tier, updated_at).run()
        return {"tier": tier, "updated_at": updated_at}
