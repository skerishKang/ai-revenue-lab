"""Explicit B66 member-to-operator inquiries with durable D1 alert receipts.

A chat prompt is not an inquiry. Only a signed-in user's deliberate form
submission enters this table. External notifications are best effort; receipt
tracking permits retries without re-sending successfully delivered channels.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .history import _row_to_dict, _rows_from_result

_CATEGORIES = {"general", "usage", "billing", "bug", "other"}
_ID = re.compile(r"b66inq_[0-9a-f]{32}\Z")
_CHANNELS = {"telegram", "discord", "email"}
_NO_STORE = {"Cache-Control": "no-store, max-age=0"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _error(code: str, status: int) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code}}, status_code=status, headers=_NO_STORE)


class D1B66InquiryStore:
    def __init__(self, db: Any):
        if db is None or not callable(getattr(db, "prepare", None)):
            raise ValueError("inquiry D1 binding missing")
        self.db = db

    def _stmt(self, sql: str, *params: Any) -> Any:
        stmt = self.db.prepare(sql)
        return stmt.bind(*params) if params else stmt

    async def _first(self, sql: str, *params: Any) -> dict | None:
        return _row_to_dict(await self._stmt(sql, *params).first())

    async def _all(self, sql: str, *params: Any) -> list[dict]:
        return _rows_from_result(await self._stmt(sql, *params).run())

    async def submit(self, user_id: str, category: str, subject: str, body: str) -> dict:
        threshold = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")
        recent = await self._first(
            "SELECT count(*) AS n FROM b66_member_inquiries WHERE user_id=? AND created_at>=?",
            user_id, threshold,
        )
        if int((recent or {}).get("n") or 0) >= 3:
            raise ValueError("inquiry_rate_limited")
        inquiry_id = "b66inq_" + uuid.uuid4().hex
        now = _now()
        await self._stmt(
            "INSERT INTO b66_member_inquiries "
            "(inquiry_id,user_id,category,subject,body,status,created_at,updated_at) "
            "VALUES (?,?,?,?,?,'open',?,?)",
            inquiry_id, user_id, category, subject, body, now, now,
        ).run()
        return {"inquiry_id": inquiry_id, "user_id": user_id,
                "category": category, "subject": subject, "body": body,
                "status": "open", "created_at": now}

    async def list_user(self, user_id: str) -> list[dict]:
        return await self._all(
            "SELECT inquiry_id,category,subject,body,status,created_at,updated_at "
            "FROM b66_member_inquiries WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
            user_id,
        )

    async def list_admin(self, status: str = "all") -> list[dict]:
        if status not in {"all", "open", "resolved"}:
            raise ValueError("invalid_status")
        sql = ("SELECT i.inquiry_id,i.user_id,i.category,i.subject,i.body,i.status,"
               "i.created_at,i.updated_at,i.delivered_at,u.email "
               "FROM b66_member_inquiries i JOIN users u ON u.id=i.user_id")
        if status == "all":
            return await self._all(sql + " ORDER BY i.created_at DESC LIMIT 100")
        return await self._all(
            sql + " WHERE i.status=? ORDER BY i.created_at DESC LIMIT 100", status)

    async def set_status(self, inquiry_id: str, status: str) -> bool:
        if not _ID.fullmatch(inquiry_id) or status not in {"open", "resolved"}:
            raise ValueError("invalid_status")
        await self._stmt(
            "UPDATE b66_member_inquiries SET status=?,updated_at=? WHERE inquiry_id=?",
            status, _now(), inquiry_id,
        ).run()
        return bool(await self._first(
            "SELECT inquiry_id FROM b66_member_inquiries WHERE inquiry_id=?", inquiry_id))

    async def pending(self, limit: int = 5) -> list[dict]:
        return await self._all(
            "SELECT inquiry_id,category,subject,body FROM b66_member_inquiries "
            "WHERE delivered_at IS NULL ORDER BY created_at ASC LIMIT ?",
            max(1, min(int(limit), 10)),
        )

    async def receipt_exists(self, inquiry_id: str, channel: str) -> bool:
        if not _ID.fullmatch(inquiry_id) or channel not in _CHANNELS:
            return False
        row = await self._first(
            "SELECT inquiry_id FROM b66_inquiry_alert_delivery "
            "WHERE inquiry_id=? AND channel=?", inquiry_id, channel)
        return row is not None

    async def record_receipt(self, inquiry_id: str, channel: str) -> None:
        if not _ID.fullmatch(inquiry_id) or channel not in _CHANNELS:
            raise ValueError("invalid_receipt")
        await self._stmt(
            "INSERT OR IGNORE INTO b66_inquiry_alert_delivery"
            "(inquiry_id,channel,delivered_at) VALUES (?,?,?)",
            inquiry_id, channel, _now(),
        ).run()

    async def complete_delivery(self, inquiry_id: str, channels: tuple[str, ...]) -> bool:
        if not channels or not _ID.fullmatch(inquiry_id):
            return False
        for channel in channels:
            if not await self.receipt_exists(inquiry_id, channel):
                return False
        await self._stmt(
            "UPDATE b66_member_inquiries SET delivered_at=? "
            "WHERE inquiry_id=? AND delivered_at IS NULL",
            _now(), inquiry_id,
        ).run()
        return True


async def deliver_inquiry(store: D1B66InquiryStore, notifier: Any, entry: dict) -> dict:
    result = {"sent": 0, "failed": 0}
    if notifier is None or not getattr(notifier, "channels", None):
        return result
    inquiry_id = entry["inquiry_id"]
    # Intentionally do not forward the full inquiry, email, or attached data
    # to external channels. Admins retrieve details via authenticated page.
    label = {
        "general": "일반 문의", "usage": "사용 방법", "billing": "요금·계정",
        "bug": "오류 신고", "other": "기타",
    }.get(entry["category"], "회원 문의")
    msg = ("[B66 회원 문의] " + label + "\n문의번호: " + inquiry_id +
           "\n관리자 화면: https://quick-quote-kr.pages.dev/admin-inquiries.html")
    for channel in tuple(notifier.channels):
        if await store.receipt_exists(inquiry_id, channel):
            continue
        if await notifier._send(channel, message=msg, subject="[B66] 회원 문의 접수"):
            await store.record_receipt(inquiry_id, channel)
            result["sent"] += 1
        else:
            result["failed"] += 1
    await store.complete_delivery(inquiry_id, tuple(notifier.channels))
    return result


async def b66_inquiries(request: Request) -> JSONResponse:
    uid = current_user_id(request)
    if not uid:
        return _error("auth_required", 401)
    store = getattr(request.app.state, "b66_inquiry_store", None)
    if store is None:
        return _error("inquiries_unavailable", 503)
    if request.method == "GET":
        try:
            return JSONResponse({"ok": True, "inquiries": await store.list_user(uid)},
                                headers=_NO_STORE)
        except Exception:
            return _error("inquiries_unavailable", 503)
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        return _error("invalid_content_type", 415)
    try:
        raw = await read_bounded_request_body(request, max_bytes=8192)
        data = json.loads(raw.decode("utf-8"))
    except RequestBodyTooLarge:
        return _error("inquiry_too_large", 413)
    except (ValueError, UnicodeError, TypeError):
        return _error("invalid_json", 400)
    if not isinstance(data, dict) or set(data) != {"category", "subject", "body"}:
        return _error("invalid_fields", 400)
    category, subject, body = data["category"], data["subject"], data["body"]
    if not (isinstance(category, str) and category in _CATEGORIES
            and isinstance(subject, str) and 1 <= len(subject.strip()) <= 120
            and isinstance(body, str) and 5 <= len(body.strip()) <= 3000
            and not any(ord(c) < 32 and c not in "\n\t" for c in subject+body)):
        return _error("invalid_inquiry", 400)
    try:
        result = await store.submit(uid, category, subject.strip(), body.strip())
    except ValueError as e:
        if str(e) == "inquiry_rate_limited":
            return _error("inquiry_rate_limited", 429)
        return _error("invalid_inquiry", 400)
    except Exception:
        return _error("inquiries_unavailable", 503)
    try:
        await deliver_inquiry(store, getattr(request.app.state, "b66_signup_notifier", None), result)
    except Exception:
        pass  # Durable outbox preserved; an alert failure never drops the inquiry.
    return JSONResponse({"ok": True, "inquiry_id": result["inquiry_id"]},
                        status_code=201, headers=_NO_STORE)


async def _admin_store(request: Request) -> tuple[Any, JSONResponse | None]:
    uid = current_user_id(request)
    if not uid:
        return None, _error("auth_required", 401)
    admin_store = getattr(request.app.state, "b66_member_admin_store", None)
    store = getattr(request.app.state, "b66_inquiry_store", None)
    if admin_store is None or store is None:
        return None, _error("admin_unavailable", 503)
    try:
        if not await admin_store.is_google_admin(uid):
            return None, _error("admin_forbidden", 403)
    except Exception:
        return None, _error("admin_unavailable", 503)
    return store, None


async def b66_admin_inquiries(request: Request) -> JSONResponse:
    store, err = await _admin_store(request)
    if err is not None:
        return err
    status = request.query_params.get("status", "all")
    if status not in {"all", "open", "resolved"}:
        return _error("invalid_status", 400)
    try:
        entries = await store.list_admin(status)
    except Exception:
        return _error("inquiries_unavailable", 503)
    return JSONResponse({"ok": True, "inquiries": entries,
                         "notification_delivery_configured": bool(
                             getattr(getattr(request.app.state, "b66_signup_notifier", None),
                                     "channels", None))}, headers=_NO_STORE)


async def b66_admin_inquiry_status(request: Request) -> JSONResponse:
    store, err = await _admin_store(request)
    if err is not None:
        return err
    inquiry_id = request.path_params.get("inquiry_id", "")
    if not _ID.fullmatch(inquiry_id):
        return _error("invalid_inquiry_id", 400)
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        return _error("invalid_content_type", 415)
    try:
        raw = await read_bounded_request_body(request, max_bytes=512)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != {"status"}:
            return _error("invalid_fields", 400)
        updated = await store.set_status(inquiry_id, payload["status"])
    except (ValueError, UnicodeError, TypeError):
        return _error("invalid_status", 400)
    except RequestBodyTooLarge:
        return _error("inquiry_too_large", 413)
    except Exception:
        return _error("inquiries_unavailable", 503)
    if not updated:
        return _error("inquiry_not_found", 404)
    return JSONResponse({"ok": True}, headers=_NO_STORE)


async def b66_admin_inquiry_dispatch(request: Request) -> JSONResponse:
    store, err = await _admin_store(request)
    if err is not None:
        return err
    notifier = getattr(request.app.state, "b66_signup_notifier", None)
    if not getattr(notifier, "channels", None):
        return _error("inquiry_notifications_not_configured", 503)
    summary = {"sent": 0, "failed": 0, "processed": 0}
    try:
        for entry in await store.pending(limit=5):
            result = await deliver_inquiry(store, notifier, entry)
            summary["sent"] += result["sent"]
            summary["failed"] += result["failed"]
            summary["processed"] += 1
    except Exception:
        return _error("inquiry_dispatch_failed", 503)
    return JSONResponse({"ok": True, "result": summary}, headers=_NO_STORE)
