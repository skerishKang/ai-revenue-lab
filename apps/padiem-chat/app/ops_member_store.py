"""#8035 ②: the members tab store — the administrator sees every account
(the 대표 결정 "관리자는 다 본다"): sign-up date, last activity, tier, the AI
honorary-member flag, the feedback count and the email in the list; the
detail carries that member's feedback·conversation·PC-link counts and their
feedback rows. Read-only; every query is bound; no user-scoped route ever
reaches this store.
"""
from __future__ import annotations

import re
from typing import Any

from .d1_rows import rows_from_result

MEMBER_ID = re.compile(r"usr_[0-9a-f]{32}\Z")
_QUERY = re.compile(r"[0-9A-Za-z_.@가-힣 -]{1,80}\Z")
_PAGE_LIMIT = 50

_MEMBER_COLUMNS = (
    "u.id, u.display_name, u.email, u.created_at, u.ai_tester,"
    " (SELECT m.tier FROM b66_memberships m WHERE m.user_id = u.id) AS tier,"
    " (SELECT COUNT(*) FROM product_feedback f WHERE f.user_id = u.id)"
    "   AS feedback_count,"
    " (SELECT MAX(c.updated_at) FROM conversations c WHERE c.user_id = u.id AND c.deleted_at IS NULL)"
    "   AS last_activity"
)


class MemberMissing(Exception):
    pass


class OpsMemberUnavailable(Exception):
    pass


class D1OpsMemberStore:
    def __init__(self, db: Any):
        if db is None or not callable(getattr(db, "prepare", None)):
            raise ValueError("ops member binding missing")
        self._db = db

    async def _rows(self, sql: str, *values):
        try:
            result = await self._db.prepare(sql).bind(*values).run()
        except Exception:
            raise OpsMemberUnavailable() from None
        return [dict(row.to_py() if callable(getattr(row, "to_py", None)) else row)
                for row in rows_from_result(result)]

    async def list_members(self, *, query: str = "", cursor: str | None = None):
        clean = query.strip() if isinstance(query, str) else ""
        if clean and _QUERY.fullmatch(clean) is None:
            raise OpsMemberUnavailable()
        values: list[Any] = []
        predicates = []
        if clean:
            like = "%" + clean + "%"
            predicates.append("(u.display_name LIKE ? OR u.email LIKE ? OR u.id LIKE ?)")
            values.extend([like, like, like])
        if cursor:
            if not re.fullmatch(r"[0-9T:.\-]+Z\|usr_[0-9a-f]{32}", cursor):
                raise OpsMemberUnavailable()
            created, member_id = cursor.split("|", 1)
            predicates.append("(u.created_at, u.id) < (?, ?)")
            values.extend([created, member_id])
        where = (" WHERE " + " AND ".join(predicates)) if predicates else ""
        sql = ("SELECT " + _MEMBER_COLUMNS + " FROM users u" + where +
               " ORDER BY u.created_at DESC, u.id DESC LIMIT ?")
        values.append(_PAGE_LIMIT + 1)
        rows = await self._rows(sql, *values)
        members, next_cursor = rows[:_PAGE_LIMIT], None
        if len(rows) > _PAGE_LIMIT and members:
            last = members[-1]
            next_cursor = f"{last['created_at']}|{last['id']}"
        for member in members:
            member["ai_tester"] = member.get("ai_tester") == 1
            member["tier"] = member.get("tier") or "FREE"
        return members, next_cursor

    async def get_member(self, user_id: str):
        if not isinstance(user_id, str) or MEMBER_ID.fullmatch(user_id) is None:
            raise MemberMissing()
        rows = await self._rows(
            "SELECT " + _MEMBER_COLUMNS + " FROM users u WHERE u.id = ?", user_id)
        if not rows:
            raise MemberMissing()
        member = rows[0]
        member["ai_tester"] = member.get("ai_tester") == 1
        member["tier"] = member.get("tier") or "FREE"
        counts = await self._rows(
            "SELECT"
            " (SELECT COUNT(*) FROM product_feedback f WHERE f.user_id = ?) AS feedback,"
            " (SELECT COUNT(*) FROM conversations c WHERE c.user_id = ? AND c.deleted_at IS NULL) AS conversations,"
            " (SELECT COUNT(*) FROM pc_device_links p WHERE p.user_id = ?"
            "   AND p.state = 'active') AS pc_links",
            user_id, user_id, user_id)
        member["conversation_count"] = counts[0]["conversations"]
        member["pc_link_count"] = counts[0]["pc_links"]
        member["feedback_count"] = counts[0]["feedback"]
        feedback = await self._rows(
            "SELECT id, body, status, created_at FROM product_feedback"
            " WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 20",
            user_id)
        member["feedback"] = feedback
        return member
