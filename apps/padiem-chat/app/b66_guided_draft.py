"""B66 #3396 private guided-in-progress state. No chat or file/model payloads.

Bounded 3-item state; exactly one slot per server-derived owner/workspace.
Only canonical fields are persisted. This does not store QuoteCore computed totals.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .b66_quote_history_routes import _owner_and_workspace, _reject_client_owner, _NO_STORE

MAX_STATE_BYTES = 16384
SCHEMA = "b66.guided-draft.v1"
STEPS = frozenset({
    "recipientCompany", "recipientPerson", "itemName", "qty", "price",
    "moreItems", "tax", "memo", "senderChoice", "senderCompany", "summary",
})
SCALARS = ("name", "qty", "unitPrice", "unit")


class GuidedDraftError(ValueError):
    pass


def _safe_text(value: Any, *, limit: int = 240) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise GuidedDraftError("invalid guided text")
    value.encode("utf-8")  # Reject lone Unicode surrogates.
    return value


def _optional_text(value: Any, *, limit: int = 240) -> str:
    if value is None:
        return ""
    return _safe_text(value, limit=limit)


def _object(value: Any, allowed: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) - allowed:
        raise GuidedDraftError("unexpected guided fields")
    return value


def _finite_number(value: Any, *, positive: bool = False) -> int | float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GuidedDraftError("invalid guided number")
    if not math.isfinite(value) or value < 0 or (positive and value == 0) or value > 10**12:
        raise GuidedDraftError("out-of-range guided number")
    return value


def normalize_guided_state(payload: Any) -> dict:
    data = _object(payload, {"schema", "mode", "step", "currentItem", "taxUnknown", "savedSkillId", "draft"})
    if data.get("schema") != SCHEMA or data.get("mode") != "guided" or data.get("step") not in STEPS:
        raise GuidedDraftError("unsupported guided schema or step")
    skill = _optional_text(data.get("savedSkillId"), limit=64)
    if skill and (not skill.startswith("b66skill_") or len(skill) != 41 or
                  any(x not in "0123456789abcdef" for x in skill[9:])):
        raise GuidedDraftError("invalid assigned Skill")
    draft = _object(data.get("draft"), {"recipient", "sender", "items", "tax", "memo", "meta"})
    recipient = _object(draft.get("recipient"), {"company", "person", "address", "email"})
    sender = _object(draft.get("sender"), {"company"})
    tax = _object(draft.get("tax"), {"mode"})
    meta = _object(draft.get("meta"), {"quoteNo", "issueDate"})
    mode = _optional_text(tax.get("mode"), limit=40)
    if mode not in {"EXCLUSIVE", "INCLUSIVE", "EXEMPT"}:
        raise GuidedDraftError("invalid tax mode")
    items = draft.get("items")
    if not isinstance(items, list) or len(items) > 3:
        raise GuidedDraftError("guided item limit exceeded")
    bounded_items = []
    for item in items:
        row = _object(item, {"id", *SCALARS})
        bounded_items.append({
            "id": _optional_text(row.get("id"), limit=64),
            "name": _optional_text(row.get("name"), limit=300),
            "unit": _optional_text(row.get("unit"), limit=40),
            "qty": _finite_number(row.get("qty"), positive=True),
            "unitPrice": _finite_number(row.get("unitPrice")),
        })
    idx = data.get("currentItem")
    if isinstance(idx, bool) or not isinstance(idx, int) or idx < -1 or idx >= len(items):
        raise GuidedDraftError("invalid guided item index")
    if data["step"] in {"qty", "price"} and idx < 0:
        raise GuidedDraftError("guided item step requires a selected item")
    if not isinstance(data.get("taxUnknown"), bool):
        raise GuidedDraftError("invalid guided tax flag")
    sanitized = {
        "schema": SCHEMA, "mode": "guided", "step": data["step"],
        "currentItem": idx, "taxUnknown": data["taxUnknown"],
        "savedSkillId": skill,
        "draft": {
            "recipient": {key: _optional_text(recipient.get(key)) for key in ("company", "person", "address", "email")},
            "sender": {"company": _optional_text(sender.get("company"))},
            "items": bounded_items,
            "tax": {"mode": mode},
            "memo": _optional_text(draft.get("memo"), limit=1200),
            "meta": {
                "quoteNo": _optional_text(meta.get("quoteNo"), limit=100),
                "issueDate": _optional_text(meta.get("issueDate"), limit=32),
            },
        },
    }
    try:
        encoded = json.dumps(sanitized, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":"), sort_keys=True).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise GuidedDraftError("guided JSON invalid") from exc
    if len(encoded) > MAX_STATE_BYTES:
        raise GuidedDraftError("guided state too large")
    return sanitized


class D1GuidedDraftStore:
    def __init__(self, db: Any):
        if db is None:
            raise ValueError("D1 binding required")
        self.db = db

    async def load(self, *, user_id: str, workspace_id: str) -> dict | None:
        row = await self.db.prepare(
            "SELECT state_json FROM b66_guided_draft WHERE user_id=? AND workspace_id=?"
        ).bind(user_id, workspace_id).first()
        if row is None:
            return None
        if not isinstance(row, dict):
            row = row.to_py() if callable(getattr(row, "to_py", None)) else dict(row)
        raw = row.get("state_json")
        if not isinstance(raw, str) or len(raw) > MAX_STATE_BYTES:
            raise GuidedDraftError("invalid stored guided state")
        try:
            return normalize_guided_state(json.loads(raw))
        except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
            raise GuidedDraftError("invalid stored guided state") from exc

    async def save(self, *, user_id: str, workspace_id: str, state: dict) -> None:
        payload = normalize_guided_state(state)
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":"), sort_keys=True)
        updated = datetime.now(timezone.utc).isoformat()
        await self.db.prepare(
            "INSERT INTO b66_guided_draft (user_id,workspace_id,state_json,updated_at)"
            " VALUES (?,?,?,?) ON CONFLICT(user_id,workspace_id) DO UPDATE"
            " SET state_json=excluded.state_json,updated_at=excluded.updated_at"
        ).bind(user_id, workspace_id, encoded, updated).run()

    async def clear(self, *, user_id: str, workspace_id: str) -> None:
        await self.db.prepare(
            "DELETE FROM b66_guided_draft WHERE user_id=? AND workspace_id=?"
        ).bind(user_id, workspace_id).run()


def _error(status: int, code: str) -> Response:
    return JSONResponse({"ok": False, "error": {"code": code}},
                        status_code=status, headers=_NO_STORE)


async def guided_draft_route(request: Request) -> Response:
    scope = await _owner_and_workspace(request)
    if scope is None:
        return _error(401, "unauthorized")
    uid, workspace_id = scope
    store = getattr(request.app.state, "b66_guided_draft_store", None)
    if store is None:
        return _error(503, "guided_state_unavailable")

    try:
        if request.method == "GET":
            try:
                state = await store.load(user_id=uid, workspace_id=workspace_id)
            except Exception:
                return _error(503, "guided_state_read_failed")
            return JSONResponse({"ok": True, "state": state}, headers=_NO_STORE)
        if request.method == "DELETE":
            try:
                await store.clear(user_id=uid, workspace_id=workspace_id)
            except Exception:
                return _error(503, "guided_state_delete_failed")
            return JSONResponse({"ok": True}, headers=_NO_STORE)
        if request.method != "PUT":
            return _error(405, "method_not_allowed")
        if (request.headers.get("content-length") or "").isdigit() and int(
                request.headers["content-length"]) > MAX_STATE_BYTES:
            return _error(413, "guided_state_too_large")
        raw = await request.body()
        if len(raw) > MAX_STATE_BYTES:
            return _error(413, "guided_state_too_large")
        data = json.loads(raw)
        if _reject_client_owner(data):
            return _error(400, "client_owner_not_allowed")
        state = normalize_guided_state(data)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return _error(400, "invalid_guided_state")
    try:
        await store.save(user_id=uid, workspace_id=workspace_id, state=state)
    except Exception:
        return _error(503, "guided_state_write_failed")
    return JSONResponse({"ok": True}, headers=_NO_STORE)
