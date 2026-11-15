"""#7690 stage 2 — site feedback administrator site assignments.

The signed Chat session is the only identity input; which sites an account may
see lives in the canonical Chat D1 (migration 119). Designation and removal
happen only through the ops tool — no browser path writes this table. Unknown
site keys are refused everywhere, and the account value never reaches a
response body.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .d1_rows import rows_from_result
from .site_feedback_store import SITE_KEYS

_UID = re.compile(r"usr_[0-9a-f]{32}\Z")


class D1SiteFeedbackAdminAuthorizer:
    """Site assignment lookups for the signed account, over the canonical D1."""

    def __init__(self, db: Any):
        if db is None or not callable(getattr(db, "prepare", None)):
            raise ValueError("site feedback admin requires the canonical Chat D1")
        self._db = db

    async def _rows(self, sql, *values):
        result = await self._db.prepare(sql).bind(*values).run()
        rows = rows_from_result(result)
        return [dict(row.to_py() if callable(getattr(row, "to_py", None)) else row) for row in rows]

    async def sites_for(self, *, user_id: str) -> frozenset[str]:
        """Site keys the account manages; empty set for a non-admin."""
        if not isinstance(user_id, str) or _UID.fullmatch(user_id) is None:
            return frozenset()
        rows = await self._rows(
            "SELECT site FROM site_feedback_admins WHERE user_id=? ORDER BY site", user_id)
        return frozenset(
            row["site"] for row in rows
            if isinstance(row.get("site"), str) and row["site"] in SITE_KEYS
        )

    async def is_site_admin(self, *, user_id: str, site: str) -> bool:
        if not isinstance(user_id, str) or _UID.fullmatch(user_id) is None:
            return False
        if not isinstance(site, str) or site not in SITE_KEYS:
            return False
        rows = await self._rows(
            "SELECT 1 AS one FROM site_feedback_admins WHERE user_id=? AND site=?",
            user_id, site)
        return bool(rows)

    async def assign(self, *, user_id: str, site: str, now: str | None = None) -> str:
        """Central-admin-only designation. 'assigned' | 'already' | 'missing'."""
        if not isinstance(user_id, str) or _UID.fullmatch(user_id) is None:
            raise ValueError("site_feedback_admin_invalid_account")
        if not isinstance(site, str) or site not in SITE_KEYS:
            raise ValueError("site_feedback_admin_invalid_site")
        found = await self._rows("SELECT 1 AS one FROM users WHERE id=?", user_id)
        if not found:
            return "missing"
        stamp = now or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        rows = await self._rows(
            "INSERT INTO site_feedback_admins (user_id, site, created_at) VALUES (?,?,?) "
            "ON CONFLICT(user_id, site) DO NOTHING RETURNING site", user_id, site, stamp)
        return "assigned" if rows else "already"

    async def unassign(self, *, user_id: str, site: str) -> str:
        """Central-admin-only removal. 'removed' | 'not-assigned'."""
        if not isinstance(user_id, str) or _UID.fullmatch(user_id) is None:
            raise ValueError("site_feedback_admin_invalid_account")
        if not isinstance(site, str) or site not in SITE_KEYS:
            raise ValueError("site_feedback_admin_invalid_site")
        rows = await self._rows(
            "DELETE FROM site_feedback_admins WHERE user_id=? AND site=? RETURNING site",
            user_id, site)
        return "removed" if rows else "not-assigned"
