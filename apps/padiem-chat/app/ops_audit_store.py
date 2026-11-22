"""#8035 ②: the operations audit trail store — who·when·what, one row per
administrator action and member-detail opening.

Written from two call sites that share one path (the #8035 원칙): the admin
routes (actor = the signed-in administrator's session user id) and the
operations tools (actor = the tool's fixed principal, `ops-tool`). Reads are
admin-only and return the newest rows first; nothing here ever reaches a
non-administrative response.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from .d1_rows import rows_from_result

AUDIT_ID = re.compile(r"opsaud_[0-9a-f]{32}\Z")
ACTION = re.compile(r"[a-z][a-z0-9_]{1,63}\Z")
ACTOR = re.compile(r".{1,256}\Z", re.S)
TARGET_TYPE = re.compile(r"[a-z][a-z0-9_]{1,31}\Z")
TARGET_ID = re.compile(r".{1,256}\Z", re.S)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class OpsAuditUnavailable(Exception):
    pass


class OpsAuditStore:
    """Append-only operations audit. `append` never raises into the caller's
    success path: a failed audit write degrades to False and the operation it
    describes still reports its own result, so the audit trail cannot be used
    to break an administrator action."""

    def __init__(self, db: Any):
        if db is None or not callable(getattr(db, "prepare", None)):
            raise ValueError("ops audit binding missing")
        self._db = db

    async def _rows(self, sql: str, *values):
        result = await self._db.prepare(sql).bind(*values).run()
        return [dict(row.to_py() if callable(getattr(row, "to_py", None)) else row)
                for row in rows_from_result(result)]

    async def append(self, *, actor_user_id: str, action: str, target_type: str,
                     target_id: str, detail: dict | None = None, dedupe_key: str | None = None) -> bool:
        if not isinstance(actor_user_id, str) or not ACTOR.fullmatch(actor_user_id):
            return False
        if not isinstance(action, str) or ACTION.fullmatch(action) is None:
            return False
        if not isinstance(target_type, str) or TARGET_TYPE.fullmatch(target_type) is None:
            return False
        if not isinstance(target_id, str) or not TARGET_ID.fullmatch(target_id):
            return False
        try:
            detail_json = json.dumps(detail if isinstance(detail, dict) else {},
                                     ensure_ascii=False, separators=(",", ":"))
        except Exception:
            detail_json = "{}"
        if len(detail_json) > 4096:
            detail_json = "{}"
        if dedupe_key is not None and (not isinstance(dedupe_key, str)
                                       or re.fullmatch(r"[0-9a-f]{64}", dedupe_key) is None):
            return False
        audit_id = "opsaud_" + (dedupe_key[:32] if dedupe_key else secrets.token_hex(16))
        try:
            await self._db.prepare(
                "INSERT INTO ops_audit_log (id, actor_user_id, action, target_type,"
                " target_id, detail_json, created_at) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO NOTHING"
            ).bind(audit_id, actor_user_id, action, target_type, target_id,
                   detail_json, _now()).run()
            return True
        except Exception:
            return False

    async def list_recent(self, *, limit: int = 20) -> list[dict]:
        bounded = limit if isinstance(limit, int) and 0 < limit <= 100 else 20
        try:
            rows = await self._rows(
                "SELECT id, actor_user_id, action, target_type, target_id,"
                " detail_json, created_at FROM ops_audit_log"
                " ORDER BY created_at DESC, id DESC LIMIT ?", bounded)
        except Exception:
            raise OpsAuditUnavailable() from None
        out = []
        for row in rows:
            try:
                detail = json.loads(row.get("detail_json") or "{}")
            except Exception:
                detail = {}
            out.append({"id": row["id"], "actor_user_id": row["actor_user_id"],
                        "action": row["action"], "target_type": row["target_type"],
                        "target_id": row["target_id"], "detail": detail,
                        "created_at": row["created_at"]})
        return out
